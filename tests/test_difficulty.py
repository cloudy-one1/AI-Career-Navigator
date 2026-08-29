"""
动态难度调度器测试（v6.5，借鉴 interviewerAgent internal/difficulty/scheduler.go）。

重点验证三条纪律：
  1. 只用真实诊断分驱动（不是回复长度）—— 因此无效分数必须被忽略而非当成 0 分；
  2. 只管轮内难度，**不参与阶段推进**（阶段归 v6.2 工程强控）；
  3. 难度变了必须可追溯（trace / summary 供报告披露）。
"""

import pytest

from backend.difficulty import DifficultyScheduler, DifficultyState


class TestLevelChanges:
    def test_two_good_scores_raise(self):
        s = DifficultyScheduler(initial=3)
        s.record(4.5)
        assert s.state.level == 3          # 一次不升
        changed, direction = s.record(4.5)
        assert changed is True
        assert direction == 1
        assert s.state.level == 4

    def test_two_bad_scores_lower(self):
        s = DifficultyScheduler(initial=3)
        s.record(1.5)
        changed, direction = s.record(1.5)
        assert changed is True
        assert direction == -1
        assert s.state.level == 2

    def test_neutral_zone_resets_both_counters(self):
        """中性区同时清零两侧计数：隔一次达标不应被累计升档"""
        s = DifficultyScheduler(initial=3)
        s.record(4.5)      # 达标 1 次
        s.record(3.0)      # 中性 → 清零
        changed, _ = s.record(4.5)   # 重新计 1 次
        assert changed is False
        assert s.state.level == 3

    def test_alternating_scores_never_change(self):
        s = DifficultyScheduler(initial=3)
        for score in (4.8, 1.2, 4.8, 1.2, 4.8):
            s.record(score)
        assert s.state.level == 3

    def test_clamped_at_max(self):
        s = DifficultyScheduler(initial=5)
        changed, _ = s.record(5.0)
        s.record(5.0)
        assert s.state.level == 5

    def test_clamped_at_min(self):
        s = DifficultyScheduler(initial=1)
        s.record(1.0)
        s.record(1.0)
        assert s.state.level == 1

    def test_consec_configurable(self):
        """连续次数可配置（默认 2）"""
        s = DifficultyScheduler(initial=3, consec=3)
        s.record(4.5)
        s.record(4.5)
        assert s.state.level == 3
        changed, _ = s.record(4.5)
        assert changed is True and s.state.level == 4


class TestInvalidScores:
    """诊断失败/缺分时不记录 —— 否则会被当成 0 分一路降到底档"""

    @pytest.mark.parametrize("bad", [None, 0, -1, "abc", "", {}])
    def test_invalid_scores_ignored(self, bad):
        s = DifficultyScheduler(initial=3)
        changed, direction = s.record(bad)
        assert changed is False and direction == 0
        assert s.state.trace == []          # 连轨迹都不写
        assert s.state.level == 3

    def test_failed_diagnosis_then_recovery(self):
        """两次诊断失败 + 一次正常分，不该触发降档"""
        s = DifficultyScheduler(initial=3)
        s.record(None)
        s.record(None)
        changed, _ = s.record(4.0)
        assert changed is False


class TestTraceAndSummary:
    def test_trace_records_every_valid_score(self):
        s = DifficultyScheduler(initial=3)
        s.record(4.5)
        s.record(4.5)
        s.record(2.0)
        assert len(s.state.trace) == 3
        assert s.state.trace[-1]["level"] == 4   # 记录的是当次生效的档位

    def test_summary_fields(self):
        s = DifficultyScheduler(initial=3)
        for score in (4.5, 4.5, 2.0, 2.0, 3.0):
            s.record(score)
        summary = s.summary()
        assert summary["enabled"] is True
        assert summary["initial_level"] == 3
        assert summary["final_level"] == 3       # 升 1 又降 1，回到原点
        assert summary["peak_level"] == 4
        assert summary["lowest_level"] == 3
        assert len(summary["trace"]) == 5

    def test_state_serializable(self):
        s = DifficultyScheduler(initial=2)
        s.record(4.5)
        d = s.state.to_dict()
        assert d["level"] == 2
        assert isinstance(d["trace"], list)


class TestPrompt:
    def test_prompt_contains_level(self):
        s = DifficultyScheduler(initial=4)
        prompt = s.build_prompt()
        assert "4/5" in prompt
        assert "出题难度指令" in prompt

    def test_prompt_describes_layer(self):
        """不同档位的描述必须不同（否则注入等于没注入）"""
        prompts = {DifficultyScheduler(initial=lvl).build_prompt() for lvl in range(1, 6)}
        assert len(prompts) == 5

    def test_prompt_forbids_self_escalation(self):
        """禁止模型自行加码——难度升降由调度器决定，不是模型临场发挥"""
        prompt = DifficultyScheduler(initial=2).build_prompt()
        assert "不要擅自加深" in prompt


class TestSessionIntegration:
    """难度接线到会话：不越权干预阶段推进"""

    def _session(self):
        from backend.interview_engine.session import InterviewSession

        return InterviewSession(
            session_id="d" * 12, resume_text="简历", jd_text="岗位",
            llm_client=None, diagnosis_engine=None,
        )

    def test_session_has_scheduler(self):
        s = self._session()
        assert s.difficulty is not None

    def test_record_difficulty_sets_pending_event(self):
        s = self._session()
        s.record_answer("答", {"overall_score": 4.8})
        assert s.pending_difficulty is None      # 一次不升档
        s.record_answer("答", {"overall_score": 4.8})
        assert s.pending_difficulty is not None
        assert s.pending_difficulty["level"] == 4
        assert s.pending_difficulty["direction"] == 1

    def test_difficulty_does_not_advance_rounds(self):
        """难度变化不得推进轮次（阶段推进归工程强控）"""
        s = self._session()
        before_round = s.current_round
        before_qidx = s.current_question_idx
        s.record_answer("答", {"overall_score": 4.8})
        s.record_answer("答", {"overall_score": 4.8})
        assert s.difficulty.state.level == 4     # 难度确实变了
        assert s.current_round == before_round   # 但轮次没动
        # 题目指针只由 record_answer 自身推进，与难度无关
        assert s.current_question_idx == before_qidx + 2

    def test_instruction_empty_when_disabled(self, monkeypatch):
        from backend import config as cfg

        monkeypatch.setattr(cfg.config, "DIFFICULTY_ENABLED", False)
        s = self._session()
        assert s.difficulty_instruction() == ""

    def test_instruction_nonempty_when_enabled(self):
        s = self._session()
        assert "出题难度指令" in s.difficulty_instruction()

    def test_report_carries_difficulty_trace(self):
        s = self._session()
        s.record_answer("答", {"overall_score": 4.8})
        report = s.build_report()
        assert "difficulty" in report
        assert report["difficulty"]["enabled"] is True
        assert len(report["difficulty"]["trace"]) == 1
