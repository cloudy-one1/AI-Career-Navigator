"""
db.py 测试：覆盖会话 / QA / 报告 / 题库 CRUD / 反馈 / 薄弱点 / JD 权重缓存。
每个测试使用独立临时库，互不干扰，也不会触碰真实 data/interview.db。

注意：backend.config 里导出的是 Config 实例 `config = Config()`；
`from backend import config` 拿到的是模块本身，二者不是同一对象。
必须通过实例设置 DB_PATH，否则 get_db() 仍会连接真实库。
"""

import json
import uuid

import pytest
import pytest_asyncio

from backend.config import config as cfg  # Config 实例
from backend.db import (
    add_question,
    delete_question,
    get_db,
    get_feedback_stats,
    get_global_weakness_profile,
    get_report,
    get_session,
    get_session_feedback,
    get_session_qas,
    get_weakness_profile,
    import_questions_from_session,
    increment_usage,
    init_db,
    list_questions,
    list_sessions,
    lookup_jd_weights,
    save_feedback,
    save_jd_weights,
    save_qa,
    save_report,
    save_session,
    save_weakness_profile,
    toggle_favorite,
    update_question,
    update_session_status,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path):
    original = cfg.DB_PATH
    cfg.DB_PATH = str(tmp_path / f"t{uuid.uuid4().hex}.db")
    await init_db()
    yield
    cfg.DB_PATH = original


class TestSessions:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        await save_session("s1", "friendly", "", "JD", "RESUME")
        row = await get_session("s1")
        assert row is not None
        assert row["style"] == "friendly"
        assert row["jd_text"] == "JD"
        assert row["resume_text"] == "RESUME"
        assert row["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        assert await get_session("nope") is None

    @pytest.mark.asyncio
    async def test_update_status(self):
        await save_session("s2", "friendly", "", "JD", "RE")
        await update_session_status("s2", "completed")
        assert (await get_session("s2"))["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list(self):
        await save_session("a", "friendly", "", "JD", "RE")
        await save_session("b", "friendly", "", "JD", "RE")
        ids = {r["id"] for r in await list_sessions()}
        assert {"a", "b"} <= ids


class TestQA:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        await save_session("s3", "friendly", "", "JD", "RE")
        await save_qa("s3", 1, "Q text", "A text", {"overall_score": 4})
        qas = await get_session_qas("s3")
        assert len(qas) == 1
        assert qas[0]["question"] == "Q text"
        assert json.loads(qas[0]["diagnosis_json"])["overall_score"] == 4


class TestReports:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        await save_session("s4", "friendly", "", "JD", "RE")
        await save_report("s4", {"summary": "good"})
        rep = await get_report("s4")
        assert rep is not None
        assert json.loads(rep["report_json"])["summary"] == "good"


class TestQuestionBank:
    @pytest.mark.asyncio
    async def test_crud(self):
        qid = await add_question("python题", "技术", "intent1", ["py"], 2, "manual", "")
        assert isinstance(qid, int)
        await update_question(qid, question_text="新题", difficulty=3)
        qs = [q for q in await list_questions() if q["id"] == qid]
        assert qs[0]["question_text"] == "新题"
        assert qs[0]["difficulty"] == 3
        # 收藏
        assert await toggle_favorite(qid) is True
        qs2 = [q for q in await list_questions() if q["id"] == qid]
        assert qs2[0]["is_favorited"] is True
        # 使用计数
        await increment_usage(qid)
        qs3 = [q for q in await list_questions() if q["id"] == qid]
        assert qs3[0]["usage_count"] == 1
        # 删除
        assert await delete_question(qid) is True
        assert [q for q in await list_questions() if q["id"] == qid] == []

    @pytest.mark.asyncio
    async def test_update_question_whitelist(self):
        qid = await add_question("白名单题", "技术", "", [], 2, "manual", "")
        # 非白名单字段应被忽略并返回 True（有合法更新时）
        assert await update_question(qid, usage_count=999) is False  # 无合法字段 -> False
        await update_question(qid, tags=["a", "b"])
        q = [q for q in await list_questions() if q["id"] == qid][0]
        assert q["tags"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_filters(self):
        await add_question("python专项", "技术", "", [], 2, "manual", "")
        await add_question("沟通题", "行为", "", [], 3, "ai_generated", "")
        assert len(await list_questions(round_type="行为")) == 1
        assert len(await list_questions(difficulty=2)) == 1
        assert len(await list_questions(source="manual")) == 1
        assert len(await list_questions(search="python")) == 1
        # 收藏过滤
        qid = await add_question("收藏题", "技术", "", [], 2, "manual", "")
        await toggle_favorite(qid)
        assert len(await list_questions(favorited=True)) == 1


class TestImportFromSession:
    @pytest.mark.asyncio
    async def test_import_and_dedup(self):
        await save_session("s5", "friendly", "", "JD", "RE")
        await save_qa("s5", 0, "Q1", "A1", {})
        await save_qa("s5", 1, "Q2", "A2", {})
        n = await import_questions_from_session("s5")
        assert n == 2
        imported = await list_questions(source="ai_generated")
        assert len(imported) == 2
        # 重复导入不应产生新记录
        n2 = await import_questions_from_session("s5")
        assert n2 == 0

    @pytest.mark.asyncio
    async def test_skips_follow_up_questions(self):
        await save_session("s8", "friendly", "", "JD", "RE")
        await save_qa("s8", 0, "正式问题", "A", {})
        await save_qa("s8", 0, "[追问] 深入一下", "B", {})
        n = await import_questions_from_session("s8")
        assert n == 1
        imported = await list_questions(source="ai_generated")
        assert imported[0]["question_text"] == "正式问题"


class TestFeedback:
    @pytest.mark.asyncio
    async def test_feedback_and_stats(self):
        await save_session("s6", "friendly", "", "JD", "RE")
        await save_feedback("s6", 0, 0, "up", "communication", "清晰", 4.0)
        await save_feedback("s6", 0, 1, "down", "technical_depth", "偏浅", 2.0)
        fbs = await get_session_feedback("s6")
        assert len(fbs) == 2
        stats = await get_feedback_stats("s6")
        assert stats["up"] == 1
        assert stats["down"] == 1
        assert stats["total"] == 2


class TestWeakness:
    @pytest.mark.asyncio
    async def test_profile(self):
        await save_session("s7", "friendly", "", "JD", "RE")
        await save_weakness_profile("s7", "communication", 0.3, 0.7, ["证据1"])
        prof = await get_weakness_profile("s7")
        assert len(prof) == 1
        assert prof[0]["dimension"] == "communication"
        assert prof[0]["risk_points"] == ["证据1"]
        global_prof = await get_global_weakness_profile()
        assert isinstance(global_prof, list)
        assert global_prof[0]["dimension"] == "communication"


class TestJdWeightsCache:
    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        assert await lookup_jd_weights("missing") is None

    @pytest.mark.asyncio
    async def test_save_then_lookup(self):
        payload = {"weights": {"technical_depth": 0.5, "communication": 0.5},
                   "reason": "r", "source": "llm"}
        await save_jd_weights("hash1", "preview text", payload)
        res = await lookup_jd_weights("hash1")
        assert res is not None
        assert res["source"] == "cache"
        assert res["weights"]["technical_depth"] == 0.5
        assert res["reason"] == "r"

    @pytest.mark.asyncio
    async def test_corrupted_row_returns_none(self):
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO jd_weights_cache (jd_hash, jd_preview, weights_json) VALUES (?, ?, ?)",
                ("bad", "", "not-json"),
            )
            await db.commit()
        finally:
            await db.close()
        assert await lookup_jd_weights("bad") is None
