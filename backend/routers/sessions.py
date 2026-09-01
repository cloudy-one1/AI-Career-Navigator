"""面试会话域：创建会话（含简历/JD 解析与丰富）、临时上传、会话查询、模式切换、公司风格列表。"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from ..config import config
from ..db import (
    save_session, get_session, get_session_qas, get_report,
    list_sessions, get_resume, get_position,
)
from ..interview_engine import InterviewSession
from ..resume_parser import (
    MIN_RESUME_CHARS,
    extract_interview_points,
    parse_resume,
)
from ..schemas import (
    SessionCreateRequest, SessionCreateResponse,
    ModeSwitchRequest, ModeSwitchResponse,
)
from ..web_research import enrich_jd_with_research
from .. import gap_analyzer
from .. import company_profiles
from ..market import service as market_service
from . import state
from .deps import ALLOWED_UPLOAD_EXT

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/sessions", response_model=SessionCreateResponse)
@state.limiter.limit(config.RATE_LIMIT_SESSION)
async def create_session(req: SessionCreateRequest, request: Request = None):
    session_id = uuid.uuid4().hex[:12]

    # v7.0: 简历/岗位优先从库中取（传入 id 时），未传 id 则沿用"直接传文本"的旧行为。
    # v8.3: 库内资源不存在 → 404（此前还要比对 owner，认证下线后只剩存在性判断）。
    if req.resume_id:
        row = await get_resume(req.resume_id)
        if not row:
            raise HTTPException(404, "简历不存在")
        req.resume_text = row.get("raw_text") or ""
    if req.position_id:
        row = await get_position(req.position_id)
        if not row:
            raise HTTPException(404, "岗位不存在")
        req.jd_text = row.get("jd_text") or ""

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
                llm_client=state.llm_client, jd_text=jd_final,
            )
            enriched = research_data.get("enriched_jd", "")
            if enriched and len(enriched) > len(jd_final):
                jd_final = enriched
                logger.info(f"岗位画像丰富: {len(jd_final)} 字符")
        except Exception as e:
            logger.warning(f"岗位画像丰富跳过: {e}")

    # v3.0: 本地市场库命中时，把定量快照（薪资/技能分布）并入岗位画像
    try:
        snapshot = await market_service.find_relevant_snapshot(jd_final)
        if snapshot and snapshot.get("total"):
            research_data["market_snapshot"] = snapshot
            logger.info(f"市场快照命中: {snapshot.get('keyword')} ({snapshot.get('total')} 条)")
    except Exception as e:
        logger.warning(f"市场快照获取跳过: {e}")

    # v6.2: 简历前置追问点（deepDivePoints/vaguePoints）—— 解析阶段一次性产出，
    # 后续各轮出题复用，让追问有数据支撑。失败降级为空，不阻断会话创建。
    resume_points: dict = {}
    if resume_text and len(resume_text.strip()) >= MIN_RESUME_CHARS:
        try:
            resume_points = await asyncio.to_thread(
                extract_interview_points, resume_text, state.llm_client, jd_final
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"简历追问点提取跳过: {e}")

    # v6.3: JD 匹配缺口 —— 出题优先级链的第一环（JD gap > JD 强匹配 > 简历锚点）。
    # 不声明优先级时模型会顺着简历走（简历在上下文里更"显眼"、更好写出具体问题），
    # 而真实面试官手里拿的是 JD，最关心的是"JD 上要求的你到底行不行"。
    # use_market=False：市场快照在上面已单独取过，这里不再重复查库（省一次 DB 往返）。
    jd_gaps: list[str] = []
    if jd_final and len(jd_final.strip()) > 20 and resume_text:
        try:
            gap_result = await gap_analyzer.analyze_gap(
                resume_text=resume_text,
                jd_text=jd_final,
                use_market=False,
                llm_client=state.llm_client,
            )
            for d in (gap_result.get("dimensions") or []):
                try:
                    score = float(d.get("score") or 0)
                except (TypeError, ValueError):
                    continue
                if 0 < score < config.JD_GAP_SCORE_THRESHOLD:
                    name = str(d.get("name") or "").strip()
                    if not name:
                        continue
                    gap_desc = str(d.get("gap") or "").strip()
                    jd_gaps.append(f"{name}：{gap_desc}" if gap_desc else name)
            jd_gaps = jd_gaps[:config.JD_GAP_MAX_ITEMS]
            if jd_gaps:
                logger.info(f"JD 匹配缺口提取 {len(jd_gaps)} 条，将作为出题优先级第一环")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"JD 缺口分析跳过（出题降级为无缺口模式）: {e}")
            jd_gaps = []

    await save_session(session_id, style=req.style or "friendly",
                       resume_filename="inline", jd_text=jd_final,
                       resume_text=resume_text,
                       resume_id=req.resume_id,       # v7.0 关联简历库（可空）
                       position_id=req.position_id)   # v7.0 关联岗位库（可空）

    # v6.5: 公司风格层 —— 显式选择 > JD 关键词自动匹配 > 不启用。
    # "none" 为前端明确不启用的哨兵值（与空串的"自动匹配"区分）；
    # 未知名称降级为自动匹配而非报错（公司风格是增强项，不是硬依赖）。
    company_profile = None
    company_display = None
    try:
        requested = (req.company_profile or "").strip()
        if requested.lower() == "none":
            logger.info("公司风格层：前端明确不启用")
        else:
            if requested:
                company_profile = company_profiles.get_profile(requested)
                if company_profile is None:
                    logger.warning(f"未知公司风格 {requested!r}，降级为 JD 自动匹配")
            if company_profile is None:
                company_profile = company_profiles.match_profile(jd_final)
            if company_profile:
                company_display = company_profile.get("display_name")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"公司风格解析失败，降级为不启用: {e}")
        company_profile = None
        company_display = None

    # 创建面试会话 (v2.4: 传递 mode; v5.0: 传递 stage; v6.2: 传递简历追问点)
    session = InterviewSession(
        session_id=session_id,
        resume_text=resume_text,
        jd_text=jd_final,
        llm_client=state.llm_client,
        diagnosis_engine=state.diagnosis_engine,
        interview_style=req.style or "friendly",
        mode=req.mode.value if req.mode else "simulation",
        stage=req.stage.value if req.stage else "phone_screen",
        include_self_intro=req.include_self_intro or False,
        question_type_mix=req.question_type_mix or {},
        resume_points=resume_points,
        jd_gaps=jd_gaps,   # v6.3: JD 匹配缺口（出题优先级链第一环）
        company_profile=company_profile,   # v6.5: 目标公司风格（None = 不启用）
    )
    async with state.session_lock:
        state.active_sessions[session_id] = session

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
        company_profile=company_display,
    )


@router.get("/api/company-profiles")
async def list_company_profiles():
    """返回全部已加载的公司风格配置摘要。目录为空 / pyyaml 缺失时返回空列表。"""
    return company_profiles.list_profiles()


@router.post("/api/sessions/upload")
@state.limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_resume(request: Request, file: UploadFile = File(...)):
    # 额外：文件大小硬限制（前端也应校验，但后端做最后一道防线）
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB")

    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {ALLOWED_UPLOAD_EXT}")

    text = parse_resume(content, filename=file.filename)
    return {"filename": file.filename, "text": text[:5000], "length": len(text)}


@router.post("/api/upload-jd")
@state.limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_jd(request: Request, file: UploadFile = File(...)):
    """v7.0.2: JD 文件上传解析（测评问题 #2）。

    复用简历解析链路（resume_parser 支持 PDF/TXT/DOCX），与 /api/sessions/upload
    同款防护（限流 / 大小硬限制 / 扩展名白名单）。解析结果只回填前端 JD 文本框，
    不入岗位库 —— 与"临时上传即开练"的简历上传同一语义。
    """
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {ALLOWED_UPLOAD_EXT}")

    text = parse_resume(content, filename=file.filename)
    if not text or not text.strip():
        raise HTTPException(400, "未能从文件中提取到文本，请确认文件内容")
    return {"filename": file.filename, "text": text[:20000], "length": len(text)}


@router.get("/api/sessions")
async def api_list_sessions():
    """v8.3: 单用户本地工具，返回全部会话（认证下线后不再有归属维度）。"""
    sessions = await list_sessions()
    return {"sessions": sessions}


@router.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    qas = await get_session_qas(session_id)
    # v4.0: 附带报告，供历史详情抽屉展示综合评分/轮次汇总
    report = await get_report(session_id)
    return {"session": session, "qa_count": len(qas), "qas": qas, "report": report}


@router.post("/api/interview/{session_id}/mode", response_model=ModeSwitchResponse)
@state.limiter.limit(config.RATE_LIMIT_SESSION)
async def switch_interview_mode(session_id: str, req: ModeSwitchRequest,
                                 request: Request = None):
    async with state.session_lock:
        session = state.active_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在或已结束")

    event = session.switch_mode(req.mode.value, req.stage.value if req.stage else None)
    # 若当前有未使用的追问，模式切换后清空，避免旧模式产物串场
    session.pending_follow_up = ""
    return ModeSwitchResponse(
        session_id=session_id,
        mode=session.mode,
        stage=session.stage,
        message=event["message"],
    )
