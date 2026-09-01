"""
[v8.2] 市场岗位导入岗位库的持久化语义（backend/db.py + backend/routers/market.py）。

钉住四条最容易悄悄回归的语义：

1. **物化而非引用**：JD 文本被复制进面试库的 positions 表，不依赖 market.db
   那条记录仍在。两库物理分离（市场是可再采集的公共缓存，岗位库是用户私有
   资产，生命周期不同），跨库无法 JOIN，只能物化。
2. **来源可辨**：导入的岗位 source='market' 且带 market_job_id；手工新建的
   source='manual'。前端据此渲染不同徽标，这是"两类岗位分开"的数据依据。
3. **幂等**：同一市场岗位重复导入不产生第二条——否则用户多点几次，
   岗位库就被同一份 JD 刷屏。
4. **溯源**：JD 文本末尾附原文链接，便于回看 51job 原页面。

迁移另测：老库（无这两列）经 init_db 后必须自动补齐，
否则新列查询直接报 "no such column"。
"""
import uuid

import pytest
import pytest_asyncio

from backend.config import config as cfg
from backend.db import (
    find_position_by_market_job, get_position, init_db, list_positions, save_position,
)
from backend.market import store


@pytest_asyncio.fixture(autouse=True)
async def dbs(tmp_path):
    """每个用例独享临时主库 + 临时市场库，与真实数据物理隔离。"""
    original_db, original_market = cfg.DB_PATH, cfg.MARKET_DB_PATH
    cfg.DB_PATH = str(tmp_path / f"p{uuid.uuid4().hex}.db")
    cfg.MARKET_DB_PATH = str(tmp_path / f"m{uuid.uuid4().hex}.db")
    await init_db()
    await store.init_market_db()
    yield
    cfg.DB_PATH, cfg.MARKET_DB_PATH = original_db, original_market


def _job(source_id: str, **over) -> dict:
    job = {
        "source": "51job", "source_id": source_id, "keyword": "Python",
        "title": "Python 开发工程师", "company": "某某科技", "city": "北京",
        "salary_raw": "20-35K", "salary_min": 20.0, "salary_max": 35.0,
        "exp_min": 3.0, "exp_max": 5.0, "education": "本科",
        "tags": ["Python", "Django"], "description": "负责后端服务开发",
        "url": f"https://example.com/{source_id}",
    }
    job.update(over)
    return job


class TestPositionSource:
    """来源字段的读写语义。"""

    @pytest.mark.asyncio
    async def test_manual_is_default(self):
        await save_position("p1", title="手工岗位", jd_text="JD 原文")
        p = await get_position("p1")
        assert p["source"] == "manual"
        assert p["market_job_id"] is None

    @pytest.mark.asyncio
    async def test_market_source_roundtrip(self):
        await save_position("p2", title="市场岗位", jd_text="JD 原文",
                            source="market", market_job_id=42)
        p = await get_position("p2")
        assert p["source"] == "market"
        assert p["market_job_id"] == 42

    @pytest.mark.asyncio
    async def test_list_query_exposes_source(self):
        """列表查询必须带来源字段——前端徽标全靠它，漏了就两类岗位长得一样。"""
        await save_position("p3", title="市场岗位", jd_text="JD 原文",
                            source="market", market_job_id=9)
        rows = await list_positions()
        assert len(rows) == 1
        assert rows[0]["source"] == "market"
        assert rows[0]["market_job_id"] == 9


class TestFindByMarketJob:
    """幂等判断的查询语义。"""

    @pytest.mark.asyncio
    async def test_hit_when_job_exists(self):
        """同一市场岗位重复导入时能查到已存在的记录——幂等判断的核心。"""
        await save_position("p4", title="X", jd_text="JD",
                            source="market", market_job_id=7)
        hit = await find_position_by_market_job(7)
        assert hit is not None and hit["id"] == "p4"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        assert await find_position_by_market_job(404) is None


class TestLegacyMigration:
    """老库升级：无新列的表经 init_db 后应自动补齐。"""

    @pytest.mark.asyncio
    async def test_columns_added_to_existing_table(self, tmp_path):
        import aiosqlite

        path = str(tmp_path / f"legacy{uuid.uuid4().hex}.db")
        cfg.DB_PATH = path
        # 造一张"升级前"的 positions 表（无 source / market_job_id）
        async with aiosqlite.connect(path) as conn:
            await conn.execute("""
                CREATE TABLE positions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT,
                    title TEXT NOT NULL,
                    department TEXT,
                    jd_text TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                )""")
            await conn.commit()

        await init_db()   # 迁移发生在 init 内

        async with aiosqlite.connect(path) as conn:
            async with conn.execute("PRAGMA table_info(positions)") as cur:
                cols = {row[1] for row in await cur.fetchall()}
        assert "source" in cols, "老库未补上 source 列"
        assert "market_job_id" in cols, "老库未补上 market_job_id 列"


class TestToPositionAPI:
    """端点行为：物化内容、幂等、404。"""

    @staticmethod
    def _seed_job() -> int:
        """写入一条市场岗位并返回其 id（调用方需 await）。"""
        return store.upsert_jobs([_job("s1")])

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient

        from backend.main import app

        return TestClient(app)

    @pytest.mark.asyncio
    async def test_import_creates_market_position(self):
        await self._seed_job()
        job_id = (await store.query_jobs())["items"][0]["id"]

        with self._client() as c:
            r = c.post(f"/api/market/jobs/{job_id}/to-position")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] is True
        pos = body["position"]
        assert pos["source"] == "market"
        assert pos["market_job_id"] == job_id
        # 物化：JD 文本已落地面试库，且带上原文链接便于溯源
        assert "Python 开发工程师" in pos["jd_text"]
        assert "https://example.com/s1" in pos["jd_text"]

    @pytest.mark.asyncio
    async def test_repeat_import_keeps_single_row(self):
        """重复导入不产生第二条——否则多点几次岗位库就被同一份 JD 刷屏。"""
        await self._seed_job()
        job_id = (await store.query_jobs())["items"][0]["id"]

        with self._client() as c:
            first = c.post(f"/api/market/jobs/{job_id}/to-position")
            second = c.post(f"/api/market/jobs/{job_id}/to-position")
            c.post(f"/api/market/jobs/{job_id}/to-position")

        assert first.json()["created"] is True
        assert second.json()["created"] is False
        rows = await list_positions()
        assert len(rows) == 1, f"重复导入产生了 {len(rows)} 条记录"

    @pytest.mark.asyncio
    async def test_missing_job_returns_404(self):
        await self._seed_job()   # 库非空，确保 404 是"找不到"而非"空库"

        with self._client() as c:
            r = c.post("/api/market/jobs/999999/to-position")

        assert r.status_code == 404
