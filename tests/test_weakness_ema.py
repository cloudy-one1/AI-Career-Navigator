"""
薄弱点记忆 EMA 衰减 + 过期淘汰测试（v6.5，借鉴 interviewerAgent memory/service.go）。

分两组：
  1. 纯函数组（不碰 IO）：score_to_weakness / update_weakness / is_expired
  2. DB 往返组：record_observation / active_memory_points / prune_expired
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from backend import weakness_memory as wm


NOW = datetime(2026, 8, 29, 12, 0, 0)


class TestScoreToWeakness:
    """1-5 分 → 薄弱度（0-100），并按岗位权重放大"""

    def test_best_score_zero_weakness(self):
        assert wm.score_to_weakness(5.0) == 0.0

    def test_worst_score_max_weakness(self):
        assert wm.score_to_weakness(1.0) == 100.0

    def test_mid_score(self):
        assert wm.score_to_weakness(3.0) == 50.0
        assert wm.score_to_weakness(4.5) == 12.5

    def test_weight_amplifies(self):
        """岗位权重越高，同样失分越要命"""
        assert wm.score_to_weakness(3.0, 0.4) == 100.0      # 2 倍权重 → 封顶
        assert wm.score_to_weakness(3.0, 0.2) == 50.0
        assert wm.score_to_weakness(3.0, 0.1) == 25.0

    def test_weight_factor_clamped(self):
        """权重系数夹在 0.5~2.0，避免极端权重把薄弱度压成 0 或爆表"""
        assert wm.score_to_weakness(3.0, 10.0) == 100.0     # 上限 2.0 倍
        assert wm.score_to_weakness(3.0, 0.001) == 25.0     # 下限 0.5 倍

    def test_invalid_input_safe(self):
        assert wm.score_to_weakness(None) == 0.0
        assert wm.score_to_weakness("abc") == 0.0
        assert wm.score_to_weakness(3.0, None) == 50.0

    def test_out_of_range_clamped(self):
        assert wm.score_to_weakness(0.0) == 100.0
        assert wm.score_to_weakness(9.9) == 0.0


class TestUpdateWeakness:
    """EMA 演进：加重 / 减轻 / 中性区不动"""

    def test_first_low_score_creates(self):
        st = wm.update_weakness(None, 2.0, now=NOW)
        assert st["occurrence_count"] == 1
        assert st["weakness_score"] > 0
        assert st["removed"] is False
        assert st["expires_at"] == NOW + timedelta(days=30)

    def test_repeated_low_scores_ema_converges(self):
        """多次低分 → 薄弱度单调递增、收敛到该得分对应的薄弱度但不超过它。

        α=0.4 时每次迭代补掉 40% 的差距：10 次后残差为 0.6^10 ≈ 0.6%，
        收敛速度是刻意的（一次失手不应该立刻判死刑）。
        """
        st = None
        scores = []
        for _ in range(10):
            st = wm.update_weakness(st, 2.0, now=NOW)
            scores.append(st["weakness_score"])
        target = wm.score_to_weakness(2.0)
        assert st["occurrence_count"] == 10
        assert all(b >= a for a, b in zip(scores, scores[1:]))   # 单调递增
        assert abs(st["weakness_score"] - target) < 2.0          # 收敛
        assert st["weakness_score"] <= target                    # 不越过目标值

    def test_neutral_zone_changes_nothing(self):
        """3.0~4.5 中性区：计数/薄弱度/过期时间全部不动（连续期也不做）"""
        st = wm.update_weakness(None, 2.0, now=NOW)
        before = dict(st)
        after = wm.update_weakness(st, 3.5, now=NOW + timedelta(days=10))
        assert after["occurrence_count"] == before["occurrence_count"]
        assert after["weakness_score"] == before["weakness_score"]
        assert after["expires_at"] == before["expires_at"]
        assert after["last_score"] == 3.5   # 只有"最近得分"会被刷新

    def test_high_score_relieves(self):
        st = wm.update_weakness(None, 2.0, now=NOW)
        st = wm.update_weakness(st, 2.0, now=NOW)      # count = 2
        relieved = wm.update_weakness(st, 4.8, now=NOW)
        assert relieved["occurrence_count"] == 1
        assert relieved["removed"] is False
        assert relieved["weakness_score"] < st["weakness_score"]

    def test_high_score_to_zero_removes(self):
        st = wm.update_weakness(None, 2.0, now=NOW)    # count = 1
        removed = wm.update_weakness(st, 4.8, now=NOW)
        assert removed["removed"] is True
        assert removed["occurrence_count"] == 0
        assert removed["weakness_score"] == 0.0

    def test_high_score_without_state_is_noop(self):
        """没有既有薄弱点时得高分，不该凭空造出一条已删除记录"""
        st = wm.update_weakness(None, 5.0, now=NOW)
        assert st["removed"] is False
        assert st["occurrence_count"] == 0

    def test_boundary_scores(self):
        """阈值边界：3.0 恰在中性区下沿（不加重），4.5 恰在中性区上沿（不减轻）"""
        st = wm.update_weakness(None, 3.0, now=NOW)
        assert st["occurrence_count"] == 0
        st2 = wm.update_weakness(None, 4.5, now=NOW)
        assert st2["occurrence_count"] == 0

    def test_weight_changes_growth_speed(self):
        """同等失分下，高权重维度涨得更快"""
        low_w = wm.update_weakness(None, 2.0, weight=0.1, now=NOW)
        high_w = wm.update_weakness(None, 2.0, weight=0.4, now=NOW)
        assert high_w["weakness_score"] > low_w["weakness_score"]


class TestIsExpired:
    """过期判定"""

    def test_not_expired(self):
        st = wm.update_weakness(None, 2.0, now=NOW)
        assert wm.is_expired(st, now=NOW + timedelta(days=29)) is False

    def test_expired(self):
        st = wm.update_weakness(None, 2.0, now=NOW)
        assert wm.is_expired(st, now=NOW + timedelta(days=31)) is True

    def test_no_expiry_never_expires(self):
        assert wm.is_expired({"expires_at": None}) is False
        assert wm.is_expired(None) is False

    def test_accepts_string_datetime(self):
        st = {"expires_at": "2020-01-01 00:00:00"}
        assert wm.is_expired(st, now=NOW) is True


# ===== DB 往返 =====


@pytest_asyncio.fixture
async def fresh_db(tmp_path):
    """每个用例一份独立的临时 DB（避免 :memory: 的连接隔离问题）"""
    import backend.db as db_mod
    from backend.config import config
    from backend.db import init_db

    config.DB_PATH = str(tmp_path / "weakness_ema.db")
    db_mod._db = None
    await init_db()
    yield
    db_mod._db = None


class TestRecordObservation:
    @pytest.mark.asyncio
    async def test_record_persists(self, fresh_db):
        await wm.record_observation("star_completeness", 2.0)
        row = await wm.get_weakness_memory("star_completeness")
        assert row is not None
        assert row["occurrence_count"] == 1
        assert row["weakness_score"] > 0

    @pytest.mark.asyncio
    async def test_second_observation_increments(self, fresh_db):
        await wm.record_observation("quantification", 2.0)
        await wm.record_observation("quantification", 2.0)
        row = await wm.get_weakness_memory("quantification")
        assert row["occurrence_count"] == 2

    @pytest.mark.asyncio
    async def test_removed_when_relieved_to_zero(self, fresh_db):
        await wm.record_observation("logic_coherence", 2.0)
        await wm.record_observation("logic_coherence", 5.0)
        row = await wm.get_weakness_memory("logic_coherence")
        assert row is None     # 计数归零 → 已删除

    @pytest.mark.asyncio
    async def test_invalid_dimension_ignored(self, fresh_db):
        assert await wm.record_observation("", 2.0) is None
        assert await wm.record_observation(None, 2.0) is None


class TestActiveMemoryPoints:
    @pytest.mark.asyncio
    async def test_ordered_by_weakness_desc(self, fresh_db):
        """更薄弱的维度排在前面（不是按最近一次均分）"""
        await wm.record_observation("professional_depth", 1.5)   # 最薄弱
        await wm.record_observation("job_relevance", 4.0)        # 不薄弱，不入表
        await wm.record_observation("star_completeness", 2.8)
        points = await wm.active_memory_points(limit=10)
        dims = [p["dimension"] for p in points]
        assert dims[0] == "professional_depth"
        assert "job_relevance" not in dims

    @pytest.mark.asyncio
    async def test_points_shape_compatible(self, fresh_db):
        """兼容 question_gen 既有字段（dimension / avg_score / risk_points）"""
        await wm.record_observation("quantification", 2.0)
        points = await wm.active_memory_points(limit=5)
        assert points
        p = points[0]
        assert "dimension" in p and "avg_score" in p and "risk_points" in p
        assert "weakness_score" in p and "occurrence_count" in p

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, fresh_db):
        assert await wm.active_memory_points(limit=5) == []

    @pytest.mark.asyncio
    async def test_expired_not_returned(self, fresh_db):
        """过期的短板不再回注入"""
        from backend.db import upsert_weakness_memory
        await upsert_weakness_memory("professional_depth", {
            "dimension": "professional_depth",
            "weakness_score": 90.0,
            "occurrence_count": 3,
            "last_score": 1.5,
            "last_seen": "2020-01-01 00:00:00",
            "expires_at": "2020-02-01 00:00:00",   # 早已过期
            "updated_at": "2020-01-01 00:00:00",
        })
        points = await wm.active_memory_points(limit=5)
        assert [p["dimension"] for p in points] == []


class TestPruneExpired:
    @pytest.mark.asyncio
    async def test_prune_removes_expired_only(self, fresh_db):
        from backend.db import upsert_weakness_memory
        await upsert_weakness_memory("expired_one", {
            "dimension": "expired_one", "weakness_score": 80.0,
            "occurrence_count": 2, "last_score": 2.0,
            "last_seen": "2020-01-01 00:00:00",
            "expires_at": "2020-02-01 00:00:00",
            "updated_at": "2020-01-01 00:00:00",
        })
        await wm.record_observation("fresh_one", 2.0)   # 未过期
        removed = await wm.prune_expired()
        assert removed == 1
        assert await wm.get_weakness_memory("expired_one") is None
        assert await wm.get_weakness_memory("fresh_one") is not None
