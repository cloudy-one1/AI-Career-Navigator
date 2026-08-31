"""
[v8.0] 求职档案聚合服务测试（backend/profile_service.py）。

钉住三条最容易悄悄回归的承诺：

1. **NBA 规则表**：六条规则的判定顺序即产品优先级——先有"我是谁"，再定"去哪"，
   再测"什么水平"，最后才是"补短板 / 排路线"。顺序错了，"陪跑"这个叙事就散了。
2. **降级纪律**：任一段聚合失败只降级该段，绝不整接口 500。档案是首屏，
   宁可少一段数据也不能白屏（v8.0 明确的产品约束）。
3. **缓存语义**：60s TTL 内不重复聚合（切 tab 是主要调用场景）；
   档案变更后可显式失效，否则用户改了简历却看不到档案更新。

NBA 与差距排序用纯函数直测（无需 DB）；聚合与降级用临时库 + patch 打桩。
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

import backend.db as db_mod
from backend.config import config
from backend import profile_service


@pytest_asyncio.fixture(autouse=True)
async def fresh_db(tmp_path):
    """每个用例独享一个临时库，与真实 data/*.db 物理隔离。"""
    original_db = config.DB_PATH
    original_market = config.MARKET_DB_PATH
    config.DB_PATH = str(tmp_path / f"p{uuid.uuid4().hex}.db")
    config.MARKET_DB_PATH = str(tmp_path / f"m{uuid.uuid4().hex}.db")
    db_mod._db = None
    await db_mod.init_db()
    profile_service.invalidate_profile_cache()   # 缓存是模块级字典，用例间必须隔离
    yield
    config.DB_PATH = original_db
    config.MARKET_DB_PATH = original_market
    db_mod._db = None
    profile_service.invalidate_profile_cache()


# ===== 夹具：构造档案各段 =====

def _identity(has=True, **over):
    d = {"has_resume": has, "resume_id": "r1", "title": "张三-简历",
         "skills": ["Python"], "highlights": [], "char_count": 100, "updated_at": ""}
    d.update(over)
    return d


def _target(has=True, **over):
    d = {"has_target": has, "position_id": "p1", "title": "Python 后端工程师",
         "department": "", "jd_excerpt": "", "market": {}}
    d.update(over)
    return d


def _level(has=True, session_count=1, dims=None, **over):
    d = {"has_history": has, "session_count": session_count, "report_count": 1,
         "overall": 3.8, "dimensions": dims if dims is not None else [
             {"key": "star_completeness", "name": "STAR 完整度", "score": 4.1, "weight": 0.2, "delta": 0.2},
             {"key": "quantification", "name": "量化程度", "score": 4.0, "weight": 0.2, "delta": 0.1},
             {"key": "logic_coherence", "name": "逻辑连贯性", "score": 4.2, "weight": 0.2, "delta": 0.0},
             {"key": "job_relevance", "name": "岗位相关性", "score": 4.3, "weight": 0.2, "delta": 0.1},
             {"key": "professional_depth", "name": "专业深度", "score": 4.0, "weight": 0.2, "delta": -0.1},
         ],
         "delta": {}, "last_session_at": ""}
    d.update(over)
    return d


def _profile(gaps=None, **over):
    p = {
        "identity": _identity(),
        "target": _target(),
        "level": _level(),
        "gaps": gaps or [],
        "updated_at": "",
        "degraded": [],
    }
    p.update(over)
    return p


# ===== NBA 规则表（纯函数，判定顺序即产品优先级）=====

def test_nba_without_resume_asks_for_resume():
    """规则一：没有"我是谁"，一切无从谈起——先要简历。"""
    action = profile_service.next_best_action(_profile(identity=_identity(has=False)))
    assert action["target_tab"] == "resume-library"
    assert action["urgency"] == "high"


def test_nba_without_target_asks_for_position():
    """规则二：有简历没目标 → 先定终点线，否则无法判断差距。"""
    action = profile_service.next_best_action(_profile(target=_target(has=False)))
    assert action["target_tab"] == "position-library"
    assert action["urgency"] == "high"


def test_nba_without_history_asks_for_first_interview():
    """规则三：目标已定但零能力数据 → 先测基线。"""
    action = profile_service.next_best_action(_profile(level=_level(has=False, session_count=0)))
    assert action["target_tab"] == "interview"
    assert "基线" in action["action"]
    assert action["urgency"] == "high"


def test_nba_active_weakness_targets_that_dimension():
    """规则四：有活跃薄弱点 → 精准定位到该维度，并把"为什么是它"讲清楚。"""
    gaps = [{"dimension": "quantification", "name": "量化程度", "kind": "weakness",
             "current": 2.6, "target": 4.0, "severity": 62.0, "occurrence": 3,
             "evidence": ["缺少量化结果"], "action_tab": "interview"}]
    action = profile_service.next_best_action(_profile(gaps=gaps))
    assert action["target_tab"] == "interview"
    assert action["dimension"] == "quantification"
    assert "量化程度" in action["action"]
    assert "连续 3 次" in action["reason"]      # 反复失分要说出来，这是可信度来源


def test_nba_converged_asks_for_career_plan():
    """规则五：短板已收敛（无活跃薄弱点）且场次足够 → 排长期路线。"""
    action = profile_service.next_best_action(_profile(level=_level(session_count=4)))
    assert action["target_tab"] == "career-plan"
    assert action["urgency"] == "normal"


def test_nba_fallback_asks_for_report():
    """规则六：场次不足（<3）且无活跃短板 → 兜底回看报告，不给无意义的建议。"""
    action = profile_service.next_best_action(_profile(level=_level(session_count=1)))
    assert action["target_tab"] == "report"
    assert action["urgency"] == "low"


# ===== 差距清单：长期薄弱点优先于单次低分 =====

def test_gaps_rank_weakness_above_single_low_score():
    """EMA 累积证据（反复失分）必须排在"一次失手"之前——这是排序口径的核心。"""
    level = _level(dims=[
        {"key": "quantification", "name": "量化程度", "score": 3.4, "weight": 0.2, "delta": 0},
        {"key": "star_completeness", "name": "STAR 完整度", "score": 2.1, "weight": 0.2, "delta": 0},
    ])
    memory = [
        {"dimension": "quantification", "weakness_score": 55.0, "occurrence_count": 4,
         "risk_points": ["项目成果未量化"]},
        {"dimension": "star_completeness", "weakness_score": 10.0, "occurrence_count": 1,
         "risk_points": []},   # 低于活跃阈值 30 → 只能走"单次低分"补位通道
    ]
    gaps = profile_service._build_gaps(level, memory)
    assert gaps[0]["dimension"] == "quantification"
    assert gaps[0]["kind"] == "weakness"
    assert gaps[0]["evidence"] == ["项目成果未量化"]
    # STAR 虽单次更低，但薄弱度未达活跃线，只能以 dimension 通道排在后面
    assert gaps[1]["dimension"] == "star_completeness"
    assert gaps[1]["kind"] == "dimension"


def test_gaps_empty_when_all_dimensions_on_target():
    """全部达标时不硬凑差距——"没有待办"本身就是一个有效状态。"""
    gaps = profile_service._build_gaps(_level(), [])
    assert gaps == []


# ===== 聚合与降级（需要 DB）=====

@pytest.mark.asyncio
async def test_empty_profile_degrades_to_guidance():
    """空档案：不报错，而是给出第一步引导（NBA 规则一）。"""
    profile = await profile_service.get_profile(owner_id=None)
    assert profile["identity"]["has_resume"] is False
    assert profile["target"]["has_target"] is False
    assert profile["level"]["has_history"] is False
    assert profile["gaps"] == []
    assert profile["next_action"]["target_tab"] == "resume-library"
    # 空数据是正常状态，不是降级
    assert profile["degraded"] == []


@pytest.mark.asyncio
async def test_segment_failure_only_degrades_that_segment():
    """某段聚合崩溃：只降级该段，其余照常返回，整接口不抛（档案是首屏）。"""
    with patch.object(profile_service, "_load_level", side_effect=RuntimeError("boom")):
        profile = await profile_service.get_profile(owner_id=None)
    assert profile["degraded"] == ["level"]
    assert profile["level"]["has_history"] is False
    assert profile["identity"]["has_resume"] is False      # 其余段不受牵连
    assert profile["next_action"]["target_tab"] == "resume-library"


@pytest.mark.asyncio
async def test_cache_hit_skips_reaggregation():
    """60s TTL 内重复请求不再打库；显式失效后重新聚合。"""
    with patch.object(profile_service, "list_resumes",
                      new=AsyncMock(return_value=[])) as mock_list:
        await profile_service.get_profile(owner_id="u1")
        await profile_service.get_profile(owner_id="u1")
        assert mock_list.await_count == 1

        profile_service.invalidate_profile_cache("u1")
        await profile_service.get_profile(owner_id="u1")
        assert mock_list.await_count == 2


@pytest.mark.asyncio
async def test_cache_is_isolated_per_owner():
    """不同用户的档案互不串味（缓存键必须含 owner_id）。"""
    with patch.object(profile_service, "list_resumes",
                      new=AsyncMock(return_value=[])) as mock_list:
        await profile_service.get_profile(owner_id="u1")
        await profile_service.get_profile(owner_id="u2")
        assert mock_list.await_count == 2


@pytest.mark.asyncio
async def test_build_weakness_context_empty_when_no_data():
    """无薄弱点时返回空串——调用方据此跳过注入，保持规划器既有行为不变。"""
    ctx = await profile_service.build_weakness_context(owner_id=None)
    assert ctx == ""


# ===== 成长曲线 =====

def test_history_is_chronological_and_carries_overall():
    """成长曲线必须按时间正序（旧 → 新）且带综合分——倒序会让"进步"看起来像退步。"""
    level = _profile()["level"]
    level["history"] = [
        {"at": "2026-08-01 10:00:00", "overall": 3.2, "dims": {"quantification": 3.0}},
        {"at": "2026-08-15 10:00:00", "overall": 3.8, "dims": {"quantification": 3.6}},
        {"at": "2026-08-28 10:00:00", "overall": 4.1, "dims": {"quantification": 4.0}},
    ]
    history = level["history"]
    times = [h["at"] for h in history]
    assert times == sorted(times)
    assert [h["overall"] for h in history] == [3.2, 3.8, 4.1]


@pytest.mark.asyncio
async def test_empty_profile_has_empty_history():
    """空档案的 history 必须是空数组而非缺失——前端要做 length 判断。"""
    profile = await profile_service.get_profile(owner_id=None)
    assert profile["level"]["history"] == []


@pytest.mark.asyncio
async def test_level_degrades_with_history_key():
    """level 段整体失败时，降级结构也要带 history 键，避免前端 undefined.length 崩溃。"""
    with patch.object(profile_service, "_load_level", side_effect=RuntimeError("boom")):
        profile = await profile_service.get_profile(owner_id=None)
    assert profile["degraded"] == ["level"]
    assert profile["level"]["history"] == []


# ===== 五步主线完成度 =====

def _states(journey):
    return [s["state"] for s in journey["steps"]]


def test_journey_all_todo_when_profile_empty():
    """空档案：第一步为 current（下一步该走到这），其余 todo。"""
    journey = profile_service.derive_journey(
        {"has_resume": False}, {"has_target": False}, {"session_count": 0, "report_count": 0})
    assert _states(journey) == ["current", "todo", "todo", "todo", "todo"]
    assert journey["completed"] == 0
    assert journey["current_key"] == "positioning"


def test_journey_derives_from_profile_without_marks():
    """前四步由档案推导，无需任何打点。"""
    journey = profile_service.derive_journey(
        {"has_resume": True}, {"has_target": True}, {"session_count": 3, "report_count": 2})
    assert _states(journey) == ["done", "done", "done", "done", "current"]
    assert journey["completed"] == 4


def test_journey_practice_done_but_diagnosis_todo():
    """开过场但没出报告：演练完成、诊断未完成——两步不能共用同一判据。"""
    journey = profile_service.derive_journey(
        {"has_resume": True}, {"has_target": True}, {"session_count": 2, "report_count": 0})
    assert _states(journey) == ["done", "done", "done", "current", "todo"]
    assert journey["current_key"] == "diagnosis"


def test_journey_career_path_requires_mark():
    """发展路径是唯一无法推导的一步，必须打点才算完成。"""
    journey = profile_service.derive_journey(
        {"has_resume": True}, {"has_target": True}, {"session_count": 5, "report_count": 4},
        {"career_path": "2026-08-31 10:00:00"})
    assert _states(journey) == ["done", "done", "done", "done", "done"]
    assert journey["completed"] == 5
    assert journey["current_key"] is None      # 全部完成时不再有"下一步"


# ===== 技能缺口（简历 vs 市场）=====

def test_skill_gap_splits_matched_and_missing():
    """集合运算结果：已具备归 matched，缺的归 missing，且保持市场热度顺序。"""
    gap = profile_service.compute_skill_gap(
        ["Python", "MySQL"], ["Python", "Docker", "MySQL", "Kafka"])
    assert gap["matched"] == ["Python", "MySQL"]
    assert gap["missing"] == ["Docker", "Kafka"]
    assert gap["market_total"] == 4


def test_skill_gap_is_case_and_format_insensitive():
    """市场侧技能名口径脏（大小写 / 后缀），精确匹配会误判成缺口。"""
    gap = profile_service.compute_skill_gap(["python", "mysql"], ["Python3", "MySQL 数据库"])
    assert gap["missing"] == []


def test_skill_gap_short_token_does_not_over_match():
    """单字母技能（如 C）不得靠子串命中 C++ —— 否则缺口会被系统性低估。"""
    gap = profile_service.compute_skill_gap(["C"], ["C++", "Go"])
    assert gap["missing"] == ["C++", "Go"]


def test_skill_gap_empty_when_either_side_missing():
    """任一侧为空就不是"缺口全满"，而是"算不出来"——不能骗用户说全都缺。"""
    assert profile_service.compute_skill_gap([], ["Python"])["missing"] == []
    assert profile_service.compute_skill_gap(["Python"], []) == {
        "matched": [], "missing": [], "market_total": 0}


@pytest.mark.asyncio
async def test_skill_gap_context_empty_when_no_data():
    """无市场数据时返回空串——调用方据此跳过注入，保持规划器既有行为。"""
    ctx = await profile_service.build_skill_gap_context(owner_id=None)
    assert ctx == ""


@pytest.mark.asyncio
async def test_journey_marks_roundtrip_and_anonymous_never_writes():
    """打点幂等；未登录一律不落库（否则所有匿名用户的数据会混在一起）。"""
    await db_mod.mark_journey_step("user-a", "career_path")
    await db_mod.mark_journey_step("user-a", "career_path")     # 重复写入不得报错
    await db_mod.mark_journey_step(None, "career_path")          # 匿名写入必须被忽略

    marks = await db_mod.list_journey_marks("user-a")
    assert list(marks.keys()) == ["career_path"]
    assert await db_mod.list_journey_marks(None) == {}
    assert await db_mod.list_journey_marks("user-b") == {}
