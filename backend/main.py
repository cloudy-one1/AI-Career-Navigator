"""
FastAPI 入口 v2.5：HTTP + WebSocket 路由。
双模式面试 + 面试官自动切换 + 题库管理 + 岗位画像研究 + 诊断反馈。
"""

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import config
from .db import init_db, save_session, update_session_status, get_session, list_sessions, save_report, get_report, get_session_qas
from .db import save_feedback as db_save_feedback, get_feedback_stats
from .llm_client import LLMClient
from .diagnosis_engine import DiagnosisEngine
from .interview_engine import InterviewSession  # v2.5: 子包引用
from .resume_parser import parse_resume
from .schemas import (
    SessionCreateRequest, SessionCreateResponse,
    ProviderSwitchRequest, ProviderListResponse, ProviderInfo,
    ReportData, DiagnosisFeedbackRequest, FeedbackStatsResponse,
)
from .security import full_check, check_output
from .web_research import enrich_jd_with_research
from . import question_bank as qbank

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

app = FastAPI(title="AI 面试官 v2.5", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 全局服务状态 =====
llm_client = LLMClient(provider=config.AI_PROVIDER)
diagnosis_engine = DiagnosisEngine(llm_client=llm_client)
active_sessions: dict[str, InterviewSession] = {}


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info(f"AI 面试官 v2.4 启动完成，当前后端: {config.AI_PROVIDER}")


# ===== 健康检查 =====

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.4", "provider": config.AI_PROVIDER}


# ===== AI 后端管理 (v2.1) =====

@app.get("/api/providers", response_model=ProviderListResponse)
async def list_providers():
    providers = []
    for k, v in config.AI_PROVIDERS.items():
        providers.append(ProviderInfo(
            id=k,
            name=v["name"],
            models=v.get("models", []),
            is_current=(k == config.AI_PROVIDER),
        ))
    current = ProviderInfo(
        id=config.AI_PROVIDER,
        name=config.AI_PROVIDERS[config.AI_PROVIDER]["name"],
        models=config.AI_PROVIDERS[config.AI_PROVIDER].get("models", []),
        is_current=True,
    )
    return ProviderListResponse(providers=providers, current=current)


@app.post("/api/switch-provider")
async def switch_provider(req: ProviderSwitchRequest):
    if req.provider not in config.AI_PROVIDERS:
        raise HTTPException(status_code=400,
                            detail=f"不支持的后端: {req.provider}。可用: {list(config.AI_PROVIDERS.keys())}")

    provider_info = config.AI_PROVIDERS[req.provider]
    api_key_env = provider_info.get("api_key_env", "")
    api_key = os.getenv(api_key_env) or os.getenv("LLM_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400,
                            detail=f"{provider_info['name']} 未配置 API KEY，请设置 {api_key_env} 环境变量")

    global llm_client, diagnosis_engine
    config.AI_PROVIDER = req.provider
    llm_client = LLMClient(provider=req.provider)
    diagnosis_engine = DiagnosisEngine(llm_client=llm_client)
    logger.info(f"切换到后端: {req.provider}")
    return {"message": f"已切换到 {provider_info['name']}", "provider": req.provider}


# ===== 会话管理 =====

@app.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    session_id = uuid.uuid4().hex[:12]

    # 解析简历
    resume_text = ""
    if req.resume_text:
        resume_text = parse_resume(req.resume_text, filename="inline.txt")

    # v2.5: 岗位画像自动丰富
    jd_final = req.jd_text or ""
    research_data = {}
    if jd_final and len(jd_final.strip()) > 20:
        try:
            research_data = await enrich_jd_with_research(
                llm_client=llm_client, jd_text=jd_final,
            )
            enriched = research_data.get("enriched_jd", "")
            if enriched and len(enriched) > len(jd_final):
                jd_final = enriched
                logger.info(f"岗位画像丰富: {len(jd_final)} 字符")
        except Exception as e:
            logger.warning(f"岗位画像丰富跳过: {e}")

    await save_session(session_id, style=req.style or "friendly",
                       resume_filename="inline", jd_text=jd_final)

    # 创建面试会话 (v2.4: 传递 mode)
    session = InterviewSession(
        session_id=session_id,
        resume_text=resume_text,
        jd_text=jd_final,
        llm_client=llm_client,
        diagnosis_engine=diagnosis_engine,
        interview_style=req.style or "friendly",
        mode=req.mode or "simulation",
    )
    active_sessions[session_id] = session

    # 根据模式返回不同的轮次列表
    rounds_source = (config.TRADITIONAL_ROUNDS if session.mode == "traditional"
                     else config.INTERVIEW_ROUNDS)

    return SessionCreateResponse(
        session_id=session_id,
        message="会话已创建",
        mode=session.mode,
        rounds=[{"index": r["round_index"], "name": r["name"],
                 "question_count": r["question_count"]}
                for r in rounds_source],
        research=research_data if research_data else None,
    )


@app.post("/api/sessions/upload")
async def upload_resume(file: UploadFile = File(...)):
    allowed_ext = (".pdf", ".docx", ".txt")
    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in allowed_ext:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {allowed_ext}")

    content = await file.read()
    text = parse_resume(content, filename=file.filename)
    return {"filename": file.filename, "text": text[:5000], "length": len(text)}


@app.get("/api/sessions")
async def api_list_sessions():
    sessions = await list_sessions()
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    qas = await get_session_qas(session_id)
    return {"session": session, "qa_count": len(qas)}


@app.get("/api/reports/{session_id}")
async def api_get_report(session_id: str):
    report = await get_report(session_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    return {"report": dict(report)}


# ===== v2.2 题库管理 API =====

@app.get("/api/question-bank")
async def list_question_bank(
    round_type: Optional[str] = Query(None),
    difficulty: Optional[int] = Query(None),
    favorited: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出题库题目"""
    try:
        result = await qbank.list_bank({
            "round_type": round_type,
            "difficulty": difficulty,
            "favorited": favorited,
            "search": search,
            "source": source,
            "limit": limit,
            "offset": offset,
        })
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


class CreateQuestionRequest(BaseModel):
    question_text: str
    round_type: str = ""
    intent: str = ""
    tags: list[str] = []
    difficulty: int = 3


@app.post("/api/question-bank")
async def create_question_bank(req: CreateQuestionRequest):
    """添加题目"""
    try:
        result = await qbank.create_question(req.model_dump())
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


class UpdateQuestionRequest(BaseModel):
    question_text: Optional[str] = None
    round_type: Optional[str] = None
    intent: Optional[str] = None
    tags: Optional[list[str]] = None
    difficulty: Optional[int] = None
    is_favorited: Optional[bool] = None


@app.put("/api/question-bank/{question_id}")
async def update_question_bank(question_id: int, req: UpdateQuestionRequest):
    """更新题目"""
    try:
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        return await qbank.update_question_item(question_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/question-bank/{question_id}")
async def delete_question_bank(question_id: int):
    """删除题目"""
    try:
        return await qbank.delete_question_item(question_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/question-bank/{question_id}/favorite")
async def favorite_question_bank(question_id: int):
    """切换收藏"""
    try:
        return await qbank.favorite_question(question_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


class ImportQuestionsRequest(BaseModel):
    session_id: str


@app.post("/api/question-bank/import")
async def import_questions_bank(req: ImportQuestionsRequest):
    """从会话导入题目"""
    try:
        return await qbank.import_from_session(req.session_id)
    except Exception as e:
        raise HTTPException(500, str(e))


# ===== v2.5: 诊断反馈 API =====

@app.post("/api/feedback")
async def submit_feedback(req: DiagnosisFeedbackRequest):
    """提交诊断反馈（👍/👎）"""
    try:
        feedback_id = await db_save_feedback(
            session_id=req.session_id,
            round_idx=req.round_idx,
            question_idx=req.question_idx,
            feedback_type=req.feedback_type,
            dimension=req.dimension,
            comment=req.comment,
            current_score=req.current_score,
        )
        return {"status": "ok", "feedback_id": feedback_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/feedback/{session_id}")
async def get_feedback(session_id: str):
    """获取会话的反馈统计"""
    try:
        stats = await get_feedback_stats(session_id)
        return stats
    except Exception as e:
        raise HTTPException(500, str(e))


# ===== v2.5: 岗位画像研究 API =====

@app.post("/api/research-position")
async def research_position(jd_text: str = Form(""), position: str = Form(""),
                             company: str = Form("")):
    """搜索并分析岗位信息"""
    try:
        result = await enrich_jd_with_research(
            llm_client=llm_client,
            jd_text=jd_text,
            position=position,
            company=company,
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error(f"岗位研究失败: {e}")
        raise HTTPException(500, str(e))


# ===== WebSocket 面试 =====

import os


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


@app.websocket("/ws/interview/{session_id}")
async def ws_interview(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = active_sessions.get(session_id)

    if not session:
        await websocket.send_json({"type": "error", "data": {"message": "会话不存在"}})
        await websocket.close()
        return

    try:
        # 1. 发送面试官信息（v2.4: 含模式信息）
        await websocket.send_json({
            "type": "interviewer_info",
            "data": {
                "style": session.style,
                "mode": session.mode,
                "total_rounds": len(session.rounds),
                "rounds_info": [{"index": r["round_index"], "name": r["name"]}
                                for r in session.rounds],
            }
        })

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
        while not session.is_finished:
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
            while session.has_more_questions_in_round():
                q = session.current_question
                if not isinstance(q, dict):
                    break
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

                    if msg_type != "answer":
                        continue

                    answer_text = data.get("text", "")

                    # v2.1: 4 层安全检查（full_check 返回 (pass_all, reason)）
                    passed, reason = full_check(answer_text, _answer_texts(session))
                    if not passed:
                        await websocket.send_json({
                            "type": "security_block",
                            "data": {"reason": reason}
                        })
                        continue

                    # v2.6: 安全通过 → 流式双 Agent 诊断，逐块推送
                    diag = None
                    async for stream_msg in session.stream_answer(answer_text):
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

                    # v2.6: 每题诊断后推送实时雷达数据
                    await websocket.send_json({
                        "type": "radar_update",
                        "data": session.radar_snapshot()
                    })

                    # v2.6: 追问已由诊断一次性产出，无需二次 LLM 调用
                    if session.should_follow_up(answer_text, diag):
                        follow_up_q = await session.generate_follow_up(diag)
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
                                session.pending_follow_up = ""
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

                            session.handle_follow_up_answer(fu_text)
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

        # 3. 生成报告
        report = session.build_report()
        await save_report(session_id, report)
        await update_session_status(session_id, "completed")

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


# ===== 静态文件 =====
try:
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
except RuntimeError:
    logger.info("静态文件挂载跳过（可能已存在）")
