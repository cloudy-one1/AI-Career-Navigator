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
    """运行 import-linter 分层依赖契约检查（v3.2；v8.10 修正为真跑）。

    踩过的坑：`python -m importlinter.cli lint` **不会执行任何检查**。
    importlinter/cli.py 没有 `if __name__ == "__main__"` 守卫，`-m` 方式只导入模块
    即以 0 退出（连帮助都不打印），于是本函数在 0.4 秒后打印"通过 ✓"，CI 同一条命令
    永远绿灯——分层契约实际从未被机器验证过。正确入口是 console script `lint-imports`，
    它由 click 命令 `lint_imports_command` 实现；这里直接调用该命令对象，避免依赖
    Scripts/bin 目录下的可执行文件位置（跨 Windows/Linux 一致）。
    另：Windows 下源码与 .importlinter 为 UTF-8，须 PYTHONUTF8=1，否则 grimp/配置读取
    按 GBK 解析会崩溃（实测报 `'gbk' codec can't decode byte 0xa1`）。
    守护有效性由 tests/test_layering_gate.py 反向钉住（故意越层的样本必须让门禁变红）。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    log.info("运行 import-linter 分层契约检查 ...")
    python = [sys.executable] if sys.executable else ["python"]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    entry = (
        "from importlinter.cli import lint_imports_command;"
        "lint_imports_command.main(prog_name='lint-imports')"
    )
    code = subprocess.run(python + ["-c", entry], env=env).returncode
    if code == 0:
        log.info("分层依赖契约检查通过 ✓")
    else:
        log.error("分层依赖契约检查失败，请修复越层依赖（L2 不得 import L3/L4，L3 不得 import L4）")
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

    log.info("=" * 50)
    log.info("  AI 求职领航 本地开发模式")
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
