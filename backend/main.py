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
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query, HTTPException, Response, Request, Depends
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
    list_weakness_points, list_unresolved_weaknesses,   # v6.3 长期记忆
    mark_weakness_resolved, delete_weakness,
    # v7.0 简历库 / 岗位库（可复用输入资产）
    save_resume, get_resume, list_resumes, update_resume, delete_resume,
    save_position, get_position, list_positions, update_position, delete_position,
    update_session_flow,   # v7.0 流程位置落库
)
from .interview_engine.flow import FlowState  # v7.0 流程状态枚举（纯数据）
from . import auth  # v7.0 认证与资源归属（L2，登记进 .importlinter）
from . import share_access  # v7.0 分享访问与脱敏（L2）
from .db import save_feedback as db_save_feedback, get_feedback_stats
from .llm_client import LLMClient, _api_key_issue
from .diagnosis_engine import DiagnosisEngine
from .interview_engine import InterviewSession  # v2.5: 子包引用
from .interview_engine.session import is_end_signal  # v6.1: 结束面试退出口令检测
from .interview_engine.report import generate_review_markdown
from .resume_parser import (  # v6.2 简历追问点
    MIN_RESUME_CHARS,
    extract_interview_points,
    parse_resume,
)
from .schemas import (
    SessionCreateRequest, SessionCreateResponse,
    ProviderSwitchRequest, ProviderListResponse, ProviderInfo,
    ReportData, DiagnosisFeedbackRequest, FeedbackStatsResponse,
    GapAnalysisRequest, GapAnalysisResponse,
    CrossJobCompareRequest, CrossJobCompareResponse, JobCompareItem,
    CareerPlanRequest, CareerPlanResponse,  # v3.2 职业规划
    ModeSwitchRequest, ModeSwitchResponse,  # v5.0 面试模式切换
    WeaknessResolveRequest,  # v6.3 长期记忆
    RegisterRequest, LoginRequest, TokenResponse, UserInfo,  # v7.0 认证
    ResumeCreateRequest, ResumeUpdateRequest,                # v7.0 简历库
    PositionCreateRequest, PositionUpdateRequest,            # v7.0 岗位库
    ShareCreateRequest,                                      # v7.0 报告分享
)
from .security import full_check, check_output
from .web_research import enrich_jd_with_research
from . import question_bank as qbank
from .market import store as market_store, service as market_service  # v3.0
from .market.crawler import tasks as crawler_tasks  # v3.3 实时采集（B档内嵌）
from .market.crawler.adapters import build_jd_text  # v3.3 岗位 JD 组装
from . import gap_analyzer  # v3.1
from . import career_planner  # v3.2 职业规划
from . import company_profiles  # v6.5 公司风格层（借鉴 interviewerAgent companies/*.yaml）
from . import weakness_memory   # v6.5 长期薄弱点记忆（EMA 衰减 + 过期淘汰）
from .voice_service import voice_service  # v4.2 MiMo 云端语音（TTS/ASR 代理）

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
    _UPLOAD_PATHS = ("/api/sessions/upload", "/api/market/import", "/api/upload-jd")

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

# ===== v7.0: 认证依赖（组合发生在 L4；auth.py 本身不感知 HTTP）=====

async def get_current_user(http_request: Request) -> "auth.UserContext":
    """解析当前用户。AUTH_ENABLED=false 时恒返回匿名（行为等同 v6.x）。"""
    return await auth.get_current_user(http_request.headers.get("authorization"))


async def require_user(user: "auth.UserContext" = Depends(get_current_user)) -> "auth.UserContext":
    """要求登录。认证关闭时不拦截（保持开关语义一致）。"""
    if config.AUTH_ENABLED and user.is_anonymous:
        raise HTTPException(status_code=401, detail="需要登录后操作")
    return user


# 允许上传的简历扩展名（两处上传端点共用，避免一边改了另一边漏）
_ALLOWED_UPLOAD_EXT = (".pdf", ".docx", ".txt")


