"""会话快照往返一致性测试（v8.21 任务三）。

快照复活的风险模式是"复活后某状态静默归零"——比不复活更危险。本文件按任务书
要求做字段级往返一致性：构造一场进行到中段的会话 → to_snapshot → JSON 序列化/
反序列化（模拟落库路径，任何 set/enum 泄漏在此暴露）→ from_snapshot →
关键字段逐一相等；再钉住 fail-fast 契约（残缺快照必须显式拒绝）。

WS 复活链路（握手 → 快照复活 → 继续作答）在 tests/test_interview_ws.py
的 TestSnapshotRevival 走真实 FastAPI 管线覆盖。
"""
import json
from unittest.mock import MagicMock

import pytest

from backend.config import config
from backend.dimension_weights import DIM_KEYS
from backend.interview_engine.flow import FlowState, NextAction
from backend.interview_engine.session import InterviewSession, SnapshotError
from backend.interview_skills import SkillContext


def _make_session(**overrides) -> InterviewSession:
    llm = MagicMock()
    diag = MagicMock()
    kwargs = dict(
        session_id="snap-1",
        resume_text="5 年后端经验，主导订单系统重构，QPS 从 800 优化到 3000",
        jd_text="招聘高级 Python 后端：熟悉 Redis/MySQL/消息队列",
        llm_client=llm,
        diagnosis_engine=diag,
        interview_style="strict",
        mode="simulation",
        stage="tech_round_1",
        include_self_intro=True,
        question_type_mix={"project": 60},
        resume_points={"deep_dive_points": ["订单系统"], "vague_points": []},
        jd_gaps=["量化不足"],
        company_profile={"display_name": "字节跳动"},
    )
    kwargs.update(overrides)
    return InterviewSession(**kwargs)


def _mid_interview(s: InterviewSession) -> None:
    """把会话推进到"第 2 轮、已答 2 题、追问已发生、状态散布各处"的中段。"""
    s.rounds = [dict(r) for r in config.INTERVIEW_ROUNDS]
    s.current_round = 1
    s.current_question_idx = 1
    s.round_questions = [
        {"question": "讲讲项目背景", "question_type": "project", "is_extra": False},
        {"question": "拆分边界怎么定的？", "question_type": "project", "is_extra": False},
        {"question": "补强：对账幂等怎么设计", "question_type": "project",
         "is_extra": True, "focus_dimension": "logic_coherence"},
    ]
    diag1 = {
        "overall_score": 4.2, "round": 1, "question_idx": 0,
        "dimensions": {k: 4 for k in DIM_KEYS},
        "follow_up_question": "", "weakness_tags": ["量化不足"],
        "next_action": "next_question",
    }
    diag2 = {
        "overall_score": 3.1, "round": 1, "question_idx": 1,
        "dimensions": {k: 3 for k in DIM_KEYS},
        "follow_up_question": "为什么选 Redis 而不是本地缓存？",
        "weakness_tags": ["深度不足"],
    }
    s.record_answer("第一题的回答，包含 STAR 结构与量化数据" * 3, diag1)
    s.record_answer("第二题的回答，讲拆分边界与依赖关系" * 3, diag2)
    s.handle_follow_up_answer("补充：Redis 是为了跨实例共享热点数据", 3.0)
    # 模拟追问补评原地改分（apply_follow_up_reassessment 的效果）
    s.all_diagnoses[-1]["follow_up_reassessed"] = True
    s.all_diagnoses[-1]["overall_score"] = 3.6

    # —— 散布在各处的会话状态 ——
    s.follow_up_count = 1
    s.pending_follow_up = "待推送的追问文本"
    s.extra_questions_added = 1
    s.set_flow_state(FlowState.GENERATING_FOLLOW_UP, answered=3)
    s.dim_weights = {k: w for k, w in zip(
        DIM_KEYS, [0.3, 0.2, 0.2, 0.15, 0.15])}
    s.weight_reason = "JD 强调高并发"
    s.weight_source = "llm"
    s._weights_ready = True
    s.weakness_tags.extend(["量化不足", "深度不足"])
    s._weakness_counts = {"量化不足": 1, "深度不足": 1}
    s.recovery_active = True
    s.recovery_streak = 2
    s.recovery_total = 4
    s._recovery_advice_done = True
    s._injected_hashes = {"hash-a", "hash-b"}
    s._kb_hashes = {"kb-1"}
    s.asked_questions = ["讲讲项目背景", "拆分边界怎么定的？"]
    s.asked_question_hashes = {"q-hash-1", "q-hash-2"}
    s.long_term_memory = [{"dimension": "量化程度", "weakness_score": 0.4}]
    s.pressure_injected = 1
    s.interviewer_history = [{"style_id": "strict", "round": 0}]
    s._rewrite_ctx = {
        "question": "拆分边界怎么定的？",
        "answer": "第二题的回答",
        "diagnosis": dict(diag2),
    }
    s.pending_difficulty = {"type": "difficulty_change", "level": 4, "direction": 1}
    s.self_intro_done = True
    s.active_skill = "quick_quiz"
    ctx = SkillContext(session_id="snap-1", mode="simulation",
                       weak_tags=["量化不足"])
    ctx.step = 2
    ctx.metadata = {"quiz_score": 3}
    s.skill_ctx = ctx
    s.skill_history = [{"reply": "候选人的测验回答"}]


