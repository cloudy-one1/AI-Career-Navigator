#!/usr/bin/env python
"""一键启动脚本：AI 求职领航 — 本地开发模式"""
import logging
import os
import shutil
import sys
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run")


def lint_imports():
    """运行 import-linter 分层依赖契约检查（v3.2）。

    注意两点：
    1. import-linter 必须走 `lint` 子命令才真正执行检查（裸 `-m importlinter.cli` 只打印帮助）。
    2. Windows 下源码为 UTF-8，须设置 PYTHONUTF8=1，否则 grimp 按 GBK 解析会崩溃或漏检。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    log.info("运行 import-linter 分层契约检查 ...")
    python = [sys.executable] if sys.executable else ["python"]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    code = subprocess.run(python + ["-m", "importlinter.cli", "lint"], env=env).returncode
    if code == 0:
        log.info("分层依赖契约检查通过 ✓")
    else:
        log.error("分层依赖契约检查失败，请修复越层依赖（详见 CHARTER.md 架构约束 2）")
    sys.exit(code)


def dev_front():
    """v4.0: 启动 Vite 前端开发服务器（:5173）。

    通过 vite.config.js 将 /api /ws /upload 代理到 FastAPI（:8000），
    后端需另行运行 `python run.py` 提供接口。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.join(root, "frontend")
    if not os.path.isdir(os.path.join(frontend_dir, "node_modules")):
        log.warning("未发现 frontend/node_modules，请先执行：cd frontend && npm install")
    npm = shutil.which("npm") or "npm"
    log.info("启动前端开发服务器（Vite :5173）...")
    log.info("提示：请保持后端运行（python run.py），/api /ws /upload 将代理到 :8000")
    subprocess.run([npm, "run", "dev"], cwd=frontend_dir)


def main():
    # 确保在项目根目录
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    # v3.2: lint 子命令（import-linter 分层契约检查）
    if len(sys.argv) > 1 and sys.argv[1] == "lint":
        lint_imports()
        return

    # v4.0: dev-front 子命令（Vite 前端开发服务器）
    if len(sys.argv) > 1 and sys.argv[1] == "dev-front":
        dev_front()
        return

    # 检查 .env
    if not os.path.exists(".env"):
        log.warning(".env 文件不存在，请复制 .env.example 并填写 DEEPSEEK_API_KEY")

    # 确保数据目录存在
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/uploads", exist_ok=True)

    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")

    # v7.3.1: 版本号统一引用 backend.config.APP_VERSION，避免横幅版本漂移
    try:
        from backend.config import APP_VERSION
    except Exception:
        APP_VERSION = "?"
    log.info("=" * 50)
    log.info("  AI 求职陪跑平台 v%s 本地开发模式", APP_VERSION)
    log.info("  前端: http://localhost:%s", port)
    log.info("  API文档: http://localhost:%s/docs", port)
    log.info("=" * 50)

    python = [sys.executable] if sys.executable else ["python"]

    # v3.3: 默认稳定模式（无热重载）。热重载会在代码变更时重启进程，
    # 导致内存中的 active_sessions 丢失、进行中的面试 WebSocket 断线。
    # 实测/完整面试流程请使用默认模式；开发调试时显式传 --dev 开启热重载。
    dev_mode = "--dev" in sys.argv
    cmd = python + ["-m", "uvicorn", "backend.main:app",
                    "--host", host, "--port", port]
    if dev_mode:
        # 仅监视 backend/，避免其他目录变更误触发
        cmd += ["--reload", "--reload-dir", "backend"]

    log.info("启动模式: %s", "开发热重载（仅监视 backend/）" if dev_mode
             else "稳定模式（无热重载，完整面试请用此模式）")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