async def assert_session_owner(session_id: str, user: "auth.UserContext") -> None:
    """会话归属断言。

    **一律返回 404 而非 403**：403 会暴露"这个 session_id 存在，只是你没权限"，
    攻击者可据此枚举有效会话 id。404 让"不存在"与"无权访问"无法区分。
    """
    if not config.AUTH_ENABLED:
        return
    if not await auth.can_access_session(user, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")


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
    # v6.5: 清理 30 天未再加重的历史薄弱点（启动即跑一次，失败不影响启动）
    await weakness_memory.prune_expired()
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


# ===== v4.2: MiMo 云端语音代理（TTS / ASR）=====
# 密钥仅存后端 .env，前端不接触。未配 Key 或失败时返回 used/ok=false，由前端降级到浏览器原生语音。

class VoiceTTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None  # None 时由后端解析为配置默认音色


@app.post("/api/voice/tts")
@limiter.limit(config.RATE_LIMIT_VOICE)
async def voice_tts(req: VoiceTTSRequest, request: Request = None):
    """文本 -> mimo-v2.5-tts -> 音频（Base64 WAV）。"""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="文本不能为空")
    if not voice_service.enabled:
        return {"used": False, "message": "未配置 MIMO_API_KEY"}
    usage = await asyncio.to_thread(voice_service.synthesize, req.text, req.voice)
    return {
        "used": usage.used,
        "audio_b64": usage.audio_b64,
        "format": usage.format,
        "message": usage.message,
    }


@app.post("/api/voice/asr")
@limiter.limit(config.RATE_LIMIT_VOICE)
async def voice_asr(request: Request, file: UploadFile = File(...)):
    """上传音频 -> mimo-v2.5-asr -> 转写文本。"""
    if not voice_service.enabled:
        return {"ok": False, "text": "", "message": "未配置 MIMO_API_KEY"}
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="音频文件为空")
    mime = file.content_type or "audio/webm"
    result = await asyncio.to_thread(
        voice_service.transcribe, audio_bytes, file.filename or "audio.webm", mime
    )
    return {"ok": result.ok, "text": result.text, "message": result.message}


# ===== 会话管理 =====

# ===== v7.0: 认证端点 =====

@app.post("/api/auth/register", response_model=TokenResponse, status_code=201)
@limiter.limit(config.RATE_LIMIT_SESSION)
async def register(req: RegisterRequest, request: Request = None):
    """注册并直接签发 token。

    注意参数名必须是 `request`：slowapi 的限流装饰器靠参数名注入请求对象，
    改名（如 http_request）会让它抛 `No "request" argument`。

    认证关闭时仍可用（行为与开启时一致）：开关只影响"是否强制要求登录"，
    不影响认证功能本身，前端因此无需为两种模式写两套代码。
    """
    user, err = await auth.register_user(
        req.username, req.password,
        role=req.role.value if hasattr(req.role, "value") else str(req.role),
        display_name=req.display_name,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.role, user.username),
        expires_in_hours=config.AUTH_TOKEN_TTL_HOURS,
        user=UserInfo(id=user.id, username=user.username, role=user.role,
                      display_name=user.display_name, is_anonymous=False),
    )


@app.post("/api/auth/login", response_model=TokenResponse)
@limiter.limit(config.RATE_LIMIT_SESSION)
async def login(req: LoginRequest, request: Request = None):
    """登录。用户名不存在与密码错误返回同一条消息（防用户名枚举）。"""
    user = await auth.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.role, user.username),
        expires_in_hours=config.AUTH_TOKEN_TTL_HOURS,
        user=UserInfo(id=user.id, username=user.username, role=user.role,
                      display_name=user.display_name, is_anonymous=False),
    )


@app.get("/api/auth/me", response_model=UserInfo)
async def me(user: "auth.UserContext" = Depends(get_current_user)):
    """当前身份。匿名模式（AUTH_ENABLED=false）返回 is_anonymous=true。"""
    return UserInfo(id=user.id, username=user.username, role=user.role,
                    display_name=user.display_name, is_anonymous=user.is_anonymous)


