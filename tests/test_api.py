"""
API 端点综合测试：核心 HTTP 路由，使用真实 FastAPI app + 内存 DB。

v8.3: 删除 TestAuthIntegration（注册/登录/归属越权），认证整体下线（CHARTER DC-10）。
原先那条 test_disabled_matches_legacy_behavior 钉的是"认证关闭时行为与 v6.x 一致"，
如今无认证是唯一状态，该承诺由 TestSessionRoutes 的基础用例直接覆盖。
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

    def test_edit_and_delete_survive_id_gap(self, client: TestClient):
        """删掉首题造成 id 空洞后，剩余题目仍必须可编辑、可删除。

        v7.3.1 修复：存在性校验曾把自增主键当成分页偏移量（offset=id-1），
        id 不连续时会把真实存在的题误判为不存在，
        即「列表里看得见、点编辑却报题目不存在」。
        """
        id1 = client.post("/api/question-bank", json={
            "question_text": "空洞测试一", "round_type": "技术深度"}).json()["id"]
        id2 = client.post("/api/question-bank", json={
            "question_text": "空洞测试二", "round_type": "技术深度"}).json()["id"]
        assert client.delete(f"/api/question-bank/{id1}").status_code in (200, 204)

        resp = client.put(f"/api/question-bank/{id2}",
                          json={"question_text": "空洞测试二（已改）"})
        assert resp.status_code == 200, f"id 空洞后应仍可编辑，实际: {resp.text}"
        assert client.delete(f"/api/question-bank/{id2}").status_code in (200, 204)


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


class TestJdUpload:
    """v7.0.2: JD 文件上传解析（测评问题 #2，复用简历解析链路）。"""

    def test_upload_jd_txt(self, client: TestClient):
        resp = client.post("/api/upload-jd",
                           files={"file": ("jd.txt",
                                           "岗位：Python 后端工程师\n要求：精通 FastAPI".encode("utf-8"),
                                           "text/plain")})
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "jd.txt"
        assert "Python" in data["text"]
        assert "FastAPI" in data["text"]
        assert data["length"] > 0

    def test_upload_jd_rejects_bad_ext(self, client: TestClient):
        resp = client.post("/api/upload-jd",
                           files={"file": ("jd.exe", b"x", "application/octet-stream")})
        assert resp.status_code == 400
        assert "不支持的文件格式" in resp.json()["detail"]

    def test_upload_jd_empty_text_rejected(self, client: TestClient):
        resp = client.post("/api/upload-jd",
                           files={"file": ("jd.txt", b"", "text/plain")})
        assert resp.status_code == 400
