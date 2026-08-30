"""
interview_engine/session.py 测试：InterviewSession 状态机。
通过 mock LLM 客户端与诊断引擎，覆盖轮次推进、追问、权重初始化、
诊断记录、模式切换、报告构建等关键路径（不触发真实 LLM / DB）。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.config import config as cfg  # Config 实例
from backend.dimension_weights import DEFAULT_WEIGHTS, DIM_KEYS
from backend.interview_engine import session as session_mod
from backend.interview_engine.session import InterviewSession


def _diag_data(**extra):
    data = {
        "overall_score": 4,
        "dimensions": {k: 4 for k in DIM_KEYS},
        "dimension_details": {k: {"comment": "回答完整"} for k in DIM_KEYS},
        "follow_up_question": "",
    }
    data.update(extra)
    return data


def _make_stream(data):
    async def _gen(**kwargs):
        yield {"type": "token", "content": "x"}
        yield {"type": "diagnosis_done", "data": data}
    return _gen


def _make_session(**overrides):
    llm = MagicMock()
    llm.chat = MagicMock(return_value="生成追问")
    diag = MagicMock()
    diag.diagnose = AsyncMock(return_value=_diag_data(overall_score=3))
    diag.stream = MagicMock(side_effect=lambda **kw: _make_stream(_diag_data())(**kw))
    kwargs = dict(
        session_id="s1",
        resume_text="3 年 Python 开发经验",
        jd_text="招聘 Python 后端工程师",
        llm_client=llm,
        diagnosis_engine=diag,
        interview_style="friendly",
        db=MagicMock(),
        mode="simulation",
    )
    kwargs.update(overrides)
    return InterviewSession(**kwargs), llm, diag


def _load_question(s):
    s.round_questions = [{"question": "介绍一下你的项目", "question_type": "project"}]
    s.current_question_idx = 0


class TestConstructor:
    def test_rounds_from_config(self):
        s, _, _ = _make_session()
        assert len(s.rounds) == len(cfg.INTERVIEW_ROUNDS)
        assert s.is_finished is False
        assert s.current_question is None
        assert s.current_round == 0

    def test_current_round_info(self):
        s, _, _ = _make_session()
        assert s.current_round_info()["name"] == cfg.INTERVIEW_ROUNDS[0]["name"]

    def test_current_interviewer(self):
        s, _, _ = _make_session()
        iv = s.current_interviewer()
        # simulation 轮次未配置 interviewer_style -> 回退 self.style
        assert iv["style_id"] == "friendly"
        assert s.get_interviewer_system_prompt() == \
            cfg.INTERVIEWER_STYLES["friendly"]["system_prompt_modifier"]

    def test_interviewer_change_event(self):
        s, _, _ = _make_session()
        e1 = s.get_interviewer_change_event()
        assert e1["type"] == "interviewer_change"
        assert e1["previous"] is None
        # 同一风格 -> 无变化
        assert s.get_interviewer_change_event() is None
        # 切换风格（拷贝轮次配置，避免污染全局 config）
        s.rounds = [dict(r) for r in s.rounds]
        other = next(k for k in cfg.INTERVIEWER_STYLES if k != "friendly")
        s.rounds[s.current_round]["interviewer_style"] = other
        e2 = s.get_interviewer_change_event()
        assert e2["current"]["style_id"] == other


class TestWeights:
    @pytest.mark.asyncio
    async def test_init_weights_success(self):
        s, _, _ = _make_session()
        mock = AsyncMock(return_value={"weights": {"technical_depth": 0.5},
                                       "reason": "r", "source": "llm"})
        with patch.object(session_mod, "analyze_jd_weights", mock):
            payload = await s.init_weights()
        assert payload["weights"]["technical_depth"] == 0.5
        assert payload["source"] == "llm"
        # 幂等：_weights_ready 后不再重复分析
        s2, _, _ = _make_session()
        s2._weights_ready = True
        with patch.object(session_mod, "analyze_jd_weights",
                          AsyncMock(side_effect=AssertionError("不应再调用"))):
            await s2.init_weights()

    @pytest.mark.asyncio
    async def test_init_weights_fallback_on_error(self):
        s, _, _ = _make_session()
        with patch.object(session_mod, "analyze_jd_weights",
                          AsyncMock(side_effect=Exception("boom"))):
            payload = await s.init_weights()
        assert s.dim_weights == dict(DEFAULT_WEIGHTS)
        assert payload["source"] == "default"

    def test_weights_payload_shape(self):
        s, _, _ = _make_session()
        payload = s.weights_payload()
        assert set(payload.keys()) == {"weights", "weight_names", "weight_desc",
                                       "reason", "source"}
        assert set(payload["weight_names"].keys()) == set(DIM_KEYS)


class TestAnswerFlow:
    def test_record_answer(self):
        s, _, _ = _make_session()
        _load_question(s)
        s.record_answer("我的回答", {"overall_score": 3, "follow_up_question": "再深入?"})
        assert s.round_answers == ["我的回答"]
        assert len(s.round_diagnoses) == 1
        assert len(s.all_diagnoses) == 1
        assert s.pending_follow_up == "再深入?"
        assert s.current_question_idx == 1
        d = s.round_diagnoses[0]
        assert d["round"] == 0
        assert d["question"] == "介绍一下你的项目"

    @pytest.mark.asyncio
    async def test_handle_answer(self):
        s, _, diag = _make_session()
        _load_question(s)
        result = await s.handle_answer("我的回答")
        assert result["overall_score"] == 3
        diag.diagnose.assert_awaited_once()
        assert len(s.round_diagnoses) == 1

    @pytest.mark.asyncio
    async def test_stream_answer(self):
        s, _, diag = _make_session()
        _load_question(s)
        msgs = [m async for m in s.stream_answer("我的回答")]
        assert [m["type"] for m in msgs] == ["token", "diagnosis_done"]
        assert len(s.round_diagnoses) == 1
        diag.stream.assert_called_once()

    def test_needs_recovery(self):
        s, _, _ = _make_session()
        assert s.needs_recovery("这个问题我不会") is True
        assert s.needs_recovery("我做过一个类似的项目，方案是这样的") is False
        assert s.needs_recovery("") is False

    def test_handle_follow_up_answer(self):
        s, _, _ = _make_session()
        _load_question(s)
        s.record_answer("第一版回答", {"overall_score": 3})
        s.handle_follow_up_answer("补充回答")
        assert s.pending_follow_up == ""
        assert "[追问补充]" in s.round_answers[-1]
        assert "补充回答" in s.answer_history[-1].get("follow_ups", [])


class TestFollowUp:
    def test_should_follow_up_branches(self):
        s, _, _ = _make_session()
        # 达到追问上限 -> False
        s.follow_up_count = cfg.FOLLOW_UP_MAX_COUNT
        assert s.should_follow_up("很长很长很长的回答" * 10) is False
        s.follow_up_count = 0
        # 诊断自带追问 -> True
        assert s.should_follow_up("x" * 50, {"follow_up_question": "追问?"}) is True
        # 回答过短 -> True
        assert s.should_follow_up("太短", {}) is True
        # 分数低于阈值 -> True
        assert s.should_follow_up("x" * 50, {"overall_score": 2.0}) is True
        # 正常 -> False
        assert s.should_follow_up("x" * 50, {"overall_score": 4.0}) is False

    def test_should_follow_up_honors_next_action(self):
        """v6.0: 采信诊断同轮产出的 next_action 三态决策。"""
        s, _, _ = _make_session()
        # 模型声明 next_question/complete 且无追问文本：低分也不再强制追问
        assert s.should_follow_up(
            "x" * 50, {"overall_score": 2.0, "next_action": "next_question"}
        ) is False
        assert s.should_follow_up(
            "x" * 50, {"overall_score": 4.0, "next_action": "complete"}
        ) is False
        # 但回答过短仍强制追问（防敷衍回答被"放行"）
        assert s.should_follow_up(
            "太短", {"overall_score": 4.0, "next_action": "complete"}
        ) is True
        # 声明 next_question 但模型仍产出追问文本 → 仍追问（追问优先）
        assert s.should_follow_up(
            "x" * 50,
            {"overall_score": 4.0, "next_action": "next_question",
             "follow_up_question": "追问?"},
        ) is True
        # 未声明 next_action → 走原有阈值规则（向后兼容）
        assert s.should_follow_up("x" * 50, {"overall_score": 2.0}) is True

    @pytest.mark.asyncio
    async def test_generate_follow_up_prefers_preset(self):
        s, llm, _ = _make_session()
        s.pending_follow_up = "预设追问"
        assert await s.generate_follow_up() == "预设追问"
        assert s.pending_follow_up == ""
        assert s.follow_up_count == 1
        llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_follow_up_generated(self):
        s, llm, _ = _make_session()
        s.last_answer_text = "候选人的上一段回答"
        assert await s.generate_follow_up({"overall_score": 3}) == "生成追问"
        llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_follow_up_llm_error_fallback(self):
        s, llm, _ = _make_session()
        llm.chat = MagicMock(side_effect=Exception("llm down"))
        assert await s.generate_follow_up({}) == "能否再详细说说？"

    def test_mark_follow_up_skipped_marks_diagnosis(self):
        """v7.0.2: 跳过追问 → 本题诊断打上 follow_up_skipped 并留存追问文本。"""
        s, _, _ = _make_session()
        _load_question(s)
        s.record_answer("第一版回答", {"overall_score": 3, "follow_up_question": "追问?"})
        s.mark_follow_up_skipped("追问?")
        d = s.all_diagnoses[-1]
        assert d["follow_up_skipped"] is True
        assert d["skipped_follow_up"] == "追问?"
        assert s.pending_follow_up == ""

    def test_mark_follow_up_skipped_fallback_to_pending(self):
        """v7.0.2: 未传追问文本时回退取 pending_follow_up（防御性兼容）。"""
        s, _, _ = _make_session()
        _load_question(s)
        s.record_answer("第一版回答", {"overall_score": 3, "follow_up_question": "追问?"})
        s.pending_follow_up = "待推送的追问"
        s.mark_follow_up_skipped()
        d = s.all_diagnoses[-1]
        assert d["follow_up_skipped"] is True
        assert d["skipped_follow_up"] == "待推送的追问"
        assert s.pending_follow_up == ""

    def test_mark_follow_up_skipped_without_diagnosis(self):
        """v7.0.2: 无诊断记录时调用不报错、只清空 pending。"""
        s, _, _ = _make_session()
        s.pending_follow_up = "追问?"
        s.mark_follow_up_skipped("追问?")
        assert s.pending_follow_up == ""

    def test_build_report_exposes_skipped_follow_up(self):
        """v7.0.2: 跳过追问进入 qa_breakdown 标记与 follow_up_stats 统计。"""
        s, _, _ = _make_session()
        _load_question(s)
        s.record_answer("第一版回答", {"overall_score": 3})
        s.mark_follow_up_skipped("再具体说说？")
        report = s.build_report()
        assert report["follow_up_stats"]["skipped_count"] == 1
        item = report["qa_breakdown"][0]
        assert item["follow_up_skipped"] is True
        assert item["skipped_follow_up"] == "再具体说说？"
        assert "追问被跳过" in report["suggestions"]


class TestRoundNavigation:
    def test_has_more_questions_in_round(self):
        s, _, _ = _make_session()
        assert s.has_more_questions_in_round() is False  # 尚未生成题目
        s.round_questions = [{"question": "Q1"}, {"question": "Q2"}]
        s.current_question_idx = 0
        assert s.has_more_questions_in_round() is True
        s.current_question_idx = 2
        assert s.has_more_questions_in_round() is False

    def test_round_remaining(self):
        s, _, _ = _make_session()
        s.round_questions = [{"question": "Q1"}, {"question": "Q2"}]
        s.current_question_idx = 1
        assert s.round_remaining == 1

    def test_should_add_extra_question(self):
        s, _, _ = _make_session()
        s.current_round = 1  # 技术广度 max_extra_questions=2
        assert s.should_add_extra_question() is True
        s.extra_questions_added = 2
        assert s.should_add_extra_question() is False

    def test_advance_round(self):
        s, _, _ = _make_session()
        s.round_questions = [{"question": "Q"}]
        s.current_question_idx = 1
        assert s.advance_round() is True
        assert s.current_round == 1
        assert s.round_questions == []
        assert s.current_question_idx == 0
        # 最后一轮推进 -> 面试结束
        s.current_round = len(s.rounds) - 1
        assert s.advance_round() is False
        assert s.is_finished is True

    def test_check_round_quality(self):
        s, _, _ = _make_session()
        s.current_round = 1
        s.round_diagnoses = [{"overall_score": 3.0}, {"overall_score": 2.0}]
        q = s.check_round_quality()
        assert q["avg_score"] == 2.5
        assert q["passed"] is True
        assert q["round_name"] == "技术广度"

    def test_round_summary(self):
        s, _, _ = _make_session()
        s.current_round = 1
        s.round_answers = ["a", "b"]
        summary = s.round_summary()
        assert summary["round"] == 1
        assert summary["round_name"] == "技术广度"
        assert summary["question_count"] == 2


class TestDiagnosisAggregation:
    def test_round_weak_dimension(self):
        s, _, _ = _make_session()
        k_weak, k_strong = DIM_KEYS[0], DIM_KEYS[1]
        s.round_diagnoses = [{
            "dimensions": {k_weak: 2, k_strong: 5},
            "dimension_details": {
                k_weak: {"comment": "原理讲解不清"},
                k_strong: {"comment": "表达流畅"},
            },
        }]
        dim, evidence = s.round_weak_dimension()
        assert dim == k_weak
        assert "原理讲解不清" in evidence

    def test_round_weak_dimension_empty(self):
        s, _, _ = _make_session()
        assert s.round_weak_dimension() == ("", "")

    def test_radar_snapshot(self):
        s, _, _ = _make_session()
        s.all_diagnoses = [{"dimensions": {k: 4 for k in DIM_KEYS}}]
        snap = s.radar_snapshot()
        assert snap["average"][DIM_KEYS[0]] == 4
        assert snap["latest"][DIM_KEYS[0]] == 4
        assert snap["answered_count"] == 1
        assert len(snap["keys"]) == len(DIM_KEYS)

    def test_accumulate_weaknesses(self):
        s, _, _ = _make_session()
        s.accumulate_weaknesses(["并发", "并发", ""])
        assert s.weakness_tags == ["并发"]
        assert s._weakness_counts["并发"] == 2
        assert s.weakness_payload()["tags"] == ["并发"]

    def test_switch_mode(self):
        s, _, _ = _make_session()
        event = s.switch_mode("traditional")
        assert event["type"] == "mode_change"
        assert event["applied_next_round"] is True
        assert s.mode == "traditional"
        # 相同模式 -> 未变化
        event2 = s.switch_mode("traditional")
        assert event2["applied_next_round"] is False


class TestGenerateQuestions:
    @pytest.mark.asyncio
    async def test_generate_questions(self):
        s, _, _ = _make_session(include_self_intro=False)
        mock_gen = AsyncMock(return_value=[{"question": "Q1", "question_type": "knowledge"}])
        with patch.object(session_mod, "generate_round_questions", mock_gen):
            qs = await s.generate_questions()
        assert qs == [{"question": "Q1", "question_type": "knowledge"}]
        assert s.current_question["question"] == "Q1"
        assert s.current_question_idx == 0

    @pytest.mark.asyncio
    async def test_self_intro_inserted_first_round(self):
        s, _, _ = _make_session(include_self_intro=True)
        with patch.object(session_mod, "generate_round_questions",
                          AsyncMock(return_value=[{"question": "Q1"}])):
            qs = await s.generate_questions()
        assert qs[0]["question_type"] == "self_intro"
        assert qs[0]["index"] == -1
        assert s.self_intro_done is True

    @pytest.mark.asyncio
    async def test_coach_mode_inserts_tip(self):
        s, _, _ = _make_session(include_self_intro=False, mode="coach")
        with patch.object(session_mod, "generate_round_questions",
                          AsyncMock(return_value=[{"question": "Q1"}])), \
             patch.object(session_mod, "generate_coach_tip",
                          AsyncMock(return_value={"question": "讲解", "intent": "内容",
                                                  "question_type": "coach_tip"})):
            qs = await s.generate_questions()
        assert qs[0]["question_type"] == "coach_tip"
        assert qs[1]["question"] == "Q1"

    @pytest.mark.asyncio
    async def test_generate_extra_question(self):
        s, _, _ = _make_session(include_self_intro=False)
        s.current_round = 1
        s.round_diagnoses = [{
            "dimensions": {"quantification": 2},
            "dimension_details": {"quantification": {"comment": "缺少数据"}},
        }]
        with patch.object(session_mod, "generate_round_questions",
                          AsyncMock(return_value=[{"question": "EQ"}])):
            eq = await s.generate_extra_question()
        assert eq["is_extra"] is True
        assert eq["focus_dimension"] == "quantification"
        assert s.extra_questions_added == 1
        assert s.round_questions[-1] is eq

    def test_build_report(self):
        s, _, _ = _make_session()
        with patch.object(session_mod, "build_report", return_value={"summary": "x"}) as m:
            assert s.build_report() == {"summary": "x"}
        m.assert_called_once_with(s)
