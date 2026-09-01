"""WebSocket 面试主循环（原 main.py 单体的最大职责块，v7.2.2 拆出）。

协议不变：{type, data} 消息嵌套；
会话不存在（4000/session_not_found）；正常完成 1000 关闭。

v8.3: 握手阶段不再校验身份（4001 unauthorized 随认证一起下线）。
"""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import config
from ..db import (
    save_report, update_session_status, save_weakness_profile, update_session_flow,
    get_session,
)
from ..interview_engine.flow import FlowState
from ..interview_engine.session import is_end_signal
from ..schemas import InterviewMode, InterviewStage
from ..security import full_check, check_output
from .. import weakness_memory
from ..db import list_unresolved_weaknesses
from . import state

logger = logging.getLogger(__name__)
router = APIRouter()


def _answer_texts(session) -> list[str]:
    """
    提取历史回答的纯文本列表。
    security.full_check 的重复检测要求 list[str]，
    而 session.answer_history 存的是含题目上下文的 dict。
    """
    texts = []
    for item in getattr(session, "answer_history", []) or []:
        if isinstance(item, dict):
            t = item.get("answer", "")
        else:
            t = str(item)
        if t:
            texts.append(t)
    return texts


async def _mark_flow(session_id: str, session, state_: "FlowState") -> None:
    """v7.0: 记录流程位置并落库。

    为什么单独封装：落库是"锦上添花"的能力，绝不能因为它失败而中断面试。
    所以这里吞掉所有异常，只记 debug 日志 —— 面试可用性优先于进度可观测性。

    为什么不做断点续答：那需要把 InterviewSession 的全部字段（轮次配置、
    诊断历史、追问状态、难度调度器……）序列化并从 DB 重建，改动面与风险都
    远大于收益。当前只保证"流程位置可追溯、答题进度不因重启归零"。
    """
    try:
        session.set_flow_state(state_)
        await update_session_flow(session_id, state_.value, session.answered_count)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[flow] 流程状态落库失败 session={session_id} state={state_}: {e}")


