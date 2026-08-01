#!/usr/bin/env python
"""一键启动脚本：AI面试官 v3.1 — 本地开发模式"""
import logging
import os
import sys
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run")


def main():
    # 确保在项目根目录
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    # 检查 .env
    if not os.path.exists(".env"):
        log.warning(".env 文件不存在，请复制 .env.example 并填写 DEEPSEEK_API_KEY")

    # 确保数据目录存在
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/uploads", exist_ok=True)

    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")

    log.info("=" * 50)
    log.info("  AI面试官 v3.1 本地开发模式")
    log.info("  前端: http://localhost:%s", port)
    log.info("  API文档: http://localhost:%s/docs", port)
    log.info("=" * 50)

    python = [sys.executable] if sys.executable else ["python"]

    subprocess.run(
        python + [
            "-m", "uvicorn", "backend.main:app",
            "--host", host, "--port", port, "--reload",
        ],
    )


if __name__ == "__main__":
    main()