@app.post("/api/sessions", response_model=SessionCreateResponse)
@limiter.limit(config.RATE_LIMIT_SESSION)
async def create_session(req: SessionCreateRequest,
                         user: "auth.UserContext" = Depends(require_user),
                         request: Request = None):
    session_id = uuid.uuid4().hex[:12]

    # v7.0: 简历/岗位优先从库中取（传入 id 时），未传 id 则沿用"直接传文本"的旧行为。
    # 库内资源不存在 / 不属于当前用户 → 404（与会话归属同一口径，不泄露资源存在性）。
    if req.resume_id:
        row = await get_resume(req.resume_id)
        if not row:
            raise HTTPException(404, "简历不存在或无权访问")
        if config.AUTH_ENABLED and not user.is_anonymous and row.get("owner_id") != user.id:
            raise HTTPException(404, "简历不存在或无权访问")
        req.resume_text = row.get("raw_text") or ""
    if req.position_id:
        row = await get_position(req.position_id)
        if not row:
            raise HTTPException(404, "岗位不存在或无权访问")
        if config.AUTH_ENABLED and not user.is_anonymous and row.get("owner_id") != user.id:
            raise HTTPException(404, "岗位不存在或无权访问")
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

    # v6.2: 简历前置追问点（deepDivePoints/vaguePoints）—— 解析阶段一次性产出，
    # 后续各轮出题复用，让追问有数据支撑。失败降级为空，不阻断会话创建。
    resume_points: dict = {}
    if resume_text and len(resume_text.strip()) >= MIN_RESUME_CHARS:
        try:
            resume_points = await asyncio.to_thread(
                extract_interview_points, resume_text, llm_client, jd_final
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
                llm_client=llm_client,
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
                       owner_id=user.id,              # v7.0 归属（匿名模式下为 None）
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
        llm_client=llm_client,
        diagnosis_engine=diagnosis_engine,
        interview_style=req.style or "friendly",
        mode=req.mode.value if req.mode else "simulation",
        stage=req.stage.value if req.stage else "phone_screen",
        include_self_intro=req.include_self_intro or False,
        question_type_mix=req.question_type_mix or {},
        resume_points=resume_points,
        jd_gaps=jd_gaps,   # v6.3: JD 匹配缺口（出题优先级链第一环）
        company_profile=company_profile,   # v6.5: 目标公司风格（None = 不启用）
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
        company_profile=company_display,
    )


# ===== v6.5: 公司风格列表（供前端选择器） =====

@app.get("/api/company-profiles")
async def list_company_profiles():
    """返回全部已加载的公司风格配置摘要。目录为空 / pyyaml 缺失时返回空列表。"""
    return company_profiles.list_profiles()


@app.post("/api/sessions/upload")
@limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_resume(request: Request, file: UploadFile = File(...)):
    # 额外：文件大小硬限制（前端也应校验，但后端做最后一道防线）
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB")

    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in _ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {_ALLOWED_UPLOAD_EXT}")

    text = parse_resume(content, filename=file.filename)
    return {"filename": file.filename, "text": text[:5000], "length": len(text)}


@app.post("/api/upload-jd")
@limiter.limit(config.RATE_LIMIT_UPLOAD)
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
    if f".{ext}" not in _ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {_ALLOWED_UPLOAD_EXT}")

    text = parse_resume(content, filename=file.filename)
    if not text or not text.strip():
        raise HTTPException(400, "未能从文件中提取到文本，请确认文件内容")
    return {"filename": file.filename, "text": text[:20000], "length": len(text)}


# ===== v7.0: 简历库 / 岗位库（可复用输入资产）=====
#
# 这两个实体的意义在"跨会话复用"：同一份简历想练第二场不用重新上传、重新解析
# （解析要调 LLM）。岗位同理——JD 不必每次粘贴。

def _assert_owner(row: Optional[dict], user: "auth.UserContext") -> None:
    """归属断言：他人的资源一律 404（不泄露存在性），老数据 owner=NULL 时同样拒绝。"""
    if not row:
        raise HTTPException(404, "资源不存在或无权访问")
    if config.AUTH_ENABLED and not user.is_anonymous and row.get("owner_id") != user.id:
        raise HTTPException(404, "资源不存在或无权访问")


@app.get("/api/resumes")
async def api_list_resumes(user: "auth.UserContext" = Depends(require_user)):
    """列表不含 raw_text（可能上万字符，N 条会把响应撑到几 MB）。"""
    return {"resumes": await list_resumes(owner_id=auth.ownership_filter(user))}


