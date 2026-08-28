"""
v6.3 长期记忆闭环测试（借鉴 HakiMeet 的长期记忆机制，扩展现有 weakness-profile）。

重点验收三件事：
1. **迁移幂等**：老库（无 resolved/updated_at 列）升级后接口可用，且 init_db 可重复执行；
   CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，这是本项目必须独立做迁移的原因。
2. **闭环语义**：标记 resolved 后即退出"未解决"查询口径（回注入 / 建议 / 图谱共用）。
3. **会话侧回注入**：只在首轮注入历史薄弱点，且数据为空时降级不抛异常。
"""

import uuid

import pytest
import pytest_asyncio

from backend.config import config as cfg  # Config 实例
from backend.db import (
    get_db,
    get_global_weakness_profile,
    get_weakness_profile,
    init_db,
    delete_weakness,
    list_unresolved_weaknesses,
    list_weakness_points,
    mark_weakness_resolved,
    save_weakness_profile,
)
from backend.interview_engine.session import InterviewSession

SESSION_A = "sess-memory-a"
SESSION_B = "sess-memory-b"


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path):
    original = cfg.DB_PATH
    cfg.DB_PATH = str(tmp_path / f"t{uuid.uuid4().hex}.db")
    await init_db()
    yield
    cfg.DB_PATH = original


async def _seed():
    """三个薄弱点：两未解决一已解决，覆盖排序与过滤。

    weakness_profile.session_id 有外键指向 sessions(id)，
    因此必须先落会话记录，否则 INSERT 会直接被 FOREIGN KEY 约束拒绝
    （该约束在生产链路天然满足——会话一定先于薄弱点被创建）。
    """
    await _ensure_sessions()
    await save_weakness_profile(SESSION_A, "逻辑连贯性", 3.0, 0.25, ["缺少因果链条"])
    await save_weakness_profile(SESSION_B, "量化程度", 2.0, 0.30, ["没有数据支撑"])
    await save_weakness_profile(SESSION_B, "专业深度", 4.5, 0.20, ["回答偏表面"])
    await mark_weakness_resolved(3, True)


async def _ensure_sessions():
    """补齐外键父记录（sessions），并启用外键约束使其真正生效。"""
    db = await get_db()
    try:
        await db.execute("PRAGMA foreign_keys = ON")
        for sid in (SESSION_A, SESSION_B):
            await db.execute(
                "INSERT OR IGNORE INTO sessions (id) VALUES (?)", (sid,)
            )
        await db.commit()
    finally:
        await db.close()


