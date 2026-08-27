"""
FastAPI 入口 v3.1：HTTP + WebSocket 路由。
双模式面试 + 面试官自动切换 + 题库管理 + 岗位画像研究 + 诊断反馈 + 市场数据层
+ Web 安全加固（slowapi 限流 / CORS 收紧 / 请求体大小限制 / 安全响应头）。
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from . import logger as app_logger
from .config import config
from .db import (
    init_db, save_session, update_session_status, get_session, list_sessions,
    save_report, get_report, get_session_qas,
    save_weakness_profile, get_weakness_profile, get_global_weakness_profile,
)
from .db import save_feedback as db_save_feedback, get_feedback_stats
from .llm_client import LLMClient, _api_key_issue
from .diagnosis_engine import DiagnosisEngine
from .interview_engine import InterviewSession  # v2.5: 子包引用
from .interview_engine.report import generate_review_markdown
from .resume_parser import parse_resume
from .schemas import (
    SessionCreateRequest, SessionCreateResponse,
    ProviderSwitchRequest, ProviderListResponse, ProviderInfo,
    ReportData, DiagnosisFeedbackRequest, FeedbackStatsResponse,
    GapAnalysisRequest, GapAnalysisResponse,
    CrossJobCompareRequest, CrossJobCompareResponse, JobCompareItem,
    CareerPlanRequest, CareerPlanResponse,  # v3.2 职业规划
)
from .security import full_check, check_output
from .web_research import enrich_jd_with_research
from . import question_bank as qbank
from .market import store as market_store, service as market_service  # v3.0
from . import gap_analyzer  # v3.1
from . import career_planner  # v3.2 职业规划

# ─── 集中日志 ───
app_logger.setup_logging()
logger = logging.getLogger("main")

# ─── 限流器 ───
limiter = Limiter(key_func=get_remote_address, default_limits=[config.RATE_LIMIT_GLOBAL])

# ─── 安全响应头中间件 ───
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


# ─── 请求体大小限制中间件 ───
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    _UPLOAD_PATHS = ("/api/sessions/upload", "/api/market/import")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        limit = config.MAX_UPLOAD_BYTES if any(path.startswith(p) for p in self._UPLOAD_PATHS) else config.MAX_REQUEST_BYTES
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > limit:
            return JSONResponse(
                status_code=413,
                content={"detail": f"请求体过大，上限 {limit // 1024 // 1024}MB" if limit >= 1024 * 1024 else f"请求体过大，上限 {limit // 1024}KB"},
            )
        return await call_next(request)


# ─── 解析 CORS origins ───
_cors_origins = [o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()]

# ─── FastAPI 应用 ───
app = FastAPI(title="AI 面试官 v3.1", version="3.1.0")

# CORS 中间件（最先注册）
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],  # 空列表 = 开发模式，允许所有
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全响应头（在 CORS 之后，影响所有响应）
app.add_middleware(SecurityHeadersMiddleware)

# 请求体大小限制（在路由匹配前生效）
app.add_middleware(RequestSizeLimitMiddleware)

# 注册 slowapi 限流异常处理器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429,
    content={"detail": f"请求过于频繁，请稍后再试。限制：{config.RATE_LIMIT_GLOBAL}"},
))

# ===== 全局服务状态 =====
llm_client = LLMClient(provider=config.AI_PROVIDER)
diagnosis_engine = DiagnosisEngine(llm_client=llm_client)
active_sessions: dict[str, InterviewSession] = {}
_session_lock = asyncio.Lock()
_provider_lock = asyncio.Lock()  # v3.1 整改：保护全局单例重赋值，消除 switch_provider 竞态


@app.on_event("startup")
async def startup():
    await init_db()
    await market_store.init_market_db()  # v3.0: 市场岗位库（幂等）
    logger.info(f"AI 面试官 v3.1 启动完成，当前后端: {config.AI_PROVIDER}")


# ===== 健康检查 =====

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.1", "provider": config.AI_PROVIDER}


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
    issue = _api_key_issue(api_key or "")
    if issue:
        raise HTTPException(status_code=400,
                            detail=f"{provider_info['name']} {issue}，请设置 {api_key_env} 环境变量")

    global llm_client, diagnosis_engine
    async with _provider_lock:
        config.AI_PROVIDER = req.provider
        llm_client = LLMClient(provider=req.provider)
        diagnosis_engine = DiagnosisEngine(llm_client=llm_client)
    logger.info(f"切换到后端: {req.provider}")
    return {"message": f"已切换到 {provider_info['name']}", "provider": req.provider}


# ===== 会话管理 =====

@app.post("/api/sessions", response_model=SessionCreateResponse)
@limiter.limit(config.RATE_LIMIT_SESSION)
async def create_session(req: SessionCreateRequest, request: Request = None):
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

    # v3.0: 本地市场库命中时，把定量快照（薪资/技能分布）并入岗位画像
    try:
        snapshot = await market_service.find_relevant_snapshot(jd_final)
        if snapshot and snapshot.get("total"):
            research_data["market_snapshot"] = snapshot
            logger.info(f"市场快照命中: {snapshot.get('keyword')} ({snapshot.get('total')} 条)")
    except Exception as e:
        logger.warning(f"市场快照获取跳过: {e}")

    await save_session(session_id, style=req.style or "friendly",
                       resume_filename="inline", jd_text=jd_final,
                       resume_text=resume_text)

    # 创建面试会话 (v2.4: 传递 mode)
    session = InterviewSession(
        session_id=session_id,
        resume_text=resume_text,
        jd_text=jd_final,
        llm_client=llm_client,
        diagnosis_engine=diagnosis_engine,
        interview_style=req.style or "friendly",
        mode=req.mode or "simulation",
        include_self_intro=req.include_self_intro or False,
        question_type_mix=req.question_type_mix or {},
    )
    async with _session_lock:
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
@limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_resume(request: Request, file: UploadFile = File(...)):
    # 额外：文件大小硬限制（前端也应校验，但后端做最后一道防线）
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB")

    allowed_ext = (".pdf", ".docx", ".txt")
    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in allowed_ext:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {allowed_ext}")

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
    # v4.0: 附带报告，供历史详情抽屉展示综合评分/轮次汇总
    report = await get_report(session_id)
    return {"session": session, "qa_count": len(qas), "qas": qas, "report": report}


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


# ===== v2.7: 薄弱点画像 API =====

@app.get("/api/weakness-profile")
async def global_weakness_profile():
    """获取全局薄弱点聚合（各维度历史平均分）"""
    try:
        profile = await get_global_weakness_profile()
        return {"status": "ok", "profile": profile}
    except Exception as e:
        logger.error(f"获取全局薄弱点失败: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/weakness-profile/{session_id}")
async def session_weakness_profile(session_id: str):
    """获取指定会话的薄弱点快照"""
    try:
        profile = await get_weakness_profile(session_id)
        return {"status": "ok", "session_id": session_id, "profile": profile}
    except Exception as e:
        logger.error(f"获取会话薄弱点失败: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/reports/{session_id}/review")
async def export_review(session_id: str):
    """导出复盘 Markdown 文件"""
    try:
        report = await get_report(session_id)
        if not report:
            raise HTTPException(404, "报告不存在")
        # v3.3: get_report 返回含 report_json 字符串的行，需解析后再交给导出函数
        # （此前直接传行对象，导出的复盘内容全为空）
        report = json.loads(report["report_json"]) if isinstance(report.get("report_json"), str) else report
        md = generate_review_markdown(report)
        return Response(content=md, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=review_{session_id}.md"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成复盘文件失败: {e}")
        raise HTTPException(500, str(e))


# ===== v2.5: 岗位画像研究 API =====

@app.post("/api/research-position")
@limiter.limit("10/minute")
async def research_position(jd_text: str = Form(""), position: str = Form(""),
                             company: str = Form(""), request: Request = None):
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


# ===== v3.0: 市场数据 API =====

@app.post("/api/market/import")
@limiter.limit("5/minute")
async def market_import(
    request: Request,
    db_path: str = Form(""),
    keyword: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    limit: int = Form(5000),
):
    """
    从 job-crawler data.db 导入岗位到 market.db。
    db_path 为空时使用 .env 中的 JOB_CRAWLER_DB_PATH 配置。
    同步执行，完成后返回导入摘要。
    """
    if not db_path.strip():
        # 未指定 → 仅允许使用 .env 中配置的可信源
        crawler_path = config.JOB_CRAWLER_DB_PATH
    else:
        # 指定路径 → 必须位于可信数据目录内且以 .db 结尾，防止任意文件存在性探测（路径遍历）
        allowed_base = os.path.normpath(os.path.dirname(os.path.abspath(config.MARKET_DB_PATH)))
        candidate = os.path.normpath(os.path.abspath(db_path.strip()))
        if candidate != allowed_base and not candidate.startswith(allowed_base + os.sep):
            raise HTTPException(400, "仅允许导入可信数据目录内的数据库文件")
        if not candidate.endswith(".db"):
            raise HTTPException(400, "仅支持导入 .db 文件")
        crawler_path = candidate

    if not crawler_path:
        raise HTTPException(400,
            "请提供 db_path 或在 .env 中配置 JOB_CRAWLER_DB_PATH")

    if not os.path.exists(crawler_path):
        raise HTTPException(400, f"job-crawler 数据库不存在: {crawler_path}")

    result = await market_service.import_and_store(
        crawler_db_path=crawler_path,
        keyword=keyword.strip() if keyword else None,
        city=city.strip() if city else None,
        limit=max(1, min(limit, 10000)),
    )
    return {"status": "ok", **result}


@app.get("/api/market/jobs")
async def market_jobs(
    keyword: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    education: Optional[str] = Query(None),
    salary_min: Optional[float] = Query(None, ge=0),
    salary_max: Optional[float] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """岗位列表查询（关键词/城市/学历/薪资区间过滤 + 分页）"""
    return await market_store.query_jobs(
        keyword=keyword, city=city, education=education,
        salary_min=salary_min, salary_max=salary_max,
        limit=limit, offset=offset,
    )


@app.get("/api/market/stats")
async def market_stats(keyword: Optional[str] = Query(None)):
    """市场统计概览：总量/城市/薪资/学历分布、平均薪资、热门技能"""
    return await market_store.get_stats(keyword=keyword)


# ===== v3.1: Gap 分析 API =====

@app.post("/api/gap-analysis", response_model=GapAnalysisResponse)
@limiter.limit(config.RATE_LIMIT_GAP)
async def gap_analysis(req: GapAnalysisRequest, request: Request = None):
    """
    简历-岗位 Gap 分析：六维度透明评分。
      技能(35%) / 城市(15%) / 学历(15%) / 经验(15%) / 薪资(10%) / 可信度(10%)
    当 market.db 中有对应岗位数据时，自动注入市场基准（薪资分位、学历分布等）。
    """
    try:
        result = await gap_analyzer.analyze_gap(
            resume_text=req.resume_text,
            jd_text=req.jd_text,
            keyword=req.keyword or "",
            use_market=True,
            llm_client=llm_client,
        )
        return result
    except Exception as e:
        logger.error(f"Gap分析失败: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/career-plan", response_model=CareerPlanResponse)
@limiter.limit(config.RATE_LIMIT_CAREER)
async def career_plan(req: CareerPlanRequest, request: Request = None):
    """
    职业规划（v3.2）：简历 + 目标岗位 + 目标年限 → 时间轴多阶段路径。
    以 Gap 分析六维快照为现状基线，调用 LLM 做多步路径推理。
    错误统一转 500，日志不泄露简历原文。
    """
    try:
        result = await career_planner.plan_career(
            req=req,
            llm_client=llm_client,
        )
        return result
    except Exception as e:
        logger.error(f"职业规划失败: {type(e).__name__}: {e}")
        raise HTTPException(500, "职业规划服务暂时不可用，请稍后重试")


@app.get("/api/gap-analysis/{session_id}")
async def gap_analysis_by_session(session_id: str):
    """
    根据已完成的会话获取 Gap 分析结果。
    优先使用面试时缓存的简历+JD，若无则返回 404。
    """
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    resume_text = session.get("resume_text", "")
    jd_text = session.get("jd_text", "")
    if not resume_text and not jd_text:
        raise HTTPException(400, "该会话没有简历或JD，无法生成Gap分析")

    # 从 JD 中提取关键词用于市场查询
    keyword = gap_analyzer._extract_keyword_from_jd(jd_text)

    try:
        result = await gap_analyzer.analyze_gap(
            resume_text=resume_text,
            jd_text=jd_text,
            keyword=keyword,
            use_market=True,
            llm_client=llm_client,
        )
        return result
    except Exception as e:
        logger.error(f"Gap分析失败(session={session_id}): {e}")
        raise HTTPException(500, str(e))


# ===== v3.1: 跨岗位对比 =====

def _sorted_gap_dims(gap: dict) -> list:
    """按权重排序的维度列表（权重高的排前面）"""
    dims = gap.get("dimensions", [])
    if not dims:
        return []
    return sorted(dims, key=lambda d: -(d.get("weight", 0) or 0))


def _make_compare_item(title: str, gap: dict) -> JobCompareItem:
    """将 gap 分析结果转换为对比项"""
    dims = _sorted_gap_dims(gap)
    strengths = [f"{d['name']} ({d['score']}/5)" for d in dims if d.get("score", 0) >= 3.5][:3]
    gaps_list = [f"{d['name']} ({d.get('score',0)}/5): {d.get('gap','')}" for d in dims if d.get("score", 0) < 3.5][:3]
    mr = gap.get("market_reference")
    return JobCompareItem(
        title=title,
        overall_score=gap["overall_score"],
        risk_level=gap["risk_level"],
        key_strengths=strengths,
        key_gaps=gaps_list if gaps_list else ["各维度表现均衡"],
        dimensions=[d for d in dims],
        market_reference=mr if mr and mr.get("keyword") else None,
    )


@app.post("/api/cross-job-compare", response_model=CrossJobCompareResponse)
@limiter.limit("5/minute")
async def cross_job_compare(req: CrossJobCompareRequest, request: Request = None):
    """
    一份简历 vs 多个岗位：并行评估每个岗位的匹配度，输出排名 + 推荐。
    每个岗位独立调用 Gap 分析（含市场参考），然后汇总对比。
    """

    if len(req.jd_list) < 2:
        raise HTTPException(400, "至少需要 2 个岗位进行对比")

    # 并行分析所有岗位（复用全局单例 llm_client，确保使用已配置后端）
    async def analyze_one(title: str, jd_text: str) -> tuple[str, dict]:
        try:
            result = await gap_analyzer.analyze_gap(
                resume_text=req.resume_text,
                jd_text=jd_text,
                use_market=True,
                llm_client=llm_client,
            )
            return title, result
        except Exception as e:
            logger.warning(f"跨岗位对比-{title} 分析失败: {e}")
            return title, gap_analyzer._fallback_gap_result(str(e))

    tasks = [analyze_one(entry.title, entry.text) for entry in req.jd_list]
    raw_results = await asyncio.gather(*tasks)

    # 转换为对比结果列表
    compare_items = [_make_compare_item(title, gap) for title, gap in raw_results]

    # 按总分排序（降序）
    compare_items.sort(key=lambda x: x.overall_score, reverse=True)

    # 生成推荐语
    ranking = [item.title for item in compare_items]
    best = compare_items[0]
    worst = compare_items[-1]
    score_gap = best.overall_score - worst.overall_score

    if score_gap > 1.5:
        recommendation = (
            f"强烈推荐「{best.title}」— 综合匹配度 {best.overall_score}/5，"
            f"远高于「{worst.title}」({worst.overall_score}/5)。"
            f"建议优先投递该岗位方向。"
        )
    elif score_gap > 0.5:
        recommendation = (
            f"推荐「{best.title}」({best.overall_score}/5)，与「{worst.title}」"
            f"({worst.overall_score}/5) 有一定差距。二者的方向不同，建议根据个人偏好权衡。"
        )
    else:
        recommendation = (
            f"各岗位匹配度接近（最高 {best.overall_score}/5，最低 {worst.overall_score}/5）。"
            f"建议综合考虑公司、团队、成长空间等因素做决策。"
        )

    return CrossJobCompareResponse(
        results=compare_items,
        recommendation=recommendation,
        ranking=ranking,
    )


# ===== v3.1: 预热机制 =====

@app.post("/api/warmup")
@limiter.limit("1/minute")
async def warmup(request: Request):
    """
    预热：预计算所有已知 JD 的权重缓存。
    遍历历史会话中的唯一 JD 文本，对未缓存的调用 LLM 分析并写入缓存。
    返回 {precomputed, skipped} 计数。
    """
    try:
        import hashlib
        sessions_data = await list_sessions()
        sessions = sessions_data.get("sessions", []) if isinstance(sessions_data, dict) else []
    except Exception:
        sessions = []

    if not sessions:
        return {"message": "没有历史会话可预热", "precomputed": 0, "skipped": 0, "total_jds": 0}

    # 收集唯一 JD 文本
    seen_hashes = set()
    unique_jds: list[str] = []
    for s in sessions:
        jd = (s.get("jd_text") or "").strip()
        if jd and len(jd) >= 8:
            jd_normalized = jd[:2000]
            h = hashlib.sha256(jd_normalized.encode("utf-8")).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_jds.append(jd_normalized)

    if not unique_jds:
        return {"message": "没有足够长的 JD 文本可预热", "precomputed": 0, "skipped": 0, "total_jds": 0}

    precomputed = 0
    skipped = 0

    from .dimension_weights import analyze_jd_weights

    llm = LLMClient()

    for jd_text in unique_jds:
        jd_hash = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
        # 检查是否已有缓存
        try:
            from .db import lookup_jd_weights
            existing = await lookup_jd_weights(jd_hash)
            if existing:
                skipped += 1
                continue
        except Exception:
            pass

        # 缓存未命中，调用 LLM 并写入缓存
        try:
            await analyze_jd_weights(llm, jd_text)
            precomputed += 1
        except Exception as e:
            logger.warning(f"预热 JD 权重失败: {e}")

    return {
        "message": f"预热完成：{precomputed} 个已计算，{skipped} 个已缓存",
        "precomputed": precomputed,
        "skipped": skipped,
        "total_jds": len(unique_jds),
    }


# ===== WebSocket 面试 =====


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
    async with _session_lock:
        session = active_sessions.get(session_id)

    if not session:
        await websocket.send_json({"type": "error", "data": {"message": "会话不存在"}})
        await websocket.close(code=4000, reason="session_not_found")
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
                        "question_type": q.get("question_type", ""),
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

        # v2.7: 保存薄弱点画像
        try:
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
                                            weights_map.get(dim_key, 0.2), rps)
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
        async with _session_lock:
            active_sessions.pop(session_id, None)


# ===== 静态文件 =====
# v4.0: 优先托管 Vite 构建产物 frontend/dist；未构建时回退到 frontend 源码目录，
# 保证 python run.py 在未执行 npm run build 时仍可直接使用。
def _mount_frontend_static():
    dist_dir = os.path.join("frontend", "dist")
    if os.path.isdir(dist_dir):
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
        logger.info("静态资源托管：%s（Vite 构建产物）", dist_dir)
    else:
        app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
        logger.info("静态资源托管：frontend（未发现 dist，回退源码目录）")


try:
    _mount_frontend_static()
except RuntimeError:
    logger.info("静态文件挂载跳过（可能已存在）")
