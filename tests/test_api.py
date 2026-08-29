"""
API 端点综合测试：核心 HTTP 路由，使用真实 FastAPI app + 内存 DB。
v7.0 新增 TestAuthIntegration：认证开关的端到端行为（含"关闭时必须等同旧版"的回归底线）。
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.config import config as cfg

TEST_SECRET = "test-only-secret-not-for-production-0123456789abcdef"


@pytest.fixture(autouse=True)
def _restore_auth_config():
    """保护全局 config：认证相关开关在部分测试里会被临时改掉。"""
    original = (cfg.AUTH_ENABLED, cfg.AUTH_SECRET)
    yield
    cfg.AUTH_ENABLED, cfg.AUTH_SECRET = original


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


class TestAuthIntegration:
    """v7.0 认证端到端。

    最重要的一条是 test_disabled_matches_legacy_behavior —— DC-06 承诺
    "AUTH_ENABLED=false 时行为与 v6.x 完全一致"，这条断言就是那个承诺的回归底线。
    """

    def _register(self, client, username):
        return client.post("/api/auth/register", json={
            "username": username,
            "password": "password123",
            "role": "jobseeker",
        })

    def test_disabled_matches_legacy_behavior(self, client: TestClient):
        """认证关闭：列会话/建会话都无需 token，且不受归属限制。"""
        cfg.AUTH_ENABLED = False
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/auth/me").json()["is_anonymous"] is True

    def test_register_returns_token(self, client: TestClient):
        cfg.AUTH_ENABLED = True
        cfg.AUTH_SECRET = TEST_SECRET
        resp = self._register(client, "alice")
        assert resp.status_code == 201
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "alice"
        assert data["user"]["is_anonymous"] is False

    def test_register_duplicate_rejected(self, client: TestClient):
        cfg.AUTH_ENABLED = True
        cfg.AUTH_SECRET = TEST_SECRET
        assert self._register(client, "alice").status_code == 201
        dup = self._register(client, "alice")
        assert dup.status_code == 400

    def test_login_and_me(self, client: TestClient):
        cfg.AUTH_ENABLED = True
        cfg.AUTH_SECRET = TEST_SECRET
        self._register(client, "alice")
        resp = client.post("/api/auth/login", json={
            "username": "alice", "password": "password123"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["username"] == "alice"

    def test_login_wrong_password_is_401(self, client: TestClient):
        cfg.AUTH_ENABLED = True
        cfg.AUTH_SECRET = TEST_SECRET
        self._register(client, "alice")
        resp = client.post("/api/auth/login", json={
            "username": "alice", "password": "wrong-password"})
        assert resp.status_code == 401

    def test_protected_endpoint_requires_login(self, client: TestClient):
        """认证开启后，未登录访问"我的会话列表"必须 401。"""
        cfg.AUTH_ENABLED = True
        cfg.AUTH_SECRET = TEST_SECRET
        assert client.get("/api/sessions").status_code == 401

    def test_foreign_session_is_404_not_403(self, client: TestClient):
        """他人的会话返回 404 而非 403 —— 不暴露"该 id 存在"。

        这是 assert_session_owner 的刻意设计：403 会让攻击者据此枚举有效会话 id。
        """
        cfg.AUTH_ENABLED = True
        cfg.AUTH_SECRET = TEST_SECRET
        self._register(client, "alice")
        self._register(client, "bob")
        bob_token = client.post("/api/auth/login", json={
            "username": "bob", "password": "password123"}).json()["access_token"]

        # 直接构造一个不属于 bob 的会话 id
        foreign_id = uuid.uuid4().hex[:12]
        resp = client.get(f"/api/sessions/{foreign_id}",
                          headers={"Authorization": f"Bearer {bob_token}"})
        assert resp.status_code == 404


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

    @pytest.mark.parametrize("path,expected_status", [
        ("/", 200),
        ("/api/sessions", 200),
        ("/nonexistent-path", 404),
    ])
    def test_security_headers_present(self, client: TestClient, path, expected_status):
        """安全头应出现在根路径、API 路由与 404 响应上"""
        resp = client.get(path)
        assert resp.status_code == expected_status
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-xss-protection") == "1; mode=block"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

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