@router.websocket("/ws/interview/{session_id}")
async def ws_interview(websocket: WebSocket, session_id: str):
    """面试主循环握手。

    会话存在性在 accept() 之后以 4000/session_not_found 关闭（原本还要在
    accept() 之前做 4001 身份校验，v8.3 随认证下线一并移除）。
    """
    await websocket.accept()
    async with state.session_lock:
        session = state.active_sessions.get(session_id)

    if not session:
        await websocket.send_json({"type": "error", "data": {"message": "会话不存在"}})
        await websocket.close(code=4000, reason="session_not_found")
        return

    try:
        # 1. 发送面试官信息（v2.4: 含模式信息；v5.0: 含阶段信息）
        await websocket.send_json({
            "type": "interviewer_info",
            "data": {
                "style": session.style,
                "mode": session.mode,
                "stage": session.stage,
                "total_rounds": len(session.rounds),
                "rounds_info": [{"index": r["round_index"], "name": r["name"]}
                                for r in session.rounds],
            }
        })

        # v6.3 长期记忆闭环：历史未解决薄弱点回注入（失败降级，不阻断面试）
        # v6.5: 优先用 EMA 薄弱度排序；新表为空（老库刚升级、还没跑过完整会话）
        #       时回退 v6.3 口径，否则升级后首场面试会静默丢掉记忆回注入。
        try:
            points = await weakness_memory.active_memory_points(limit=10)
            if not points:
                points = await list_unresolved_weaknesses(limit=10)
            session.set_long_term_memory(points)
        except Exception as e:
            logger.warning(f"长期记忆回注入跳过: {e}")

        # v2.6: 按 JD 动态计算各维度权重，并告知前端本场评分口径
        weights_payload = await session.init_weights()
        await websocket.send_json({
            "type": "dimension_weights",
            "data": weights_payload,
        })

        # v2.4: 发送初始面试官信息
        init_intv = session.get_interviewer_change_event()
        if init_intv:
            await websocket.send_json({
                "type": "interviewer_change",
                "data": init_intv,
            })

        # 2. 面试主循环
        # v6.1: user_ended = 候选人输入"结束面试"退出口令，主动收束面试（借鉴 offerMaster）
        user_ended = False
        while not session.is_finished and not user_ended:
            info = session.current_round_info()

            # 轮次开始
            await websocket.send_json({
                "type": "round_start",
                "data": {"round": session.current_round, "name": info["name"]}
            })

            # v2.4: 发送面试官切换事件（新轮次开始时）
            intv_event = session.get_interviewer_change_event()
            if intv_event:
                await websocket.send_json({
                    "type": "interviewer_change",
                    "data": intv_event,
                })

            # 生成题目
            if not session.round_questions:
                await session.generate_questions()

            if not session.round_questions:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"{info['name']}题目生成失败，跳过本轮"}
                })
                session.advance_round()
                continue

            # 题目循环
            while session.has_more_questions_in_round() and not user_ended:
                q = session.current_question
                if not isinstance(q, dict):
                    break
                # v7.0: 出题即标记"等待回答"并落库 —— 让进程重启后仍能看出
                # 这场面试停在哪一题（注意：只落进度，不做断点续答）。
                await _mark_flow(session_id, session, FlowState.WAITING_ANSWER)
                await websocket.send_json({
                    "type": "question",
                    "data": {
                        "round": session.current_round,
                        "index": session.current_question_idx + 1,
                        "total": len(session.round_questions),
                        "question": q.get("question", ""),
                        "intent": q.get("intent", ""),
                        "is_extra": q.get("is_extra", False),
                        "focus_dimension": q.get("focus_dimension", ""),
                        "focus_dimension_name": q.get("focus_dimension_name", ""),
                        "question_type": q.get("question_type", ""),
                        # v6.3: 压力题标记（pressure_bank 注入），前端渲染"压力题"徽章
                        "is_pressure": bool(q.get("is_pressure", False)),
                        "pressure_topic": q.get("topic", ""),
                        # v6.4: 出题依据（session.question_basis 确定性拼装），
                        # 前端渲染"本题依据"chip；空串时前端不渲染
                        "basis": session.question_basis(q),
                    }
                })

                # 等待回答
                answer_received = False
                while not answer_received:
                    msg = await websocket.receive_json()
                    msg_type = msg.get("type", "")
                    data = msg.get("data", {})

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong", "data": {}})
                        continue

                    # v5.0: 会话中切换模式/阶段（实时生效）
                    if msg_type == "switch_mode":
                        mode_val = data.get("mode", "")
                        stage_val = data.get("stage") or None
                        try:
                            mode = InterviewMode(mode_val).value if mode_val else None
                            stage = InterviewStage(stage_val).value if stage_val else None
                        except ValueError:
                            await websocket.send_json({
                                "type": "error",
                                "data": {"message": f"未知模式或阶段: {mode_val} / {stage_val}"}
                            })
                            continue
                        if mode:
                            event = session.switch_mode(mode, stage)
                        elif stage:
                            event = session.switch_mode(session.mode, stage)
                        else:
                            continue
                        session.pending_follow_up = ""
                        await websocket.send_json({"type": "mode_change", "data": event})
                        continue

                    # v6.5: 面试技能（有状态多轮）—— 默认显式触发，
                    # 不在回答里做关键词猜测（原版纯 strings.Contains 会把普通回答误判成触发）。
                    if msg_type == "skill":
                        action = str(data.get("action", "")).strip()
                        if action == "list":
                            await websocket.send_json({
                                "type": "skill_list",
                                "data": {"skills": session.skill_registry.list()},
                            })
                        elif action == "activate":
                            event = session.activate_skill(data.get("name", ""))
                            await websocket.send_json({"type": "skill_start", "data": event})
                            if event.get("ok"):
                                opening = await session.generate_skill_turn()
                                if opening:
                                    await websocket.send_json({
                                        "type": "follow_up",
                                        "data": {
                                            "question": opening,
                                            "reason": event.get("skill", ""),
                                            "skill": event.get("skill", ""),
                                            "step": 1,
                                            "total": event.get("total_steps", 1),
                                        },
                                    })
                        elif action == "deactivate":
                            event = session.deactivate_skill(reason="user_exit")
                            await websocket.send_json({"type": "skill_end", "data": event})
                        continue

                    if msg_type != "answer":
                        continue

                    answer_text = data.get("text", "")

                    # v6.1: 结束面试退出口令检测（借鉴 offerMaster is_end_signal）。
                    # 放在安全检查之前：口令文本过短，会被质量校验拦截而永远无法命中。
                    # 命中后不诊断、不计分，直接收束面试并照常生成部分报告。
                    if is_end_signal(answer_text):
                        user_ended = True
                        await websocket.send_json({
                            "type": "interview_end_signal",
                            "data": {"message": "收到结束信号，面试到此结束，正在生成面评报告……"}
                        })
                        break

                    # v6.1: 语音来源标记（前端 source=voice 时，诊断注入 ASR 容错评分话术）
                    from_voice = (str(data.get("source", "")).lower() == "voice"
                                  or bool(data.get("from_voice")))

                    # v6.2: 思考时长（前端从题目展示到提交作答的秒数，进报告 qaBreakdown）
                    thinking_seconds = data.get("thinking_seconds", 0) or 0

                    # v2.1: 4 层安全检查（full_check 返回 (pass_all, reason)）
                    passed, reason = full_check(answer_text, _answer_texts(session))
                    if not passed:
                        await websocket.send_json({
                            "type": "security_block",
                            "data": {"reason": reason}
                        })
                        continue

                    # v6.5: 技能进行中 → 走技能轮，**不诊断**。
                    # 测验答案（"B"）拿去打五维分只会污染报告，技能轮单独维护对话历史。
                    if session.is_skill_active():
                        skill_name = session.active_skill
                        progress = session.advance_skill(answer_text)
                        if progress.get("completed"):
                            await websocket.send_json({
                                "type": "skill_end",
                                "data": {
                                    "skill": skill_name,
                                    "reason": "completed",
                                    "message": progress.get("message", ""),
                                },
                            })
                        else:
                            reply = await session.generate_skill_turn()
                            await websocket.send_json({
                                "type": "follow_up",
                                "data": {
                                    "question": reply or "（技能环节生成失败，已退出）",
                                    "reason": skill_name,
                                    "skill": skill_name,
                                    "step": progress.get("step", 1),
                                    "total": progress.get("total", 1),
                                },
                            })
                        continue

                    # v2.6: 安全通过 → 流式双 Agent 诊断，逐块推送
                    diag = None
                    async for stream_msg in session.stream_answer(
                        answer_text,
                        from_voice=from_voice,
                        thinking_seconds=thinking_seconds,
                    ):
                        if stream_msg.get("type") == "diagnosis_done":
                            diag = stream_msg.get("data")
                            continue
                        await websocket.send_json(stream_msg)

                    if not diag:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "诊断失败，请重新作答"}
                        })
                        continue

                    # v2.1: 输出泄露检测（check_output 返回 (is_safe, leaked)）
                    out_safe, leaked = check_output(json.dumps(diag, ensure_ascii=False))
                    if not out_safe:
                        logger.warning(f"输出检测到泄露: {leaked}")

                    await websocket.send_json({
                        "type": "diagnosis_result",
                        "data": diag
                    })

                    # v6.5: 难度变档事件（一次性信号，推送后清空）。
                    # 必须让候选人/前端看见难度在动，否则分数变化无法归因。
                    if session.pending_difficulty:
                        await websocket.send_json({
                            "type": "difficulty_change",
                            "data": session.pending_difficulty,
                        })
                        session.pending_difficulty = None

                    # v2.6: 每题诊断后推送实时雷达数据
                    await websocket.send_json({
                        "type": "radar_update",
                        "data": session.radar_snapshot()
                    })

                    # v5.0: 每题诊断后推送薄弱点累计面板
                    await websocket.send_json({
                        "type": "weakness_update",
                        "data": session.weakness_payload()
                    })

                    # v2.6: 追问已由诊断一次性产出，无需二次 LLM 调用
                    if session.should_follow_up(answer_text, diag):
                        follow_up_q = await session.generate_follow_up(diag)
                        await _mark_flow(session_id, session, FlowState.GENERATING_FOLLOW_UP)
                        await websocket.send_json({
                            "type": "follow_up",
                            "data": {
                                "question": follow_up_q,
                                "reason": diag.get("weakest_dimension_name", ""),
                            }
                        })
                        # 等待补充回答，允许用户主动跳过
                        while True:
                            fu_msg = await websocket.receive_json()
                            fu_type = fu_msg.get("type", "")

                            if fu_type == "ping":
                                await websocket.send_json({"type": "pong", "data": {}})
                                continue

                            if fu_type == "skip_follow_up":
                                # v7.0.2: 跳过追问留痕 —— 显式标记进本题诊断，
                                # 报告如实披露（真实面试中回避追问本身是负面信号）
                                session.mark_follow_up_skipped(follow_up_q)
                                await websocket.send_json({
                                    "type": "follow_up_received",
                                    "data": {"message": "已跳过追问"}
                                })
                                break

                            if fu_type != "answer":
                                continue

                            fu_text = fu_msg.get("data", {}).get("text", "")
                            fu_passed, fu_reason = full_check(fu_text, _answer_texts(session))
                            if not fu_passed:
                                await websocket.send_json({
                                    "type": "security_block",
                                    "data": {"reason": f"追问回答被拦截：{fu_reason}"}
                                })
                                continue

                            session.handle_follow_up_answer(
                                fu_text,
                                (fu_msg.get("data", {}) or {}).get("thinking_seconds", 0) or 0,
                            )
                            await _mark_flow(session_id, session, FlowState.DECIDING_NEXT)
                            await websocket.send_json({
                                "type": "follow_up_received",
                                "data": {"message": "补充回答已记录"}
                            })
                            break

                    answer_received = True

                # 本轮题目问完 → 质量驱动推进检查
                quality = session.check_round_quality()
                await websocket.send_json({
                    "type": "round_quality_check",
                    "data": quality
                })

                if quality["passed"] or not quality["can_add_extra"]:
                    break

                # v2.6: 未达标 → 针对薄弱维度追加定向题
                extra_q = await session.generate_extra_question()
                if not extra_q:
                    break

                await websocket.send_json({
                    "type": "extra_question",
                    "data": {
                        "round": session.current_round,
                        "question": extra_q.get("question", ""),
                        "intent": extra_q.get("intent", ""),
                        "focus_dimension": extra_q.get("focus_dimension", ""),
                        "focus_dimension_name": extra_q.get("focus_dimension_name", ""),
                        "reason": extra_q.get("reason", "本轮质量未达标，追加一道针对性问题"),
                    }
                })

            # v6.2: 收尾阶段 —— 由工程层发收束语，确保最后一轮答完即收束不拖沓
            if session.is_closing_round() and not user_ended:
                await websocket.send_json({
                    "type": "interview_closing",
                    "data": {
                        "round_name": info["name"],
                        "message": config.CLOSING_MESSAGE,
                    }
                })

            # 轮次总结
            await websocket.send_json({
                "type": "round_summary",
                "data": {
                    "round_name": info["name"],
                    "avg_score": session._current_round_avg_score(),
                    "quality": session.check_round_quality(),
                    "extra_questions_added": session.extra_questions_added,
                }
            })

            # 推进到下一轮
            session.advance_round()
            await _mark_flow(session_id, session, FlowState.ADVANCING_ROUND)

        # 3. 生成报告
        await _mark_flow(session_id, session, FlowState.FINISHED)
        report = session.build_report()
        await save_report(session_id, report)
        await update_session_status(session_id, "completed")

        # v2.7: 保存薄弱点画像
        try:
            # v8.4: 从会话获取 position_id，实现按岗位隔离薄弱点数据
            session_row = await get_session(session_id)
            sid_position_id = (session_row or {}).get("position_id") if session_row else None

            # v3.3: 对齐 build_report 实际 schema（dimension_averages + scoring.weights）。
            # 旧代码读取的 dimension_details / detailed_qa 字段在报告中不存在，
            # 导致薄弱点画像恒为空。
            weights_map = (report.get("scoring") or {}).get("weights") or {}
            for dim_key, avg in (report.get("dimension_averages") or {}).items():
                rps = []
                for diag in session.all_diagnoses:
                    if diag.get("weakest_dimension") == dim_key:
                        rps.extend(diag.get("risk_points", []) or [])
                await save_weakness_profile(session_id, dim_key, avg,
                                            weights_map.get(dim_key, 0.2), rps,
                                            position_id=sid_position_id)

            # v6.5: 长期薄弱点记忆（EMA 衰减 + 30 天过期 + 中性区不动）。
            # 与上面的快照写入是两件事：快照是历史流水，这里演进的是"当前状态"。
            for dim_key, avg in (report.get("dimension_averages") or {}).items():
                await weakness_memory.record_observation(
                    dim_key, avg, weights_map.get(dim_key, 0.2),
                    position_id=sid_position_id
                )
        except Exception as e:
            logger.error(f"保存薄弱点画像失败: {e}")

        await websocket.send_json({
            "type": "interview_done",
            "data": report,
        })

    except WebSocketDisconnect:
        logger.info(f"会话 {session_id} WebSocket 断开")

        # 尝试保存部分结果
        if session.all_diagnoses:
            try:
                partial_report = session.build_report()
                await save_report(session_id, partial_report)
                await update_session_status(session_id, "interrupted")
            except Exception as e:
                logger.error(f"保存中断报告失败: {e}")

    except Exception as e:
        logger.exception(f"面试会话 {session_id} 异常")
        try:
            await websocket.send_json({"type": "error", "data": {"message": str(e)}})
        except Exception:
            pass

    finally:
        # v3.1 整改：WS 结束（正常完成/断开/异常）一律清理会话引用，避免 active_sessions 内存泄漏
        async with state.session_lock:
            state.active_sessions.pop(session_id, None)
