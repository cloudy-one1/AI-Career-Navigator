#!/usr/bin/env python
"""一键启动脚本：AI面试官 v2"""
import os
import sys
import subprocess

def main():
    # 确保在项目根目录
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    # 检查 .env
    if not os.path.exists(".env"):
        print("[WARNING] .env 文件不存在，请复制 .env.example 并填写 DEEPSEEK_API_KEY")

    # 确保数据目录存在
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/uploads", exist_ok=True)

    print("=" * 50)
    print("  AI面试官 v2 启动中...")
    print("  前端: http://localhost:8000")
    print("  API文档: http://localhost:8000/docs")
    print("=" * 50)

    python = [sys.executable] if sys.executable else ["python"]

    subprocess.run(
        python + [
            "-m", "uvicorn", "backend.main:app",
            "--host", "0.0.0.0", "--port", "8000", "--reload",
        ],
    )


if __name__ == "__main__":
    main()
