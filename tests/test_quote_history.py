"""引用可核率持久化（v8.14）。

v8.10 的进程内可核率随重启归零，而落库报告里根本没有 quote_verified——
"历史可核率从 dimension_details 离线汇总"在当时的报告形状下无从谈起。
v8.14 两步闭环：
  1. build_report 把每题 dimension_details（含 quote / quote_verified）落进
     qa_breakdown，报告 JSON 自携带验证结果；
  2. db.sessions.get_quote_verification_stats() 从报告反查全历史可核率，
     经 /api/health 的 quote_stats.all_time 暴露。

口径与 diagnosis_engine._verify_quote 一致：空 quote 不进分母。
"""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.config import config
from backend.db import (
    get_quote_verification_stats,
    init_db,
    save_report,
    save_session,
)
from backend.interview_engine.report import build_report

DIM_KEYS = ("star_completeness", "quantification", "logic_coherence",
            "job_relevance", "professional_depth")


# ==================== 1. build_report 持久化契约 ====================

def _fake_session(diagnoses):
    return SimpleNamespace(
        session_id="s1", mode="simulation", stage="phone_screen",
        style="friendly", interviewer_history=[],
        rounds=[], all_diagnoses=diagnoses,
        dim_weights=None, _weakness_counts={},
        resume_points={}, weight_reason="", weight_source="default",
    )


def _diag(details=None, question="介绍一下你的项目"):
    d = {
        "round": 0, "round_name": "项目拷问", "question": question,
        "overall_score": 4.0,
        "dimensions": {k: 4.0 for k in DIM_KEYS},
        "weakest_dimension": "quantification",
        "overall_comment": "整体不错",
        "thinking_seconds": 12.0,
        "risk_points": [], "rewritten_answer": "改写后的回答",
    }
    if details is not None:
        d["dimension_details"] = details
    return d


class TestBuildReportPersistsDimensionDetails:
    def test_details_land_in_qa_breakdown(self):
        """诊断里的五维明细（含 quote_verified）必须进落库报告。"""
        details = {
            "quantification": {"score": 4.0, "comment": "有数据",
                               "quote": "把响应时间从 800ms 降到 200ms",
                               "quote_verified": True},
            "job_relevance": {"score": 3.0, "comment": "偏题",
                              "quote": "模型编造的原话",
                              "quote_verified": False},
        }
        report = build_report(_fake_session([_diag(details=details)]))
        qa = report["qa_breakdown"][0]
        assert qa["dimension_details"]["quantification"]["quote_verified"] is True
        assert qa["dimension_details"]["job_relevance"]["quote_verified"] is False

    def test_missing_details_degrade_to_empty_dict(self):
        """无明细（mock session / 老诊断）退化为空 dict，不崩不编造。"""
        report = build_report(_fake_session([_diag()]))
        assert report["qa_breakdown"][0]["dimension_details"] == {}


# ==================== 2. 全历史聚合口径 ====================

@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    original = (config.DB_PATH, config.MARKET_DB_PATH)
    config.DB_PATH = str(tmp_path / "quote_hist.db")
    config.MARKET_DB_PATH = str(tmp_path / "quote_hist_market.db")
    await init_db()
    yield
    config.DB_PATH, config.MARKET_DB_PATH = original


def _report(qa_items):
    return {"qa_breakdown": qa_items}


def _qa_item(details):
    return {"question": "Q", "dimension_details": details}


@pytest.mark.asyncio
async def test_aggregate_counts_only_nonempty_quotes(fresh_db):
    """口径：非空 quote 才进分母；quote_verified=True 才进分子；老报告不进。"""
    await save_session("sess-a")
    await save_report("sess-a", _report([
        # cited=1 verified=1（空 quote 不计入）
        _qa_item({"quantification": {"quote": "真话", "quote_verified": True},
                  "logic_coherence": {"quote": "", "quote_verified": True}}),
        # cited=1 verified=0
        _qa_item({"job_relevance": {"quote": "编造", "quote_verified": False}}),
    ]))
    await save_session("sess-b")
    await save_report("sess-b", _report([
        _qa_item({"quantification": {"quote": "又是真话", "quote_verified": True}}),
    ]))
    # 老报告（v8.14 前形状）：没有 qa_breakdown，不能给新口径充数
    await save_session("sess-old")
    await save_report("sess-old", {"overall_avg": 3.5})

    stats = await get_quote_verification_stats()
    assert stats["reports_scanned"] == 3
    assert stats["reports_with_quote_data"] == 2
    assert stats["cited"] == 3
    assert stats["verified"] == 2
    assert stats["verify_rate"] == round(2 / 3, 4)
    assert stats["parse_errors"] == 0


