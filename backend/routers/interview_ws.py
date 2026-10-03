"""WebSocket 面试主循环（原 main.py 单体的最大职责块，v7.2.2 拆出）。

协议不变：{type, data} 消息嵌套；
会话不存在（4000/session_not_found）；同会话重复握手（4000/session_already_active，
v8.18 单会话单连接守卫）；正常完成 1000 关闭。

v8.3: 握手阶段不再校验身份（4001 unauthorized 随认证一起下线）。
"""
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import config
from ..db import (
    save_report, update_session_status, save_weakness_profile, update_session_flow,
    get_session, update_session_snapshot,
)
from ..interview_engine.flow import FlowState, NextAction
from ..interview_engine.session import InterviewSession, SnapshotError, is_end_signal
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

    v8.21: "不做断点续答"的限制已被会话快照补齐——快照在关键节点落库，
    进程重启后可从 DB 快照重建会话继续面试（见 _try_revive_session）。
    """
    try:
        session.set_flow_state(state_)
        await update_session_flow(session_id, state_.value, session.answered_count)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[flow] 流程状态落库失败 session={session_id} state={state_}: {e}")


async def _save_snapshot(session_id: str, session) -> None:
    """v8.21: 关键节点落会话快照（出题后 / 诊断完成后 / 轮次推进后 / 模式切换后）。

    与 _mark_flow 同一纪律：锦上添花不阻断，失败只记 debug 日志；刻意**不在**
    流式 chunk 上调用（每 chunk 一写是数 KB 级 JSON 的无谓放大）。快照是
    进行时持久化，不是报告替代品——终态仍走 build_report/save_report。
    """
    try:
        await update_session_snapshot(session_id, session.to_snapshot())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[snapshot] 快照落库失败 session={session_id}: {e}")


async def _try_revive_session(session_id: str) -> InterviewSession | None:
    """v8.21: 快照复活——进程重启后 active_sessions 无此条目，但 DB 快照仍在
    且会话状态为 active 时，从快照重建会话对象继续面试（任务书"重建继续"语义）。

    任何一步不满足（无快照 / 状态非 active / JSON 损坏 / 快照残缺）都降级为
    None，调用方按"会话不存在"处理——宁可放弃复活，也不带残缺状态继续面试。
    """
    try:
        row = await get_session(session_id, include_snapshot=True)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[snapshot] 快照读取失败 session={session_id}: {e}")
        return None
    if not row or (row.get("status") or "active") != "active":
        return None
    raw = row.get("snapshot_json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"[snapshot] 快照 JSON 解析失败 session={session_id}: {e}")
        return None
    try:
        session = InterviewSession.from_snapshot(
            data, llm_client=state.llm_client, diagnosis_engine=state.diagnosis_engine)
    except SnapshotError as e:
        logger.warning(f"[snapshot] 快照残缺，放弃复活 session={session_id}: {e}")
        return None
    except Exception as e:  # noqa: BLE001 - 快照形态的意外损坏同样降级，不让握手 500
        logger.warning(f"[snapshot] 快照无法重建，放弃复活 session={session_id}: "
                       f"{type(e).__name__}: {e}")
        return None
    logger.info("[snapshot] 会话 %s 已从快照复活（round=%s answered=%s）",
                session_id[:8], session.current_round, session.answered_count)
    return session


async def _handle_control_message(websocket, session, msg) -> bool:
    """
    v8.6: 处理与"推进主流程"无关的控制类消息（ping / request_rewrite）。

    返回 True = 消息已消费，调用方应继续等下一条。

    为什么单独抽出来：答题等待循环与追问等待循环都必须在等待期间响应这些消息。
    两处各写一遍迟早漏掉一种——漏掉 request_rewrite 的表现是"用户点了没反应"，
    而且只在特定时机（恰好在追问等待中）复现，极难定位。
    """
    msg_type = msg.get("type", "")

    if msg_type == "ping":
        await websocket.send_json({"type": "pong", "data": {}})
        return True

    if msg_type == "request_rewrite":
        # v8.6: 按需改写 —— 诊断已给出评分，改写等用户需要时再生成，
        # 避免每题都白等一次完整 LLM 往返（详见 config.AUTO_REWRITE）。
        data = msg.get("data", {}) or {}
        try:
            round_idx = int(data.get("round", -1))
            question_idx = int(data.get("question_idx", -1))
        except (TypeError, ValueError):
            round_idx = question_idx = -1
        try:
            async for rw_msg in session.stream_rewrite(round_idx, question_idx):
                await websocket.send_json(rw_msg)
        except Exception as e:  # noqa: BLE001
            # 改写是锦上添花：失败只记日志。诊断与评分此刻已经完整给出，
            # 改写生成不出来不应该让整场面试卡住。
            logger.warning(f"[rewrite] 按需改写生成失败: {e}")
        return True

    return False


async def _safe_send(websocket, payload: dict) -> None:
    """发送失败只吞掉（连接已断时由下一次 receive 的 WebSocketDisconnect 兜住）。"""
    try:
        await websocket.send_json(payload)
    except Exception:  # noqa: BLE001
        pass


async def _recv_msg(websocket) -> dict:
    """接收并校验一帧客户端消息——畸形帧不杀死面试（v8.18）。

    此前 receive_json 的三种失败（非法 JSON、非 dict 帧、data 非 dict）都会
    带着异常一路炸穿最外层 except，把整场面试打成 error 终态。现在逐帧校验：
    畸形帧回一条错误帧后继续收，直到拿到合法 dict；WebSocketDisconnect 不在
    捕获范围（它继承 Exception 但不是下面任何一种），断连照常向外传播。
    """
    while True:
        try:
            raw = await websocket.receive_json()
        except json.JSONDecodeError:
            await _safe_send(websocket, {"type": "error",
                                         "data": {"message": "消息格式错误（非法 JSON），已忽略"}})
            continue
        except (KeyError, RuntimeError, TypeError, ValueError) as e:
            # KeyError：二进制帧进 receive_text；其余为极端传输层噪声
            await _safe_send(websocket, {"type": "error",
                                         "data": {"message": f"消息格式错误，已忽略（{type(e).__name__}）"}})
            continue
        if not isinstance(raw, dict):
            await _safe_send(websocket, {"type": "error",
                                         "data": {"message": "消息格式错误（需为 JSON 对象），已忽略"}})
            continue
        if not isinstance(raw.get("data", {}), dict):
            raw["data"] = {}   # data 恒为 dict，下游 .get 不再可能炸
        return raw


async def _save_partial_report(session_id: str, session, status: str) -> bool:
    """断连/异常路径尽量保住已答题目——只要有诊断记录就落一份部分报告。

    返回是否真正落库。此前只有 WebSocketDisconnect 分支落部分报告，服务端
    发送诊断/出题期间断连（比 receive 期间断连更常见）落入通用 except 只落
    status=error，几十分钟答题数据随 unregister 全部蒸发。
    """
    if not getattr(session, "all_diagnoses", None):
        return False
    try:
        partial_report = session.build_report()
        await save_report(session_id, partial_report)
        await update_session_status(session_id, status)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"保存部分报告失败 session={session_id}: {e}")
        return False


@router.websocket("/ws/interview/{session_id}")
async def ws_interview(websocket: WebSocket, session_id: str):
    """面试主循环握手。

    会话存在性在 accept() 之后以 4000/session_not_found 关闭（原本还要在
    accept() 之前做 4001 身份校验，v8.3 随认证下线一并移除）。
    """
    await websocket.accept()
    # v8.18: 原子完成「查会话 + 单连接认领」。没有这道守卫时，同一会话的第二次
    # 握手会拿到同一 session 对象，两个主循环并发出题/推进/互踩状态。
    session, err = await state.acquire_ws_session(session_id)
    # v8.21: 快照复活——内存无此条目（进程重启）但 DB 快照仍在且会话 active 时，
    # 从快照重建会话对象继续面试；复活后重新走认领（单连接守卫 / TTL 豁免语义
    # 全部不变，只是在 acquire 之前多了一步"复活"）。
    if session is None and err == "session_not_found":
        revived = await _try_revive_session(session_id)
        if revived is not None:
            await state.register_session(session_id, revived)
            session, err = await state.acquire_ws_session(session_id)
    if session is None:
        if err == "session_already_active":
            await websocket.send_json({
                "type": "error",
                "data": {"message": "该会话已在另一连接中进行，请勿重复打开"},
            })
            await websocket.close(code=4000, reason="session_already_active")
        else:
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
                # v8.21: ASKING 落位——出题是一次 LLM 往返（数秒级），流程位置
                # 如实反映"正在出题"，而不是停在上一状态装死。
                await _mark_flow(session_id, session, FlowState.ASKING)
                await session.generate_questions()

            if not session.round_questions:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"{info['name']}题目生成失败，跳过本轮"}
                })
                session.advance_round()
                continue

            # v8.21: 关键节点落快照——出题后（含复活后重入本轮的场景）
            await _save_snapshot(session_id, session)

            # v8.6: 服务端墙钟起点（每次出题时设置），用于校验前端上报的思考时长
            question_sent_at = None

            # 题目循环
            while session.has_more_questions_in_round() and not user_ended:
                q = session.current_question
                if not isinstance(q, dict):
                    break
                # v7.0: 出题即标记"等待回答"并落库 —— 让进程重启后仍能看出
                # 这场面试停在哪一题（注意：只落进度，不做断点续答）。
                await _mark_flow(session_id, session, FlowState.WAITING_ANSWER)
                # v8.6: 服务端墙钟起点，用于交叉校验前端上报的思考时长
                question_sent_at = time.time()
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
                    msg = await _recv_msg(websocket)
                    msg_type = msg.get("type", "")
                    data = msg.get("data", {})

                    # v8.6: ping / request_rewrite 走统一入口（两个等待循环共用）
                    if await _handle_control_message(websocket, session, msg):
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
                        # v8.21: 关键节点落快照——模式切换后（推进时按新模式
                        # 重建轮次结构的 mode_changed 标记必须活过进程重启）
                        await _save_snapshot(session_id, session)
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
                    stream_notified = False
                    # v8.21: DIAGNOSING 落位——诊断是流式长任务，此前九态中
                    # 此状态从不落位，"正在诊断"只能靠猜。
                    await _mark_flow(session_id, session, FlowState.DIAGNOSING)
                    async for stream_msg in session.stream_answer(
                        answer_text,
                        from_voice=from_voice,
                        thinking_seconds=thinking_seconds,
                    ):
                        if stream_msg.get("type") == "diagnosis_done":
                            diag = stream_msg.get("data")
                            continue
                        if stream_msg.get("type") == "diagnosis_error":
                            # v8.20: 链路失败显式上报——本题未计分、指针未推进，
                            # 前端可对同一题重答（此前伪装成全 0 分诊断照常入库）
                            stream_notified = True
                            await websocket.send_json({"type": "error",
                                                       "data": stream_msg.get("data")})
                            continue
                        await websocket.send_json(stream_msg)

                    if not diag:
                        if not stream_notified:
                            await websocket.send_json({
                                "type": "error",
                                "data": {"message": "诊断失败，请重新作答"}
                            })
                        continue

                    # v8.6: 用服务端墙钟差校验前端上报的思考时长（失真时以服务端值为准）
                    if question_sent_at is not None:
                        session.annotate_server_thinking(time.time() - question_sent_at)

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

                    # v8.21: 关键节点落快照——诊断完成后（本题答案 + 诊断已入会话状态）
                    await _save_snapshot(session_id, session)

                    # v8.21: 是否追问收敛到 decide_next 纯函数——"接下来该做什么"
                    # 的唯一出处（should_follow_up 老方法已删除，规则逐条并入纯
                    # 函数，取舍记录在本提交描述的规则 diff 清单）。OFFER_RECOVERY
                    # 与追问共用同一段副作用：恢复建议经 pending_follow_up 的
                    # 守卫话术（record_answer 内替换）由 generate_follow_up 送达。
                    decision = session.decide()
                    if decision.action in (NextAction.GENERATE_FOLLOW_UP,
                                           NextAction.OFFER_RECOVERY):
                        logger.info("[flow] %s 追问判定: %s", session_id[:8], decision.reason)
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
                            fu_msg = await _recv_msg(websocket)
                            fu_type = fu_msg.get("type", "")

                            if await _handle_control_message(websocket, session, fu_msg):
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

                            # v8.21: 结束口令前置检查——与主回答等待循环同一处理。
                            # 此前只修了主循环：追问等待期间说"结束面试"会先撞上
                            # v8.20 注入拦截词 ((结束|终止|退出)\s*面试) 被拦为
                            # 不安全内容，用户想收束面试却收到 security_block，
                            # 只能先跳过追问再说口令。口令必须排在安全检查之前。
                            if is_end_signal(fu_text):
                                user_ended = True
                                await websocket.send_json({
                                    "type": "interview_end_signal",
                                    "data": {"message": "收到结束信号，面试到此结束，正在生成面评报告……"}
                                })
                                break

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

                            # v8.6: 追问补评 —— 让补充回答真正影响分数。
                            # 此前追问补充"只并入语境、不重评"（session.py 里已披露的取舍），
                            # 候选人被追问后补出的优质内容不改变已评分，是真实的评分盲区。
                            # 放在 handle_follow_up_answer 之后：先落文本，再谈改分，
                            # 任何一步失败都还有一份完整的首评结果在。
                            if config.FOLLOW_UP_REASSESS:
                                try:
                                    async for ra_msg in session.stream_follow_up_reassessment():
                                        await websocket.send_json(ra_msg)
                                    # 分数改了 → 雷达与薄弱点面板必须跟着刷新，
                                    # 否则前端会出现"诊断卡 4.2 分、雷达还停在 3.1"的错位。
                                    if (session.all_diagnoses
                                            and session.all_diagnoses[-1].get("follow_up_reassessed")):
                                        await websocket.send_json({
                                            "type": "radar_update",
                                            "data": session.radar_snapshot(),
                                        })
                                        await websocket.send_json({
                                            "type": "weakness_update",
                                            "data": session.weakness_payload(),
                                        })
                                except Exception as e:  # noqa: BLE001
                                    # 补评是锦上添花：失败即静默降级为"不重评"，
                                    # 与 _mark_flow 同一风格——面试可用性优先于分数精度。
                                    logger.warning(
                                        f"[reassess] {session_id[:8]} 追问补评失败，保留首评分数: {e}")

                            await _mark_flow(session_id, session, FlowState.DECIDING_NEXT)
                            await websocket.send_json({
                                "type": "follow_up_received",
                                "data": {"message": "补充回答已记录"}
                            })
                            break
                        # v8.21: 关键节点落快照——追问交换完成（补充回答 / 跳过留痕
                        # 都已改变本题状态）
                        await _save_snapshot(session_id, session)

                    answer_received = True

                # 本轮题目问完 → 轮次结算
                # v8.21: 补题判定收敛到 decide_next 纯函数（D9/D10：not round_passed
                # 含"已答题"前提；below_min_questions 继续出题是纯函数独有的规则，
                # 老路径从未实现）。check_round_quality 降级为 round_quality_check
                # 帧的数据源（前端展示），不再驱动推进。追问类动作在此处不可能是
                # 决策结果——追问机会一次性门（follow_up_count>0 时 ③ 跳过）。
                # v8.19: 用户已宣布结束（退出口令）就不再做质量检查与追加题——
                # 此前 break 只跳出答题等待循环，随后仍会打一次 LLM 生成追加题，
                # 前端在 interview_end_signal 之后收到自相矛盾的出题事件
                if not user_ended:
                    quality = session.check_round_quality()
                    await websocket.send_json({
                        "type": "round_quality_check",
                        "data": quality
                    })

                    decision = session.decide()
                    if decision.action == NextAction.AWAIT_ANSWER:
                        # 本轮还有计划内的题 → 继续问下一题。结算块在每次回答后
                        # 都会执行（不只在本轮题目问完后），该动作在此时意味着
                        # "下一题"而非"收轮"——漏掉这个分支会把剩余计划题整轮
                        # 跳过（实测：每答一题就推进一轮）。
                        #
                        # 取舍记录（D15）：老路径在此处按质量插入补题、抢在计划
                        # 题之前（低分会把本轮计划题替换成补题）；v8.21 起以纯
                        # 函数为准——计划题问完才进结算，补题只在结算点追加。
                        continue
                    if decision.action != NextAction.GENERATE_EXTRA:
                        # v8.21: 推进 / 收尾同样出自本决策——ADVANCE_ROUND 进入
                        # 下一轮、FINISH 结束面试，推进副作用仍由循环尾部的
                        # advance_round 执行（advance 后 is_finished 的判定与
                        # 纯函数 is_last_round 同源）。决策理由首次可观测。
                        logger.info("[flow] %s 结算判定: %s", session_id[:8], decision.reason)
                        break
                    logger.info("[flow] %s 补题判定: %s", session_id[:8], decision.reason)
                    # v8.21: ASKING 落位——补题生成同样是一次 LLM 往返
                    await _mark_flow(session_id, session, FlowState.ASKING)

                    # v2.6: 未达标 → 针对薄弱维度追加定向题
                    extra_q = await session.generate_extra_question()
                    if not extra_q:
                        break

                    # v8.6: 追加题同样是"一道题"，墙钟起点随之重置
                    question_sent_at = time.time()
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
                    # v8.21: 关键节点落快照——补题已入本轮题单
                    await _save_snapshot(session_id, session)
                    # 追加题回到答题等待循环（answer_received 仍为 False）

                if user_ended:
                    break

            # v6.2: 收尾阶段 —— 由工程层发收束语，确保最后一轮答完即收束不拖沓
            if session.is_closing_round() and not user_ended:
                # v8.21: CLOSING 落位——收尾强控阶段在流程位置上显式可见
                await _mark_flow(session_id, session, FlowState.CLOSING)
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
            # v8.21: 关键节点落快照——轮次推进后（新轮次从零开始的状态）
            await _save_snapshot(session_id, session)

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
        await _save_partial_report(session_id, session, "interrupted")

    except Exception as e:
        logger.exception(f"面试会话 {session_id} 异常")
        # v8.18: 非断连异常同样尝试保住已答题目（此前只落 status=error，
        # 发送诊断/出题期间的异常会带着整场答题数据一起蒸发）
        saved = await _save_partial_report(session_id, session, "error")
        if not saved:
            try:
                await update_session_status(session_id, "error")
            except Exception as log_err:  # noqa: BLE001 - 终态落库失败不能掩盖原始异常
                logger.warning("会话 %s 异常终态落库失败: %s", session_id, log_err)
        # v8.18: 不再把 str(e) 原样回传客户端（内部路径/库错误细节泄漏），
        # 细节已在上面 logger.exception 留痕
        await _safe_send(websocket, {
            "type": "error",
            "data": {"message": "面试进程发生内部错误，本场已结束；已答题目已尽力保存，可在历史记录查看"},
        })

    finally:
        # v3.1 整改：WS 结束（正常完成/断开/异常）一律清理会话引用，避免 active_sessions 内存泄漏
        # v8.12: 连同创建时刻一并对称注销（TTL 记录不留悬挂条目）
        # v8.18: 连同单连接认领一并对称释放
        await state.release_ws_session(session_id)
        await state.unregister_session(session_id)