def _roundtrip(s: InterviewSession) -> InterviewSession:
    """to_snapshot → JSON 往返（模拟落库）→ from_snapshot。

    中间必须过一遍 json.dumps/loads：快照协议承诺"纯 JSON 可承载"，
    任何 set/enum/对象引用泄漏都在这一步炸出来。
    """
    data = json.loads(json.dumps(s.to_snapshot(), ensure_ascii=False))
    return InterviewSession.from_snapshot(
        data, llm_client=MagicMock(), diagnosis_engine=MagicMock())


class TestSnapshotRoundtrip:
    @pytest.fixture()
    def pair(self):
        original = _make_session()
        _mid_interview(original)
        return original, _roundtrip(original)

    def test_creation_inputs(self, pair):
        s, r = pair
        assert r.session_id == s.session_id
        assert r.resume_text == s.resume_text
        assert r.jd_text == s.jd_text
        assert r.style == s.style
        assert r.mode == s.mode
        assert r.stage == s.stage
        assert r.include_self_intro == s.include_self_intro
        assert r.question_type_mix == s.question_type_mix
        assert r.resume_points == s.resume_points
        assert r.jd_gaps == s.jd_gaps
        assert r.company_profile == s.company_profile

    def test_round_and_question_state(self, pair):
        s, r = pair
        assert r.rounds == s.rounds
        assert r.current_round == s.current_round
        assert r.current_question_idx == s.current_question_idx
        assert r.round_questions == s.round_questions
        assert r.round_answers == s.round_answers
        assert r.extra_questions_added == s.extra_questions_added
        assert r.is_finished == s.is_finished
        assert r.current_question == s.current_question
        assert r.has_more_questions_in_round() == s.has_more_questions_in_round()

    def test_diagnosis_history(self, pair):
        s, r = pair
        assert r.round_diagnoses == s.round_diagnoses
        assert r.all_diagnoses == s.all_diagnoses
        assert r.answer_history == s.answer_history
        # record_answer 把同一个 dict 同时放进两份（补评原地改分同时生效）；
        # 快照往返后必须重建这一别名关系
        assert r.round_diagnoses[-1] is r.all_diagnoses[-1]
        assert r.all_diagnoses[-1]["overall_score"] == 3.6
        assert r._current_round_avg_score() == s._current_round_avg_score()

    def test_follow_up_state(self, pair):
        s, r = pair
        assert r.follow_up_count == s.follow_up_count
        assert r.pending_follow_up == s.pending_follow_up
        assert r.last_answer_text == s.last_answer_text
        assert r._rewrite_ctx == s._rewrite_ctx
        assert r.skill_history == s.skill_history

    def test_weights(self, pair):
        s, r = pair
        assert r.dim_weights == s.dim_weights
        assert r.weight_reason == s.weight_reason
        assert r.weight_source == s.weight_source
        assert r._weights_ready is True
        assert r.weights_payload() == s.weights_payload()

    def test_weakness_and_recovery(self, pair):
        s, r = pair
        assert r.weakness_tags == s.weakness_tags
        assert r._weakness_counts == s._weakness_counts
        assert r.recovery_active == s.recovery_active
        assert r.recovery_streak == s.recovery_streak
        assert r.recovery_total == s.recovery_total
        assert r._recovery_advice_done == s._recovery_advice_done
        assert r.weakness_payload() == s.weakness_payload()

    def test_dedup_ledgers_are_sets_again(self, pair):
        s, r = pair
        assert r._injected_hashes == s._injected_hashes
        assert isinstance(r._injected_hashes, set)
        assert r._kb_hashes == s._kb_hashes
        assert r.asked_questions == s.asked_questions
        assert r.asked_question_hashes == s.asked_question_hashes
        assert r._is_duplicate_question("讲讲项目背景") == \
            s._is_duplicate_question("讲讲项目背景")

    def test_difficulty_scheduler(self, pair):
        s, r = pair
        assert r.difficulty.state.level == s.difficulty.state.level
        assert r.difficulty.state.consec_up == s.difficulty.state.consec_up
        assert r.difficulty.state.consec_down == s.difficulty.state.consec_down
        assert r.difficulty.state.trace == s.difficulty.state.trace
        assert r.difficulty_instruction() == s.difficulty_instruction()

    def test_skill_active_state(self, pair):
        s, r = pair
        assert r.active_skill == s.active_skill
        assert r.is_skill_active() == s.is_skill_active()
        assert r.skill_ctx.step == s.skill_ctx.step
        assert r.skill_ctx.metadata == s.skill_ctx.metadata
        assert r.skill_ctx.weak_tags == s.skill_ctx.weak_tags

    def test_flow_position(self, pair):
        s, r = pair
        assert r.flow_state == s.flow_state
        assert r.answered_count == s.answered_count
        assert r.flow_payload() == s.flow_payload()

    def test_decision_still_works_after_revive(self, pair):
        """复活不是标本——重建的会话必须能继续参与推进决策。"""
        s, r = pair
        assert r.decide().action == s.decide().action
        assert r.snapshot().current_round == s.snapshot().current_round

    def test_empty_session_roundtrip(self):
        """刚创建、还没答题的会话也必须能完整往返（重启发生在出题前）。

        不钉 decide 的具体动作：空会话（last_answer_text 为空）命中的是纯函数
        的"过短强制追问"分支，是生产从未走过的状态（decide 只在答题后被调用），
        这里只验证"往返前后决策一致"——快照不改变行为。
        """
        s = _make_session()
        r = _roundtrip(s)
        assert r.round_questions == []
        assert r.all_diagnoses == []
        assert r.answered_count == 0
        assert r.flow_state == FlowState.INIT
        assert r.decide().action == s.decide().action