@app.post("/api/resumes/upload", status_code=201)
@limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_resume_to_library(file: UploadFile = File(...),
                                  user: "auth.UserContext" = Depends(require_user),
                                  request: Request = None):
    """上传简历并写入简历库。

    为什么不复用 /api/sessions/upload：那个接口为兼容既有前端把文本截断到 5000 字。
    截断用于"临时上传后立刻开练"尚可，用于**入库**则不可接受 —— 截断是静默的，
    用户下次选用这份简历时看不到任何异常，但 LLM 看到的简历是不完整的，
    出题质量随之下降且无从归因。
    """
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in _ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {_ALLOWED_UPLOAD_EXT}")

    raw_text = parse_resume(content, filename=file.filename)
    if not raw_text or not raw_text.strip():
        raise HTTPException(400, "未能从文件中提取到文本，请确认文件内容")
    resume_id = uuid.uuid4().hex[:12]
    title = file.filename.rsplit(".", 1)[0] or "未命名简历"
    await save_resume(resume_id, title=title, raw_text=raw_text,
                      owner_id=user.id, filename=file.filename)
    row = await get_resume(resume_id)
    row.pop("raw_text", None)   # 回执不需要回传全文
    return {"resume": row}


@app.post("/api/resumes", status_code=201)
async def api_create_resume(req: ResumeCreateRequest,
                            user: "auth.UserContext" = Depends(require_user)):
    resume_id = uuid.uuid4().hex[:12]
    await save_resume(
        resume_id, title=req.title.strip() or "未命名简历", raw_text=req.raw_text,
        owner_id=user.id, filename=req.filename, parsed_json=req.parsed_json,
    )
    row = await get_resume(resume_id)
    row.pop("raw_text", None)
    return {"resume": row}


@app.get("/api/resumes/{resume_id}")
async def api_get_resume(resume_id: str,
                         user: "auth.UserContext" = Depends(require_user)):
    _assert_owner(await get_resume(resume_id), user)
    return {"resume": await get_resume(resume_id)}


@app.patch("/api/resumes/{resume_id}")
async def api_update_resume(resume_id: str, req: ResumeUpdateRequest,
                            user: "auth.UserContext" = Depends(require_user)):
    _assert_owner(await get_resume(resume_id), user)
    await update_resume(resume_id, title=req.title, parsed_json=req.parsed_json)
    row = await get_resume(resume_id)
    row.pop("raw_text", None)
    return {"resume": row}


@app.delete("/api/resumes/{resume_id}")
async def api_delete_resume(resume_id: str,
                            user: "auth.UserContext" = Depends(require_user)):
    _assert_owner(await get_resume(resume_id), user)
    await delete_resume(resume_id)
    return {"ok": True}


@app.get("/api/positions")
async def api_list_positions(user: "auth.UserContext" = Depends(require_user)):
    return {"positions": await list_positions(owner_id=auth.ownership_filter(user))}


@app.post("/api/positions", status_code=201)
async def api_create_position(req: PositionCreateRequest,
                              user: "auth.UserContext" = Depends(require_user)):
    position_id = uuid.uuid4().hex[:12]
    await save_position(
        position_id, title=req.title.strip() or "未命名岗位", jd_text=req.jd_text,
        owner_id=user.id, department=req.department,
    )
    return {"position": await get_position(position_id)}


@app.get("/api/positions/{position_id}")
async def api_get_position(position_id: str,
                           user: "auth.UserContext" = Depends(require_user)):
    _assert_owner(await get_position(position_id), user)
    return {"position": await get_position(position_id)}


@app.patch("/api/positions/{position_id}")
async def api_update_position(position_id: str, req: PositionUpdateRequest,
                              user: "auth.UserContext" = Depends(require_user)):
    _assert_owner(await get_position(position_id), user)
    await update_position(position_id, title=req.title, jd_text=req.jd_text,
                          department=req.department)
    return {"position": await get_position(position_id)}


@app.delete("/api/positions/{position_id}")
async def api_delete_position(position_id: str,
                              user: "auth.UserContext" = Depends(require_user)):
    _assert_owner(await get_position(position_id), user)
    await delete_position(position_id)
    return {"ok": True}


