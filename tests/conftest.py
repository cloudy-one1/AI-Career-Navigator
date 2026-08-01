"""
pytest 共享 fixtures：FastAPI TestClient、内存 DB、mock LLM。

用法:
    pytest tests/ -v
    pytest tests/ --cov=backend --cov-report=term-missing
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# 确保 backend 在 import 路径中
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# 设置测试环境
os.environ["AI_PROVIDER"] = "deepseek"
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["JOB_CRAWLER_DB_PATH"] = ""


@pytest.fixture(scope="session")
def event_loop():
    """session 级别的 event loop"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def app(tmp_path):
    """创建 FastAPI app 实例（临时文件 DB，避免 :memory: 连接隔离）"""
    import backend.db as db_mod
    from backend.config import config
    from backend.db import init_db

    db_file = str(tmp_path / "test_interview.db")
    market_file = str(tmp_path / "test_market.db")
    config.DB_PATH = db_file
    config.MARKET_DB_PATH = market_file
    db_mod._db = None
    from backend.market.store import init_market_db
    await init_db()
    await init_market_db()

    from backend.main import app
    yield app


@pytest_asyncio.fixture
async def client(app):
    """HTTP TestClient"""
    return TestClient(app)


@pytest.fixture
def sample_resume():
    return """张三
Python 开发工程师 | 3年经验 | 本科 · 计算机科学

技能: Python, Django, Flask, MySQL, Redis, Docker, Git

工作经历:
- XX科技 (2021-至今): 后端开发，负责电商平台 API 设计与实现
"""


@pytest.fixture
def sample_jd():
    return """高级 Python 开发工程师

岗位要求:
- 本科及以上，3-5 年后端开发经验
- 精通 Python, Django/Flask 框架
- 熟悉 MySQL/PostgreSQL，了解 Redis
- 有微服务架构经验优先
- 工作地点: 北京
- 薪资: 20K-35K
"""


@pytest.fixture
def sample_gap_llm_output():
    """模拟 LLM 返回的 Gap 分析 JSON"""
    return {
        "skills": {"score": 4, "evidence": "Python/Django 匹配", "gap": "缺少微服务经验", "suggestion": "学习 Docker/K8S"},
        "location": {"score": 5, "evidence": "未指定城市", "gap": "", "suggestion": ""},
        "education": {"score": 5, "evidence": "本科·计算机科学", "gap": "", "suggestion": ""},
        "experience": {"score": 3, "evidence": "3年 vs 要求3-5年", "gap": "年限偏低", "suggestion": "突出项目影响力"},
        "salary": {"score": 4, "evidence": "未提薪资预期", "gap": "", "suggestion": "参考市场25-30K范围"},
        "credibility": {"score": 5, "evidence": "信息一致", "gap": "", "suggestion": ""},
        "overall_assessment": "候选人基本匹配",
        "risk_level": "中",
    }