@pytest.mark.asyncio
async def test_aggregate_reflects_data_change(fresh_db):
    """证伪锚点：把一条 quote_verified 翻转，统计必须跟着动（不是写死的假绿）。"""
    report = _report([
        _qa_item({"quantification": {"quote": "真话", "quote_verified": True}}),
    ])
    await save_session("sess-flip")
    await save_report("sess-flip", report)
    assert (await get_quote_verification_stats())["verified"] == 1

    report["qa_breakdown"][0]["dimension_details"]["quantification"]["quote_verified"] = False
    await save_report("sess-flip", report)  # INSERT OR REPLACE 覆盖同键
    stats = await get_quote_verification_stats()
    assert stats["verified"] == 0
    assert stats["verify_rate"] == 0.0


@pytest.mark.asyncio
async def test_aggregate_survives_corrupt_report_json(fresh_db):
    """坏 JSON 计入 parse_errors 并跳过，不中断整批（与市场聚合脏行口径一致）。"""
    await save_session("sess-ok")
    await save_report("sess-ok", _report([
        _qa_item({"quantification": {"quote": "真话", "quote_verified": True}}),
    ]))
    from backend.db.connection import get_db
    await save_session("sess-bad")  # reports 对 sessions 有外键，坏行也要先建会话
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO reports (session_id, report_json) VALUES (?, ?)",
            ("sess-bad", "{not-a-json"))
        await db.commit()
    finally:
        await db.close()

    stats = await get_quote_verification_stats()
    assert stats["reports_scanned"] == 2
    assert stats["parse_errors"] == 1
    assert stats["cited"] == 1 and stats["verified"] == 1


@pytest.mark.asyncio
async def test_aggregate_empty_db(fresh_db):
    stats = await get_quote_verification_stats()
    assert stats["reports_scanned"] == 0
    assert stats["cited"] == 0
    assert stats["verify_rate"] is None


# ==================== 3. /api/health 集成 ====================

def _client_with_db(tmp_path):
    original = (config.DB_PATH, config.MARKET_DB_PATH)
    config.DB_PATH = str(tmp_path / "health_q.db")
    config.MARKET_DB_PATH = str(tmp_path / "health_q_market.db")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(init_db())
    finally:
        loop.close()
    from backend.main import app
    try:
        yield TestClient(app)
    finally:
        config.DB_PATH, config.MARKET_DB_PATH = original


class TestHealthQuoteStatsAllTime:
    @pytest.fixture()
    def client(self, tmp_path):
        yield from _client_with_db(tmp_path)

    def test_health_carries_all_time_block(self, client, tmp_path):
        """health 的 quote_stats 必须并列两个口径：进程内 + all_time。"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(save_session("sess-h"))
            loop.run_until_complete(save_report("sess-h", _report([
                _qa_item({"quantification": {"quote": "真话", "quote_verified": True},
                          "job_relevance": {"quote": "编造", "quote_verified": False}}),
            ])))
        finally:
            loop.close()

        resp = client.get("/api/health")
        assert resp.status_code == 200
        qs = resp.json()["quote_stats"]
        assert {"cited", "verified", "verify_rate"} <= set(qs)     # 进程内（v8.10）
        all_time = qs["all_time"]
        assert all_time["reports_scanned"] == 1
        assert all_time["cited"] == 2 and all_time["verified"] == 1
        assert all_time["verify_rate"] == 0.5

    def test_health_all_time_empty_db_has_no_rate(self, client):
        qs = client.get("/api/health").json()["quote_stats"]
        assert qs["all_time"]["reports_scanned"] == 0
        assert qs["all_time"]["verify_rate"] is None