class TestMigration:
    pytestmark = pytest.mark.asyncio

    async def test_new_db_has_resolved_columns(self):
        db = await get_db()
        try:
            async with db.execute("PRAGMA table_info(weakness_profile)") as cur:
                cols = {row[1] for row in await cur.fetchall()}
        finally:
            await db.close()
        assert {"resolved", "updated_at"} <= cols

    async def test_init_db_is_repeatable(self):
        """init_db 每次启动都会跑，迁移不能第二次执行就炸。"""
        await init_db()
        await init_db()
        assert await list_weakness_points() == []

    async def test_legacy_db_upgraded_in_place(self, tmp_path):
        """模拟老库：手工建一张没有 resolved/updated_at 的旧表，再跑 init_db。"""
        legacy = str(tmp_path / f"legacy{uuid.uuid4().hex}.db")
        original = cfg.DB_PATH
        cfg.DB_PATH = legacy
        try:
            db = await get_db()
            await db.execute("""
                CREATE TABLE IF NOT EXISTS weakness_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    avg_score REAL NOT NULL,
                    weight REAL NOT NULL,
                    risk_points TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            await db.execute(
                "INSERT INTO weakness_profile (session_id, dimension, avg_score, weight)"
                " VALUES (?, ?, ?, ?)",
                ("legacy-sess", "STAR完整度", 2.5, 0.2),
            )
            await db.commit()
            await db.close()

            # 关键：升级前查询会因缺列而失败，升级后必须可用
            await init_db()
            points = await list_weakness_points()
            assert len(points) == 1
            assert points[0]["resolved"] == 0
        finally:
            cfg.DB_PATH = original


class TestClosedLoop:
    pytestmark = pytest.mark.asyncio

    async def test_unresolved_is_default_view(self):
        await _seed()
        points = await list_weakness_points()
        assert [p["dimension"] for p in points] == ["量化程度", "逻辑连贯性", "专业深度"][:2]

    async def test_include_resolved_returns_all(self):
        await _seed()
        assert len(await list_weakness_points(include_resolved=True)) == 3
        assert len(await list_weakness_points(include_resolved=False)) == 2

    async def test_mark_resolved_removes_from_unresolved(self):
        await _seed()
        target = (await list_weakness_points())[0]
        assert await mark_weakness_resolved(target["id"], True) is True
        remaining = {p["id"] for p in await list_weakness_points()}
        assert target["id"] not in remaining

    async def test_can_revert_to_unresolved(self):
        await _seed()
        target = (await list_weakness_points())[0]
        await mark_weakness_resolved(target["id"], True)
        await mark_weakness_resolved(target["id"], False)
        assert target["id"] in {p["id"] for p in await list_weakness_points()}

    async def test_mark_missing_id_returns_false(self):
        assert await mark_weakness_resolved(999999, True) is False

    async def test_delete_weakness(self):
        await _seed()
        target = (await list_weakness_points())[0]
        assert await delete_weakness(target["id"]) is True
        assert len(await list_weakness_points(include_resolved=True)) == 2
        assert await delete_weakness(target["id"]) is False

    async def test_limit_is_respected(self):
        await _seed()
        assert len(await list_unresolved_weaknesses(limit=1)) == 1

    async def test_risk_points_are_parsed_from_json(self):
        await _seed()
        point = (await list_weakness_points())[0]
        assert point["risk_points"] == ["没有数据支撑"]

    async def test_global_profile_reports_open_count(self):
        await _seed()
        rows = {r["dimension"]: r for r in await get_global_weakness_profile()}
        assert rows["量化程度"]["open_count"] == 1
        assert rows["专业深度"]["open_count"] == 0

    async def test_session_profile_carries_resolved_flag(self):
        await _seed()
        rows = await get_weakness_profile(SESSION_B)
        by_dim = {r["dimension"]: r for r in rows}
        assert by_dim["专业深度"]["resolved"] == 1
        assert by_dim["量化程度"]["resolved"] == 0


class TestSessionReinjection:
    """会话侧：历史薄弱点回注入（只在首轮，数据为空时静默降级）。"""

    def _session(self) -> InterviewSession:
        return InterviewSession(
            session_id="sess-reinject",
            resume_text="3 年 Python 开发经验",
            jd_text="招聘 Python 后端工程师",
            llm_client=None,
            diagnosis_engine=None,
        )

    def test_empty_by_default(self):
        s = self._session()
        assert s.long_term_memory == []
        assert s.long_term_memory_for_prompt() == []

    def test_injected_only_in_first_round(self):
        """一场会话内薄弱点不变，后续轮次再注入是纯粹的 token 浪费。"""
        s = self._session()
        s.set_long_term_memory([{"dimension": "量化程度", "avg_score": 2.0}])
        assert len(s.long_term_memory_for_prompt()) == 1
        s.current_round = 1
        assert s.long_term_memory_for_prompt() == []

    def test_non_dict_entries_filtered_out(self):
        s = self._session()
        s.set_long_term_memory([None, "bad", {"dimension": "逻辑连贯性"}])
        assert len(s.long_term_memory) == 1

    def test_none_input_degrades_silently(self):
        """拉取失败传 None 时不得抛异常——降级为无历史记忆模式。"""
        s = self._session()
        s.set_long_term_memory(None)
        assert s.long_term_memory == []
