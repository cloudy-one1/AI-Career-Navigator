"""
test_entities.py —— v7.0 简历库 / 岗位库（可复用输入资产）

覆盖：
1. CRUD 正常路径
2. 列表不返回大字段（raw_text 可能上万字符，N 条会把响应撑到几 MB）
3. 列表语义：无归属维度，返回全部（v8.3 认证下线，见 CHARTER DC-10）
4. 创建会话时关联 resume_id / position_id，且未传 id 时行为不变（向后兼容）
"""

import uuid

import pytest
import pytest_asyncio

from backend.config import config as cfg  # Config 实例
from backend.db import (
    delete_position,
    delete_resume,
    get_position,
    get_resume,
    init_db,
    list_positions,
    list_resumes,
    save_position,
    save_resume,
    update_position,
    update_resume,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path):
    original = cfg.DB_PATH
    cfg.DB_PATH = str(tmp_path / f"ent{uuid.uuid4().hex}.db")
    await init_db()
    yield
    cfg.DB_PATH = original


# ===== 1. 简历库 CRUD =====

class TestResumeCRUD:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        await save_resume("r1", "我的简历", "张三 Python 3年", filename="cv.pdf")
        row = await get_resume("r1")
        assert row is not None
        assert row["title"] == "我的简历"
        assert row["raw_text"] == "张三 Python 3年"
        assert row["filename"] == "cv.pdf"
        assert row["char_count"] == len("张三 Python 3年")

    @pytest.mark.asyncio
    async def test_list_excludes_raw_text(self):
        """列表不含 raw_text —— 这是性能约定，不是疏漏。"""
        await save_resume("r1", "简历A", "x" * 10000)
        rows = await list_resumes()
        assert len(rows) == 1
        assert "raw_text" not in rows[0]
        # 详情才有
        assert "raw_text" in await get_resume("r1")

    @pytest.mark.asyncio
    async def test_update_title_and_parsed(self):
        await save_resume("r1", "旧标题", "text")
        await update_resume("r1", title="新标题", parsed_json='{"skills":["Python"]}')
        row = await get_resume("r1")
        assert row["title"] == "新标题"
        assert row["parsed_json"] == '{"skills":["Python"]}'
        # 只传其中一个参数时不该把另一个清空
        await update_resume("r1", title="第三次改")
        assert (await get_resume("r1"))["parsed_json"] == '{"skills":["Python"]}'

    @pytest.mark.asyncio
    async def test_delete(self):
        await save_resume("r1", "t", "text")
        await delete_resume("r1")
        assert await get_resume("r1") is None


# ===== 2. 岗位库 CRUD =====

class TestPositionCRUD:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        await save_position("p1", "高级 Python", "JD 内容", department="技术部")
        row = await get_position("p1")
        assert row["title"] == "高级 Python"
        assert row["jd_text"] == "JD 内容"
        assert row["department"] == "技术部"

    @pytest.mark.asyncio
    async def test_update_partial(self):
        await save_position("p1", "旧岗位", "旧JD")
        await update_position("p1", jd_text="新JD")
        row = await get_position("p1")
        assert row["jd_text"] == "新JD"
        assert row["title"] == "旧岗位"   # 未传的字段不该被清掉

    @pytest.mark.asyncio
    async def test_update_with_nothing_is_noop(self):
        await save_position("p1", "岗位", "JD")
        await update_position("p1")       # 全空：不应报错，也不应改动
        assert (await get_position("p1"))["jd_text"] == "JD"

    @pytest.mark.asyncio
    async def test_delete(self):
        await save_position("p1", "t", "JD")
        await delete_position("p1")
        assert await get_position("p1") is None


# ===== 3. 列表语义 =====

class TestEntityListing:
    """v8.3: 本类原为「归属隔离」（A 看不到 B 的简历/岗位）。

    认证下线后不存在第二个使用者，"按 owner 过滤"这一语义连同它的参数一起消失。
    这里改为钉住剩下的唯一语义——列表返回全部、且只受 limit 约束，
    防止将来有人重新引入过滤条件却按旧的多用户前提理解它。
    """

    @pytest.mark.asyncio
    async def test_list_returns_everything(self):
        await save_resume("r1", "简历A", "t")
        await save_resume("r2", "简历B", "t")
        assert len(await list_resumes()) == 2

    @pytest.mark.asyncio
    async def test_list_positions_empty_by_default(self):
        await save_resume("r1", "简历A", "t")
        assert len(await list_positions()) == 0

    @pytest.mark.asyncio
    async def test_list_respects_limit(self):
        for i in range(5):
            await save_resume(f"r{i}", f"简历{i}", "t")
        assert len(await list_resumes(limit=2)) == 2


