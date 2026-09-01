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

    def test_needs_recovery_contrast_exemption(self):
        """v8.6: "没做过，但我了解原理"不该被当成卡壳。

        误触发的代价是双重的：恢复话术打断候选人本来的节奏，且该题会被打上
        assisted 标记，进了报告就成了"这题是借助引导完成的"——一个假信号。
        """
        s, _, _ = _make_session()
        assert s.needs_recovery("我没做过这个，但我了解它的实现原理") is False
        assert s.needs_recovery("这块不太了解，不过我可以说说我的理解") is False
        assert s.needs_recovery("不知道，不过我猜应该和缓存穿透有关") is False

    def test_needs_recovery_contrast_needs_substance(self):
        """转折后必须有实质内容才豁免——"我没做过，但……"后面没了仍是卡壳。"""
        s, _, _ = _make_session()
        assert s.needs_recovery("我没做过，但") is True
        assert s.needs_recovery("不会，不过") is True

    def test_needs_recovery_contrast_before_marker(self):
        """先转折、再示弱（"不过我确实不会"）不算豁免：结论仍是不会。"""
        s, _, _ = _make_session()
        assert s.needs_recovery("不过我确实不会") is True

    def test_needs_recovery_still_triggers_without_contrast(self):
        """豁免不能把真正的卡壳一起免掉。"""
        s, _, _ = _make_session()
        assert s.needs_recovery("这个我不懂") is True
        assert s.needs_recovery("完全没思路，答不上来") is True
        assert s.needs_recovery("没接触过这类系统") is True

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


# ===== v8.6: 追问补评（增量重评）=====
# 覆盖的是"分数被改写的边界"，不是 LLM 质量：补评必须能改分、必须留原分、
# 必须只跑一次、失败必须退回首评。这四条任何一条破了，补评就从诊断工具变成噪音。

def _reassess_payload(score=4.6, note="补充了具体数据"):
    return {
        "dimensions": {k: 5 for k in DIM_KEYS},
        "dimension_details": {k: {"comment": "补充到位"} for k in DIM_KEYS},
        "overall_score": score,
        "weakest_dimension": "quantification",
        "reassessment_note": note,
    }


async def _reassess_stream(payload):
    """模拟 DiagnosisEngine.reassess_stream 的消息序列（status → done）。"""
    yield {"type": "reassessment_status", "data": {"phase": "reassessing"}}
    yield {"type": "reassessment_done", "data": payload}


def _session_with_follow_up():
    """已答题 + 已收到一次追问补充的会话（补评的标准前置状态）。"""
    s, _, diag = _make_session()
    _load_question(s)
    s.record_answer("首评回答", _diag_data(overall_score=3))
    s.pending_follow_up = "能具体说说数据吗？"
    s.handle_follow_up_answer("补充：转化率从 12% 提到 18%")
    return s, diag


def _bind_reassess(diag, gen_fn):
    """把 diag.reassess_stream 绑到 gen_fn(**kwargs)（gen_fn 须为异步生成器函数）。"""
    diag.reassess_stream = MagicMock(side_effect=lambda **kw: gen_fn(**kw))