@app.get("/api/sessions")
async def api_list_sessions(user: "auth.UserContext" = Depends(require_user)):
    """v7.0: 按归属过滤。匿名模式（AUTH_ENABLED=false）返回全部，等同 v6.x。"""
    sessions = await list_sessions(owner_id=auth.ownership_filter(user))
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str,
                          user: "auth.UserContext" = Depends(require_user)):
    await assert_session_owner(session_id, user)   # 越权/不存在一律 404
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    qas = await get_session_qas(session_id)
    # v4.0: 附带报告，供历史详情抽屉展示综合评分/轮次汇总
    report = await get_report(session_id)
    return {"session": session, "qa_count": len(qas), "qas": qas, "report": report}


# ===== v5.0: 会话进行中切换面试模式/阶段 =====

@app.post("/api/interview/{session_id}/mode", response_model=ModeSwitchResponse)
@limiter.limit(config.RATE_LIMIT_SESSION)
async def switch_interview_mode(session_id: str, req: ModeSwitchRequest,
                                 user: "auth.UserContext" = Depends(require_user),
                                 request: Request = None):
    await assert_session_owner(session_id, user)
    async with _session_lock:
        session = active_sessions.get(session_id)
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


# ===== v7.0: 报告分享（招聘端只读入口）=====
#
# 三个端点的权限口径：
#   POST   /api/sessions/{id}/share    需登录 + 会话归属（只有本人能分享自己的报告）
#   GET    /api/sessions/{id}/shares   需登录 + 会话归属
#   DELETE /api/shares/{token}         需登录 + 创建者匹配
#   GET    /api/shared/{token}         **免登录** —— 拿链接的是外部 HR，不该被要求注册
# 免登录读取的安全性由"高熵随机 token + 只存摘要 + 可撤销 + 可过期"保证，
# 而不是靠"知道链接的人是谁"。

@app.post("/api/sessions/{session_id}/share", status_code=201)
async def create_share(session_id: str, req: ShareCreateRequest,
                       user: "auth.UserContext" = Depends(require_user)):
    await assert_session_owner(session_id, user)
    # 先判会话存在（404，与归属同一口径），再判报告存在（400，属用法错误）。
    # 顺序不能反，否则"会话不存在"会被报成 400，泄露了与越权场景不同的响应特征。
    if not await get_session(session_id):
        raise HTTPException(404, "会话不存在或无权访问")
    if not await get_report(session_id):
        raise HTTPException(400, "该会话还没有生成报告，无法分享")
    try:
        link = await share_access.create_share_link(
            session_id, created_by=user.id, include_detail=req.include_detail,
            expires_days=req.expires_days, shared_with=req.shared_with)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    # 明文 token 只在这一次响应中出现，之后无法再从库中还原
    return {"share": link, "url": f"/share/{link['token']}"}


# ===== v7.0.1: 招聘者收件箱（登录态下的受控读取）=====
#
# 与免登录的 /api/shared/{token} 是两条独立通道：收件箱按登录身份
# （shared_with=当前招聘者用户名）过滤，报告数据直接随接口返回，
# 不经过"凭明文 token"的免登录端点——两条通道互不放大对方的风险面。

@app.get("/api/recruiter/inbox")
async def recruiter_inbox(user: "auth.UserContext" = Depends(require_user)):
    """招聘者的"收到的报告"列表（摘要层）。仅 recruiter 角色可用。"""
    if config.AUTH_ENABLED and user.role != "recruiter":
        raise HTTPException(403, "仅招聘者账户可访问收件箱")
    return {"reports": await share_access.recruiter_inbox(user.username)}


@app.get("/api/recruiter/reports/{token_hash}")
async def recruiter_open_report(token_hash: str,
                                user: "auth.UserContext" = Depends(require_user)):
    """招聘者打开收件箱中的一份报告（完整脱敏载荷）。仅发件指定的本人可见。"""
    if config.AUTH_ENABLED and user.role != "recruiter":
        raise HTTPException(403, "仅招聘者账户可访问收件箱")
    try:
        payload = await share_access.open_inbox_report(token_hash, user.username)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    return payload


@app.get("/api/sessions/{session_id}/shares")
async def list_shares(session_id: str,
                      user: "auth.UserContext" = Depends(require_user)):
    await assert_session_owner(session_id, user)
    return {"shares": await share_access.list_share_links(session_id)}


@app.delete("/api/shares/{token}")
async def revoke_share(token: str,
                       user: "auth.UserContext" = Depends(require_user)):
    try:
        await share_access.revoke_share_link(token, user.id)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    return {"ok": True}


