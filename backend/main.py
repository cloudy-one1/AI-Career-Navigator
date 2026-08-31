"""
FastAPI 应用装配（v7.2.2 起为纯装配层）。

v7.2.2 路由拆分：66 条 HTTP 路由 + WS 主循环按域迁移到 backend/routers/*
（system/auth/voice/sessions/assets/reports/question_bank/diagnostics/
market/analytics/interview_ws），本文件只保留：
  - 中间件（CORS / 安全响应头 / 请求体大小限制）与限流异常处理器；
  - startup（建库 / 市场库 / 记忆修剪）；
  - include_router（保持与拆分前相同的域注册顺序）；
  - 静态文件挂载。
全局服务单例收敛在 routers/state.py，认证依赖与归属断言在 routers/deps.py。
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from . import logger as app_logger
from .config import APP_VERSION, config
from .db import init_db
from .market import store as market_store
from . import weakness_memory
from .routers import state
from .routers import (
    system, auth, voice, sessions, assets, reports,
    question_bank, diagnostics, market, analytics, interview_ws, profile,
)

# ─── 集中日志 ───
app_logger.setup_logging()
logger = logging.getLogger("main")


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
    # v7.4: 补 /api/voice/asr —— 录音上传与简历上传同属二进制大body，此前漏登记导致
    # 走普通请求的 1MB 额度，而前端 maxDurationMs=120000（约 1~2MB 音频）必然 413。
    _UPLOAD_PATHS = (
        "/api/sessions/upload", "/api/market/import", "/api/upload-jd",
        "/api/voice/asr",
    )

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

# ─── startup（v7.3.1: on_event 已弃用，迁移到 lifespan）───
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await market_store.init_market_db()  # v3.0: 市场岗位库（幂等）
    # v6.5: 清理 30 天未再加重的历史薄弱点（启动即跑一次，失败不影响启动）
    await weakness_memory.prune_expired()
    logger.info(f"AI 求职陪跑平台 v{APP_VERSION} 启动完成，当前后端: {config.AI_PROVIDER}")
    yield


# ─── FastAPI 应用 ───
app = FastAPI(title="AI 求职陪跑平台", version=APP_VERSION, lifespan=lifespan)

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
app.state.limiter = state.limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429,
    content={"detail": f"请求过于频繁，请稍后再试。限制：{config.RATE_LIMIT_GLOBAL}"},
))


# ─── 路由注册（保持与拆分前 main.py 一致的域顺序）───
app.include_router(system.router)          # 健康检查 + AI 后端管理 + 预热
app.include_router(auth.router)            # v7.0 认证
app.include_router(voice.router)           # v4.2 MiMo 云端语音
app.include_router(sessions.router)        # 会话创建/查询/上传/模式切换/公司风格
app.include_router(assets.router)          # v7.0 简历库/岗位库
app.include_router(reports.router)         # 报告读取 + Markdown/HTML 导出
app.include_router(question_bank.router)   # v2.2 题库
app.include_router(diagnostics.router)     # v2.5 反馈 + v2.7 薄弱点（/points 先于 /{session_id}）
app.include_router(market.router)          # v3.0/v3.3 市场数据 + 实时采集 + 岗位研究
app.include_router(analytics.router)       # v3.1 Gap 分析 + 跨岗位对比 + v3.2 职业规划
app.include_router(profile.router)         # v8.0 求职档案（能力档案首屏数据源）
app.include_router(interview_ws.router)    # WebSocket 面试主循环


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