class TestFollowUpReassessment:
    @pytest.mark.asyncio
    async def test_updates_score_and_keeps_original(self):
        """补评改分数，但首评原分必须完整留下（改分不留痕是不可接受的）。"""
        s, diag = _session_with_follow_up()
        before = s.all_diagnoses[-1]["overall_score"]
        _bind_reassess(diag, lambda **kw: _reassess_stream(_reassess_payload()))

        msgs = [m async for m in s.stream_follow_up_reassessment()]

        assert [m["type"] for m in msgs] == ["reassessment_status", "reassessment_done"]
        d = s.all_diagnoses[-1]
        assert d["follow_up_reassessed"] is True
        assert d["overall_score"] == 4.6
        assert d["weakest_dimension"] == "quantification"
        assert d["reassessment_note"] == "补充了具体数据"
        # 首评快照：分数、五维、最弱维度一个都不能少
        assert d["pre_follow_up"]["overall_score"] == before
        assert d["pre_follow_up"]["dimensions"] == {k: 4 for k in DIM_KEYS}
        assert d["reassessment_delta"] == round(4.6 - before, 2)

    @pytest.mark.asyncio
    async def test_supplements_carry_question_and_answer(self):
        """补评输入必须同时带上"追问了什么"与"补充了什么"。

        少了追问问题，模型就只能看到一段没头没尾的补充文本——
        分不清哪句是面试官问的、哪句是候选人答的，评分必然打偏。
        """
        s, diag = _session_with_follow_up()
        captured = {}

        async def _cap(**kwargs):
            captured.update(kwargs)
            async for m in _reassess_stream(_reassess_payload()):
                yield m

        _bind_reassess(diag, _cap)
        [m async for m in s.stream_follow_up_reassessment()]

        assert captured["question"] == "介绍一下你的项目"
        assert captured["answer"] == "首评回答"
        assert len(captured["supplements"]) == 1
        assert "能具体说说数据吗" in captured["supplements"][0]
        assert "转化率从 12% 提到 18%" in captured["supplements"][0]

    @pytest.mark.asyncio
    async def test_reassessment_runs_only_once(self):
        """同一题只补评一次：二次补评会让分数被反复改写，首评快照也失去意义。"""
        s, diag = _session_with_follow_up()
        _bind_reassess(diag, lambda **kw: _reassess_stream(_reassess_payload()))
        [m async for m in s.stream_follow_up_reassessment()]
        first = s.all_diagnoses[-1]["overall_score"]

        _bind_reassess(diag, lambda **kw: pytest.fail("不应发起第二次补评"))
        msgs = [m async for m in s.stream_follow_up_reassessment()]

        assert msgs == []
        assert s.all_diagnoses[-1]["overall_score"] == first

    @pytest.mark.asyncio
    async def test_no_supplement_is_noop(self):
        """没有追问补充就不该补评——那等于把同一份回答评两遍，纯浪费 token。"""
        s, _, diag = _make_session()
        _load_question(s)
        s.record_answer("只有首评", _diag_data())
        diag.reassess_stream = MagicMock(side_effect=lambda **kw: pytest.fail("无补充不应补评"))

        assert [m async for m in s.stream_follow_up_reassessment()] == []

    @pytest.mark.asyncio
    async def test_failure_keeps_first_score(self):
        """补评失败静默退回首评：拿不到 reassessment_done 就等于没发生过。"""
        s, diag = _session_with_follow_up()
        before = s.all_diagnoses[-1]["overall_score"]

        async def _no_done(**kwargs):
            yield {"type": "reassessment_status", "data": {"phase": "reassessing"}}

        _bind_reassess(diag, _no_done)
        msgs = [m async for m in s.stream_follow_up_reassessment()]

        assert [m["type"] for m in msgs] == ["reassessment_status"]
        assert s.all_diagnoses[-1]["overall_score"] == before
        assert s.all_diagnoses[-1].get("follow_up_reassessed") is not True
        assert "pre_follow_up" not in s.all_diagnoses[-1]

    @pytest.mark.asyncio
    async def test_downgrade_is_recorded(self):
        """补评可以降分：补充暴露了新问题时，delta 必须是负的。

        若补评只能涨分，追问就退化成送分机制——比不补评更有害。
        """
        s, diag = _session_with_follow_up()
        _bind_reassess(diag, lambda **kw: _reassess_stream(_reassess_payload(score=2.0)))

        [m async for m in s.stream_follow_up_reassessment()]

        d = s.all_diagnoses[-1]
        assert d["overall_score"] == 2.0
        assert d["reassessment_delta"] == -1.0

    def test_apply_reassessment_without_diagnosis(self):
        """无诊断记录 / 空入参时返回 False，绝不造出一条空分数的诊断。"""
        s, _, _ = _make_session()
        assert s.apply_follow_up_reassessment({}) is False
        _load_question(s)
        s.record_answer("x", _diag_data())
        assert s.apply_follow_up_reassessment({}) is False
        assert s.all_diagnoses[-1].get("follow_up_reassessed") is not True


async def _reassess_stream(payload):
    """模拟 DiagnosisEngine.reassess_stream 的消息序列。"""
    yield {"type": "reassessment_status", "data": {"phase": "reassessing"}}
    yield {"type": "reassessment_done", "data": payload}