@app.get("/api/shared/{token}")
async def read_shared_report(token: str):
    """免登录只读。任何不合法情况统一 404 —— 不区分"不存在/已撤销/已过期"。

    统一措辞是有意的：若三者的响应不同，攻击者就能用响应差异枚举有效令牌。
    """
    try:
        payload = await share_access.resolve_shared_report(token)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    return payload


@app.get("/api/reports/{session_id}")
async def api_get_report(session_id: str,
                         user: "auth.UserContext" = Depends(require_user)):
    """报告含完整的简历事实与逐题诊断，是隐私敏感度最高的端点，必须校验归属。"""
    await assert_session_owner(session_id, user)
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


# v6.3 长期记忆闭环：明细 / 复习建议 / 标记已解决 / 删除。
# 注意路由顺序——静态段必须注册在 /{session_id} 之前，
# 否则 "points" / "suggestions" 会被当成 session_id 吃掉。
@app.get("/api/weakness-profile/points")
async def weakness_points(include_resolved: bool = False,
                          limit: int = Query(200, ge=1, le=1000)):
    """薄弱点明细（记忆图谱数据源）。

    include_resolved 默认 False：主视图只呈现未解决的短板；
    limit 兜住上限，避免历史数据多了之后一次性拉爆前端 DOM。
    """
    try:
        points = await list_weakness_points(include_resolved=include_resolved,
                                            limit=limit)
        return {"status": "ok", "count": len(points), "points": points}
    except Exception as e:
        logger.error(f"获取薄弱点明细失败: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/weakness-profile/suggestions")
async def weakness_suggestions(limit: int = Query(5, ge=1, le=20)):
    """复习建议：最该优先补的未解决薄弱点（与面试回注入同一排序口径）。

    v6.5: 与回注入同口径——优先 EMA 薄弱度降序，新表为空时回退 v6.3 的均分升序。
    """
    try:
        suggestions = await weakness_memory.active_memory_points(limit=limit)
        if not suggestions:
            suggestions = await list_unresolved_weaknesses(limit=limit)
        return {"status": "ok", "count": len(suggestions), "suggestions": suggestions}
    except Exception as e:
        logger.error(f"获取复习建议失败: {e}")
        raise HTTPException(500, str(e))


@app.put("/api/weakness-profile/{point_id}/resolve")
async def resolve_weakness(point_id: int, payload: WeaknessResolveRequest):
    """标记薄弱点已解决 / 恢复未解决（闭环的收敛动作）。"""
    try:
        ok = await mark_weakness_resolved(point_id, payload.resolved)
        if not ok:
            raise HTTPException(404, "薄弱点不存在")
        return {"status": "ok", "id": point_id, "resolved": payload.resolved}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新薄弱点状态失败: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/weakness-profile/{point_id}")
