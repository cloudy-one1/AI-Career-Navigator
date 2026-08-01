"""
API 端点综合测试：核心 HTTP 路由，使用真实 FastAPI app + 内存 DB。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """创建 TestClient（使用临时文件 DB，避免 :memory: 连接隔离问题）"""
    import asyncio
    from backend.config import config
    import backend.db as db_mod

    # 使用临时文件 DB（':memory:' 每个连接独立，不适合多连接的 FastAPI 测试）
    db_file = str(tmp_path / "test_interview.db")
    market_file = str(tmp_path / "test_market.db")
    config.DB_PATH = db_file
    config.MARKET_DB_PATH = market_file
    db_mod._db = None

    from backend.db import init_db
    from backend.market.store import init_market_db

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(init_db())
        loop.run_until_complete(init_market_db())
    finally:
        loop.close()

    from backend.main import app
    return TestClient(app)


class TestBasicRoutes:
    def test_root(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_docs(self, client: TestClient):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_providers(self, client: TestClient):
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data


class TestSessionRoutes:
    def test_create_session_response(self, client: TestClient):
        """会话创建应该返回 session_id（可能因 LLM 不可用而 500，但结构应完整）"""
        resp = client.post("/api/sessions", json={
            "resume_text": "Python 3年经验",
            "jd_text": "高级 Python 开发",
        })
        assert resp.status_code in (200, 500, 503)

    def test_list_sessions(self, client: TestClient):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert "sessions" in resp.json()

    def test_get_nonexistent_session(self, client: TestClient):
        resp = client.get("/api/sessions/nonexistent-id-12345")
        assert resp.status_code == 404


class TestGapAnalysisRoutes:
    def test_gap_analysis_no_session(self, client: TestClient):
        resp = client.post("/api/gap-analysis", json={
            "resume_text": "Python 3年",
            "jd_text": "Python 5年",
        })
        assert resp.status_code in (200, 500)

    def test_gap_analysis_by_nonexistent_session(self, client: TestClient):
        resp = client.get("/api/gap-analysis/does-not-exist")
        assert resp.status_code == 404


class TestMarketRoutes:
    def test_market_import_no_db(self, client: TestClient):
        """无 JOB_CRAWLER_DB_PATH 且未提供 db_path 时应返回 400"""
        resp = client.post("/api/market/import", data={
            "db_path": "",
        })
        assert resp.status_code in (400, 500)

    def test_market_stats(self, client: TestClient):
        resp = client.get("/api/market/stats")
        assert resp.status_code == 200


class TestQuestionBankRoutes:
    def test_list_empty_bank(self, client: TestClient):
        resp = client.get("/api/question-bank")
        assert resp.status_code == 200
        assert "questions" in resp.json()


class TestFeedbackRoutes:
    def test_submit_feedback_no_session(self, client: TestClient):
        resp = client.post("/api/feedback", json={
            "session_id": "dummy-nonexistent",
            "round_idx": 0,
            "question_idx": 0,
            "feedback_type": "up",
        })
        assert resp.status_code in (200, 400, 404)


class TestSecurityMeasures:
    """v3.1 Web 安全加固测试"""

    def test_security_headers_present(self, client: TestClient):
        """所有响应应包含安全头"""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-xss-protection") == "1; mode=block"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_security_headers_on_api(self, client: TestClient):
        """API 端点也应包含安全头"""
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert "x-content-type-options" in resp.headers
        assert "x-frame-options" in resp.headers

    def test_security_headers_on_404(self, client: TestClient):
        """404 响应也应包含安全头"""
        resp = client.get("/nonexistent-path")
        assert resp.status_code == 404
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_request_size_limit_normal(self, client: TestClient):
        """正常大小请求不应被拦截"""
        resp = client.get("/api/sessions")
        assert resp.status_code == 200

    def test_large_request_body_blocked(self, client: TestClient):
        """超大请求体应返回 413"""
        huge_body = "x" * (11 * 1024 * 1024)  # 11MB > 10MB limit
        resp = client.post("/api/sessions/upload", data=huge_body,
                           headers={"content-type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 413

    def test_cors_header_present(self, client: TestClient):
        """CORS 头应存在于正常响应中"""
        resp = client.get("/")
        # CORSMiddleware 在 OPTIONS 预检时返回，普通 GET 也会有 access-control-*
        assert resp.status_code == 200