class TestServerThinkingCrossCheck:
    """v8.6: 思考时长的服务端交叉校验。

    前端上报值不可能大于"服务端推题 → 收到回答"的墙钟差（后者多算了网络与渲染）。
    这个不变量让"前端报多少就是多少"降级为"可交叉校验"。
    """

    def _answered(self, reported):
        s, _, _ = _make_session()
        _load_question(s)
        s.record_answer("回答", _diag_data(), reported)
        return s

    def test_consistent_report_kept(self):
        """上报值合理（小于服务端墙钟差）：原样保留，不标异常。"""
        s = self._answered(12.0)
        s.annotate_server_thinking(20.0)
        d = s.all_diagnoses[-1]
        assert d["thinking_seconds"] == 12.0
        assert d["server_thinking_seconds"] == 20.0
        assert d["thinking_seconds_anomalous"] is False

    def test_impossible_report_overridden(self):
        """上报值超过服务端墙钟差：以服务端值为准并标注异常。"""
        s = self._answered(120.0)
        s.annotate_server_thinking(20.0)
        d = s.all_diagnoses[-1]
        assert d["thinking_seconds"] == 20.0
        assert d["thinking_seconds_anomalous"] is True
        # answer_history 必须同步，否则报告两处口径不一致
        assert s.answer_history[-1]["thinking_seconds"] == 20.0

    def test_skew_within_tolerance_kept(self):
        """容差内的正常偏差（渲染 + 网络开销）不该被判异常。"""
        s = self._answered(21.0)
        s.annotate_server_thinking(20.0)
        d = s.all_diagnoses[-1]
        assert d["thinking_seconds"] == 21.0
        assert d["thinking_seconds_anomalous"] is False

    def test_no_diagnosis_is_noop(self):
        s, _, _ = _make_session()
        s.annotate_server_thinking(10.0)   # 无诊断记录，不应抛错

    def test_zero_server_elapsed_is_noop(self):
        """服务端墙钟为 0（未采集到）时不覆盖，避免把有效值抹成 0。"""
        s = self._answered(12.0)
        s.annotate_server_thinking(0)
        assert s.all_diagnoses[-1]["thinking_seconds"] == 12.0


class TestOnDemandRewrite:
    """v8.6: 改写按需生成（AUTO_REWRITE=false 时前端看到评分后才来要）。"""

    @pytest.mark.asyncio
    async def test_stream_answer_stores_rewrite_context(self):
        """改写改为按需后，前端来要时这题已不是"当前题"，不留存就拼不出 prompt。"""
        s, _, _ = _make_session()
        _load_question(s)
        [m async for m in s.stream_answer("我的回答")]

        ctx = s._rewrite_ctx
        assert ctx["question"] == "介绍一下你的项目"
        assert ctx["answer"] == "我的回答"
        assert ctx["diagnosis"]["overall_score"] == 4

    @pytest.mark.asyncio
    async def test_mismatched_target_emits_nothing(self):
        """身份不符直接拒绝：把上一题的改写贴到当前题上是"串台"，比慢一点糟得多。"""
        s, _, diag = _make_session()
        s._rewrite_ctx = {"question": "Q", "answer": "A",
                          "diagnosis": {"round": 0, "question_idx": 0}}
        diag.rewrite_stream = MagicMock(side_effect=lambda **kw: pytest.fail("身份不符不应生成"))

        assert [m async for m in s.stream_rewrite(1, 0)] == []
        assert [m async for m in s.stream_rewrite(0, 1)] == []

    @pytest.mark.asyncio
    async def test_stream_rewrite_carries_identity(self):
        """rewrite_done 必须带 round/question_idx —— 前端靠它回填到正确的诊断卡。"""
        s, _, diag = _make_session()
        s._rewrite_ctx = {"question": "Q", "answer": "A",
                          "diagnosis": {"round": 0, "question_idx": 2}}

        async def _rw(**kwargs):
            yield {"type": "rewrite_chunk", "data": {"text": "改写"}}
            yield {"type": "rewrite_done",
                   "data": {"rewritten_answer": "改写文本", "key_changes": ["补数据"]}}

        diag.rewrite_stream = MagicMock(side_effect=lambda **kw: _rw(**kw))
        msgs = [m async for m in s.stream_rewrite(0, 2)]

        assert [m["type"] for m in msgs] == ["rewrite_start", "rewrite_chunk", "rewrite_done"]
        assert msgs[0]["data"] == {"round": 0, "question_idx": 2}
        assert msgs[-1]["data"]["round"] == 0
        assert msgs[-1]["data"]["question_idx"] == 2
        assert msgs[-1]["data"]["rewritten_answer"] == "改写文本"

    @pytest.mark.asyncio
    async def test_no_context_is_noop(self):
        s, _, _ = _make_session()
        assert [m async for m in s.stream_rewrite(0, 0)] == []