async def remove_weakness(point_id: int):
    """删除单条薄弱点（与"标记已解决"区分：这是物理删除，不可恢复）。"""
    try:
        ok = await delete_weakness(point_id)
        if not ok:
            raise HTTPException(404, "薄弱点不存在")
        return {"status": "ok", "id": point_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除薄弱点失败: {e}")
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


# ===== v6.1: 复盘报告 HTML 导出（借鉴 offerMaster report_pdf.py 的 MD→HTML 模板渲染） =====
# 用浏览器打印（Ctrl+P → 另存为 PDF）替代 weasyprint 服务端出 PDF：
# weasyprint 依赖 GTK/Pango，Windows 部署成本高；HTML 模板 + 打印样式零重量级依赖。

_REPORT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif;
         max-width: 820px; margin: 24px auto; padding: 0 16px; color: #1f2328;
         line-height: 1.7; }}
  h1 {{ border-bottom: 2px solid #2563eb; padding-bottom: 8px; }}
  h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 4px; margin-top: 28px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; }}
  th {{ background: #f6f8fa; }}
  blockquote {{ border-left: 4px solid #2563eb; margin: 8px 0; padding: 4px 14px;
               color: #57606a; background: #f6f8fa; }}
  code {{ background: #f6f8fa; padding: 1px 5px; border-radius: 4px; }}
  pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }}
  @media print {{
    body {{ margin: 0; max-width: none; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
<button class="no-print" onclick="window.print()"
        style="float:right;padding:8px 14px;cursor:pointer;">🖨 打印 / 另存为 PDF</button>
{body}
</body>
</html>"""


@app.get("/api/reports/{session_id}/export.html")
async def export_report_html(session_id: str,
                             user: "auth.UserContext" = Depends(require_user)):
    """导出复盘报告 HTML（Markdown 渲染 + 打印样式，浏览器打印即得 PDF）"""
    await assert_session_owner(session_id, user)
    try:
        try:
            import markdown as _md
        except ImportError:
            raise HTTPException(500, "缺少 markdown 依赖，请执行 pip install -r requirements.txt")
        report = await get_report(session_id)
        if not report:
            raise HTTPException(404, "报告不存在")
        report = json.loads(report["report_json"]) if isinstance(report.get("report_json"), str) else report
        body = _md.markdown(
            generate_review_markdown(report),
            extensions=["tables", "fenced_code"],
        )
        html = _REPORT_HTML_TEMPLATE.format(title=f"面试复盘报告 · {session_id}", body=body)
        return Response(content=html, media_type="text/html; charset=utf-8")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成复盘 HTML 失败: {e}")
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


# ===== v3.3: 市场实时采集 API（job-crawler B档内嵌）=====

def _get_city_map():
    """延迟加载城市映射：依赖 playwright 安装，未装时给出明确指引。"""
    try:
        from .market.crawler.python_job_scraper import get_province_city_map  # noqa: PLC0415
        return get_province_city_map()
    except ModuleNotFoundError as e:
        raise HTTPException(
            500,
            f"实时采集组件未就绪：{e}。请执行 pip install playwright playwright-stealth "
            "并运行 playwright install chromium",
        )


@app.post("/api/market/crawl")
@limiter.limit(config.MARKET_CRAWL_RATE_LIMIT)
async def market_crawl(
    request: Request,
    keyword: str = Form(..., min_length=1, max_length=50),
    cities: Optional[List[str]] = Form(None),  # 不传 = 全国范围搜索（底层 scrape_jobs 支持）
    pages: int = Form(3),
    sort_type: str = Form("0"),
    token: Optional[str] = Form(None),
):
    """启动 51job 实时采集（后台任务，立即返回 task_id）。

    单实例互斥：已有 running 任务时返回 409；
    参数不合法返回 400；playwright 未安装返回 500（含安装指引）。
    """
    if config.MARKET_CRAWL_TOKEN and token != config.MARKET_CRAWL_TOKEN:
        raise HTTPException(401, "采集口令不正确")
    cities = [c for c in (cities or []) if c and c.strip()]  # 归一化：不传/空串 → []（全国）
    if len(cities) > config.MARKET_CRAWL_CITY_LIMIT:
        raise HTTPException(400, f"单次最多选择 {config.MARKET_CRAWL_CITY_LIMIT} 个城市")
    if not (1 <= pages <= config.MARKET_CRAWL_PAGE_LIMIT):
        raise HTTPException(400, f"页数需为 1~{config.MARKET_CRAWL_PAGE_LIMIT}")

    err = crawler_tasks.validate(keyword, cities, pages)
    if err:
        raise HTTPException(400, err)
    task, err2 = crawler_tasks.start_crawl(keyword, cities, pages, sort_type)
    if task is None:
        raise HTTPException(409, err2)
    return {"task_id": task.id}


@app.get("/api/market/crawl/status/{task_id}")
async def market_crawl_status(task_id: str):
    """查询采集任务状态（前端 1.5s 轮询；终态任务 TTL 10 分钟后惰性清理）。"""
    task = crawler_tasks.get_status(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在或已过期")
    return task.to_dict()


@app.get("/api/market/city-map")
async def market_city_map():
    """省份→城市级联数据（采集表单用，前端不内嵌 388 城市表）。"""
    return _get_city_map()


@app.get("/api/market/jobs/{job_id}")
async def market_job_detail(job_id: int):
    """岗位详情 + Gap 分析用 JD 文本（title/company/salary/edu/exp/tags/描述）。"""
    job = await market_store.get_job_by_id(job_id)
    if job is None:
        raise HTTPException(404, "岗位不存在")
    return {"job": job, "jd_text": build_jd_text(job)}


@app.post("/api/market/jobs/{job_id}/interest")
async def market_toggle_interest(job_id: int):
    """切换岗位「感兴趣」收藏状态（持久化到 market.db）。

    与题库收藏（question_bank.is_favorited）同模式：全局标记、不区分用户，
    因为本项目 market.db 为单机单用户库且支持免登录使用。
    返回新状态；岗位不存在返回 404。
    """
    state = await market_store.toggle_interest(job_id)
    if state is None:
        raise HTTPException(404, "岗位不存在")
    return {"job_id": job_id, "is_interested": state}


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


async def _mark_flow(session_id: str, session, state: "FlowState") -> None:
    """v7.0: 记录流程位置并落库。

    为什么单独封装：落库是"锦上添花"的能力，绝不能因为它失败而中断面试。
    所以这里吞掉所有异常，只记 debug 日志 —— 面试可用性优先于进度可观测性。

    为什么不做断点续答：那需要把 InterviewSession 的全部字段（轮次配置、
    诊断历史、追问状态、难度调度器……）序列化并从 DB 重建，改动面与风险都
    远大于收益。当前只保证"流程位置可追溯、答题进度不因重启归零"。
    """
    try:
        session.set_flow_state(state)
        await update_session_flow(session_id, state.value, session.answered_count)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[flow] 流程状态落库失败 session={session_id} state={state}: {e}")


@app.websocket("/ws/interview/{session_id}")
async def ws_interview(websocket: WebSocket, session_id: str,
                       token: str = Query(default="")):
    """v7.0: 握手阶段校验连接者身份。

    为什么 token 走 query 参数：浏览器的 WebSocket API 不支持自定义请求头，
    Sec-WebSocket-Protocol 子协议又要求服务端回显，这里用它反而更绕。

    为什么在 accept() 之前校验：`close()` 必须在握手未完成时调用才能带上
    自定义关闭码；一旦 accept 过再 close，浏览器只收得到 1000（正常关闭），
    前端就无法区分"会话不存在"与"没有权限"。
    """
    user = await auth.resolve_ws_user(token)
    if not await auth.can_access_session(user, session_id):
        logger.warning(f"[ws] 拒绝未授权连接 session={session_id} user={user.id}")
        await websocket.close(code=4001, reason="unauthorized")
        return

    await websocket.accept()
    async with _session_lock:
        session = active_sessions.get(session_id)

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
                _mark_flow(session_id, session, FlowState.WAITING_ANSWER)
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
                        from .schemas import InterviewMode, InterviewStage
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
                        _mark_flow(session_id, session, FlowState.GENERATING_FOLLOW_UP)
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
                            _mark_flow(session_id, session, FlowState.DECIDING_NEXT)
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
            _mark_flow(session_id, session, FlowState.ADVANCING_ROUND)

        # 3. 生成报告
        _mark_flow(session_id, session, FlowState.FINISHED)
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

            # v6.5: 长期薄弱点记忆（EMA 衰减 + 30 天过期 + 中性区不动）。
            # 与上面的快照写入是两件事：快照是历史流水，这里演进的是"当前状态"。
            for dim_key, avg in (report.get("dimension_averages") or {}).items():
                await weakness_memory.record_observation(
                    dim_key, avg, weights_map.get(dim_key, 0.2)
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
        async with _session_lock:
            active_sessions.pop(session_id, None)


# ===== v7.0: 招聘端分享页（独立入口）=====
# 必须注册在静态挂载之前：/share/{token} 是业务路由，不是静态文件，
# 若被 StaticFiles 先接管就会 404。
@app.get("/share/{token}")
async def share_page(token: str):
    """返回分享页 HTML。

    页面本身不含任何报告数据 —— 数据由前端拿 token 再去请求 /api/shared/{token}。
    这样"页面"与"数据"的权限口径可以各自独立演进：
    页面谁都能拿，数据过不过得了关由接口决定。
    """
    dist_html = os.path.join("frontend", "dist", "share.html")
    src_html = os.path.join("frontend", "share.html")
    path = dist_html if os.path.isfile(dist_html) else src_html
    try:
        with open(path, "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/html; charset=utf-8")
    except OSError:
        raise HTTPException(500, "分享页模板缺失")


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