# ===== 4. HTTP 层：CRUD 与关联 =====

class TestEntityEndpoints:
    @pytest_asyncio.fixture
    async def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as c:
            yield c

    def test_list_is_open(self, client):
        """回归底线：列表端点无需任何凭据即可访问（v8.3 起无认证层）。"""
        assert client.get("/api/resumes").status_code == 200
        assert client.get("/api/positions").status_code == 200

    def test_crud_roundtrip(self, client):
        created = client.post("/api/resumes", json={
            "title": "测试简历", "raw_text": "张三 Python", "filename": "cv.pdf"})
        assert created.status_code == 201
        rid = created.json()["resume"]["id"]

        got = client.get(f"/api/resumes/{rid}")
        assert got.status_code == 200
        assert got.json()["resume"]["raw_text"] == "张三 Python"

        patched = client.patch(f"/api/resumes/{rid}", json={"title": "改名了"})
        assert patched.json()["resume"]["title"] == "改名了"

        assert client.delete(f"/api/resumes/{rid}").status_code == 200
        assert client.get(f"/api/resumes/{rid}").status_code == 404

    def test_missing_resource_is_404(self, client):
        assert client.get("/api/resumes/nope").status_code == 404
        assert client.get("/api/positions/nope").status_code == 404

    def test_position_crud_roundtrip(self, client):
        created = client.post("/api/positions", json={
            "title": "Python 工程师", "jd_text": "要求 3 年经验", "department": "技术"})
        assert created.status_code == 201
        pid = created.json()["position"]["id"]
        assert client.get(f"/api/positions/{pid}").status_code == 200
        assert client.delete(f"/api/positions/{pid}").status_code == 200


class TestUploadToLibrary:
    """上传入库必须保留完整文本。

    /api/sessions/upload 会把文本截断到 5000 字——那是历史兼容行为，改动会波及
    既有前端。但入库场景不能截断：截断是静默的，用户下次选用这份简历时看不到
    任何异常，LLM 看到的却是不完整的简历，出题质量下降且无从归因。
    """

    def test_upload_keeps_full_text(self, client):
        long_text = "张三 高级Python工程师 " + "负责订单系统重构与性能优化。" * 400  # 远超 5000 字
        files = {"file": ("cv.txt", long_text.encode("utf-8"), "text/plain")}
        resp = client.post("/api/resumes/upload", files=files)
        assert resp.status_code == 201
        rid = resp.json()["resume"]["id"]

        detail = client.get(f"/api/resumes/{rid}").json()["resume"]
        assert detail["char_count"] == len(long_text)
        assert len(detail["raw_text"]) > 5000          # 没被截断
        assert detail["title"] == "cv"                  # 默认用文件名去扩展名

    def test_upload_rejects_bad_extension(self, client):
        files = {"file": ("cv.exe", b"MZ\x00\x00", "application/octet-stream")}
        assert client.post("/api/resumes/upload", files=files).status_code == 400

    def test_legacy_upload_endpoint_still_truncates(self, client):
        """回归底线：旧端点行为不变（截断到 5000），既有前端依赖这个约定。"""
        long_text = "字" * 8000
        files = {"file": ("cv.txt", long_text.encode("utf-8"), "text/plain")}
        resp = client.post("/api/sessions/upload", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["text"]) == 5000
        assert data["length"] == 8000        # 真实长度仍然如实返回


class TestSessionUsesLibrary:
    """创建会话时引用库内简历/岗位 —— D2 的"冒烟：选库内简历开新会话"。"""

    def test_session_records_library_refs(self, client):
        rid = client.post("/api/resumes", json={
            "title": "库内简历", "raw_text": "张三 Python 3年 Django Redis"}).json()["resume"]["id"]
        pid = client.post("/api/positions", json={
            "title": "库内岗位", "jd_text": "要求 3 年 Python 经验"}).json()["position"]["id"]

        resp = client.post("/api/sessions", json={
            "resume_id": rid, "position_id": pid, "resume_text": "", "jd_text": "",
        })
        # 允许 500/503（无 LLM Key 时创建会话会失败），但绝不能是 404/403 ——
        # 那说明库引用被当成越权或不存在了。
        assert resp.status_code not in (403, 404), resp.text

    def test_session_rejects_missing_ref(self, client):
        resp = client.post("/api/sessions", json={
            "resume_id": "不存在的id", "resume_text": "", "jd_text": ""})
        assert resp.status_code == 404
