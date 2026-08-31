# ============================================================
# AI求职陪跑 v7.3 — 生产级 Docker 镜像
# 支持: docker run / docker compose / 任意容器平台
# ============================================================

FROM python:3.12-slim

# ---- 系统依赖 ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- 应用目录 ----
WORKDIR /app

# ---- Python 依赖（分层缓存，代码变更时复用）----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- 项目文件 ----
COPY . .

# ---- 创建非 root 用户 ----
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p data data/uploads \
    && chown -R appuser:appuser /app
USER appuser

# ---- 运行时配置 ----
EXPOSE 8000

ENV HOST=0.0.0.0 \
    PORT=8000 \
    LOG_LEVEL=info \
    UVICORN_WORKERS=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${PORT}/docs || exit 1

# ---- 启动 ----
# 单 worker 模式（默认）：适合轻量部署
# 多 worker 模式：设置环境变量 UVICORN_WORKERS=N（建议 ≤ CPU 核数）
CMD ["sh", "-c", "python -m uvicorn backend.main:app --host ${HOST} --port ${PORT} --log-level ${LOG_LEVEL} --workers ${UVICORN_WORKERS}"]