class TestSnapshotFailFast:
    """残缺快照必须显式拒绝（降级为"不复活"），绝不带残缺状态继续面试。"""

    def _data(self) -> dict:
        s = _make_session()
        _mid_interview(s)
        return json.loads(json.dumps(s.to_snapshot(), ensure_ascii=False))

    def _rejects(self, mutate, match: str):
        data = self._data()
        mutate(data)
        with pytest.raises(SnapshotError, match=match):
            InterviewSession.from_snapshot(data, MagicMock(), MagicMock())

    def test_not_a_dict(self):
        with pytest.raises(SnapshotError):
            InterviewSession.from_snapshot(["not", "a", "dict"], MagicMock(), MagicMock())

    def test_unknown_version(self):
        self._rejects(lambda d: d.update(v=999), "版本不识别")

    def test_missing_required_field(self):
        self._rejects(lambda d: d.pop("rounds"), "缺少必填字段")

    def test_missing_difficulty_state(self):
        """难度状态缺失若静默回默认档，复活后难度会"静默归零"——必须拒绝。"""
        self._rejects(lambda d: d.pop("difficulty"), "缺少必填字段")

    def test_bad_flow_state(self):
        self._rejects(lambda d: d.update(flow_state="nope"), "flow_state 不识别")

    def test_bad_numeric_field(self):
        self._rejects(lambda d: d.update(answered_count="很多"), "不是整数")

    def test_bad_dim_weights_type(self):
        self._rejects(lambda d: d.update(dim_weights=[1, 2]), "dim_weights")

    def test_bad_skill_ctx_type(self):
        self._rejects(lambda d: d.update(skill={"skill_ctx": "x"}), "skill_ctx")

    def test_bad_difficulty_type(self):
        self._rejects(lambda d: d.update(difficulty="x"), "difficulty")
