"""
v6.3 借鉴 mock-interviewer 的能力落地测试
（对应《docs/mock-interviewer-深度研读.md》第 10 节 P0 / P1 清单）：

  P0-1 面试官角色卡：perspective / followup_chain / never_ask 三字段 + 注入 prompt
  P0-2 追问范式绑定角色：问什么（薄弱维度）× 怎么问（角色追问链）
  P0-3 简历锚点五分类：技术选型 / 量化数据 / 架构设计 / 业务决策 / 团队管理
  P1-1 规则化加减分项：确定性行为信号 + evidence + 封顶与夹紧
  P1-2 JD gap 出题优先级显式注入
  P1-3 压力题库随机注入 + 三道闸门 + 去重
  P1-4 恢复态红线（绝不给答案）+ 3 次阈值 + assisted 标记

测试约定：不依赖真实 LLM，全部用 MagicMock / monkeypatch 隔离。
"""

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import question_gen as qg
from backend.config import config
from backend.diagnosis_engine import _build_diagnostician_system, normalize_result
from backend.dimension_weights import DIM_KEYS
from backend.interview_engine.report import build_report
from backend.interview_engine.session import (
    RECOVERY_FALLBACK_PROMPT,
    RECOVERY_SKIP_ADVICE,
    RECOVERY_SKIP_THRESHOLD,
    InterviewSession,
)
from backend.output_sanitizer import contains_answer_leak
from backend.pressure_bank import list_questions, sample_questions
from backend.resume_anchors import (
    ARCHITECTURE,
    METRIC,
    TEAM,
    TECH_CHOICE,
    build_anchors_block,
    classify,
    group_points,
    merge_anchor_sources,
)
from backend.score_adjustments import (
    DIM_QUANT,
    MAX_PENALTY_PER_ANSWER,
    Adjustment,
    apply_adjustments,
    detect_adjustments,
)


def _make_session(**overrides):
    llm = MagicMock()
    llm.chat = MagicMock(return_value="追问")
    diag = MagicMock()
    diag.diagnose = AsyncMock(return_value={"overall_score": 3})
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
    return InterviewSession(**kwargs)


# ==================== P0-1 面试官角色卡 ====================

class TestInterviewerRoleCard:
    def test_all_styles_carry_full_card(self):
        """7 种风格缺一不可：视角独白 / 追问链 / 不会问清单。"""
        for sid, style in config.INTERVIEWER_STYLES.items():
            assert style.get("perspective"), f"{sid} 缺 perspective"
            assert len(style.get("followup_chain") or []) >= 3, f"{sid} 追问链过短"
            assert len(style.get("never_ask") or []) >= 3, f"{sid} 不会问清单过短"

    def test_current_interviewer_exposes_card(self):
        s = _make_session(interview_style="strict")
        iv = s.current_interviewer()
        assert iv["perspective"]
        assert iv["followup_chain"]
        assert iv["never_ask"]

    def test_role_prompt_has_three_sections(self):
        s = _make_session(interview_style="skeptical")
        p = s.get_interviewer_role_prompt()
        assert "你在评判什么" in p
        assert "你的追问路径" in p
        assert "你不问什么" in p

    def test_system_prompt_contract_unchanged(self):
        """既有契约不可动：原方法仍只返回语气指令（test_session 依赖此语义）。"""
        s = _make_session(interview_style="friendly")
        assert (s.get_interviewer_system_prompt()
                == config.INTERVIEWER_STYLES["friendly"]["system_prompt_modifier"])


# ==================== P0-2 追问范式绑定角色 ====================

class TestFollowUpPatternBoundToRole:
    @pytest.mark.asyncio
    async def test_follow_up_prompt_carries_role_chain_and_focus(self):
        """问什么（薄弱维度）与怎么问（角色追问链）必须同时注入。"""
        captured = {}

        def _chat(system, user, *a, **kw):
            captured["system"] = system
            return "你刚才提到 XX，能具体说说吗"

        llm = MagicMock()
        llm.chat = _chat
        s = _make_session(interview_style="skeptical", llm_client=llm)

        out = await s.generate_follow_up(diagnosis={"weakest_dimension_name": "量化程度"})
        assert out
        # 怎么问：skeptical 的追问链首环
        assert "这个数据是怎么归因的" in captured["system"]
        # 负向边界
        assert "你不问什么" in captured["system"]
        # 问什么：薄弱维度
        assert "量化程度" in captured["system"]

    @pytest.mark.asyncio
    async def test_different_roles_produce_different_prompts(self):
        """7 种风格的核心差异验证：追问结构不同，而非仅语气不同。"""
        seen = {}

        for style in ("strict", "curious"):
            captured = {}

            def _chat(system, user, *a, **kw):
                captured["system"] = system
                return "追问"

            llm = MagicMock()
            llm.chat = _chat
            s = _make_session(interview_style=style, llm_client=llm)
            await s.generate_follow_up(diagnosis={"weakest_dimension_name": ""})
            seen[style] = captured["system"]

        assert seen["strict"] != seen["curious"]

    def test_diagnostician_prompt_injects_role_without_touching_scoring(self):
        """角色卡进诊断 prompt 时必须声明"不影响评分标准"。"""
        p = _build_diagnostician_system(None, False, "【角色卡】测试内容")
        assert "【角色卡】测试内容" in p
        assert "不影响下述五维评分标准" in p

    def test_diagnostician_prompt_without_role_unchanged(self):
        """不传角色卡时行为与 v6.2 一致（向后兼容）。"""
        p = _build_diagnostician_system(None, False, "")
        assert "本次面试官角色设定" not in p


# ==================== P0-3 简历锚点五分类 ====================

class TestResumeAnchors:
    def test_classify_metric(self):
        assert classify("接口 P99 从 800ms 降到 200ms，未说明优化手段") == METRIC

    def test_classify_tech_choice(self):
        assert classify("项目里用了 Redis，但未说明选型依据") == TECH_CHOICE

    def test_classify_architecture(self):
        assert classify("从0到1搭建了整套系统架构，需核实设计边界") == ARCHITECTURE

    def test_classify_team(self):
        assert classify("带领 5 人团队完成迁移，需核实分工") == TEAM

    def test_unclassifiable_returns_empty(self):
        """无法归类时宁可弃权，也不乱分类注入错误方向。"""
        assert classify("") == ""
        assert classify("这段话没有任何可识别信号") == ""

    def test_group_points_drops_unclassifiable(self):
        grouped = group_points(["用了 Kafka 做削峰", "无意义的句子"])
        assert grouped[TECH_CHOICE] == ["用了 Kafka 做削峰"]
        assert "无意义的句子" not in sum(grouped.values(), [])

    def test_merge_prefers_llm_output(self):
        merged = merge_anchor_sources(
            {"metric": ["提升 30% 未说明口径"]},
            ["用了 Redis 未说明原因"],
        )
        assert merged[METRIC] == ["提升 30% 未说明口径"]
        # LLM 没给的 tech_choice 由规则补齐
        assert merged[TECH_CHOICE] == ["用了 Redis 未说明原因"]

    def test_build_anchors_block_includes_probe_direction(self):
        block = build_anchors_block({"metric": ["提升 30% 未说明口径"]})
        assert "量化数据" in block
        assert "怎么测出来" in block

    def test_build_anchors_block_empty_for_noise(self):
        assert build_anchors_block({}) == ""
        assert build_anchors_block(None) == ""

    def test_resume_points_block_appends_anchor_section(self):
        text = qg.build_resume_points_block({
            "deep_dive_points": ["接口 P99 从 800ms 降到 200ms"],
            "vague_points": [],
        })
        assert "值得深挖的点" in text
        # 即使 LLM 没给 anchors，也应按规则补齐锚点方向
        assert "锚点类型与追问方向" in text


# ==================== P1-1 规则化加减分项 ====================

class TestScoreAdjustments:
    def test_no_quantification(self):
        adjs = detect_adjustments("说说你做的性能优化",
                                  "我们做了很多优化，性能提升明显，效果不错。")
        hit = next((a for a in adjs if a.key == "no_quantification"), None)
        assert hit is not None
        assert hit.dimension == DIM_QUANT
        assert hit.delta == -1.0
        assert hit.evidence  # 必须有证据，否则不可解释

    def test_data_conflict(self):
        adjs = detect_adjustments("优化效果如何",
                                  "优化后性能提升了 30%，后来又提升了 50%。")
        hit = next((a for a in adjs if a.key == "data_conflict"), None)
        assert hit is not None and hit.delta == -2.0

    def test_data_conflict_suppresses_quantified_bonus(self):
        """矛盾的数据不能同时算"量化充分"，否则一加一减看不懂。"""
        adjs = detect_adjustments("q", "优化后性能提升了 30%，后来又提升了 50%。")
        assert not any(a.key == "quantified" for a in adjs)

    def test_term_stacking(self):
        text = "我熟悉 Redis、Kafka、MySQL、gRPC、Docker、K8s 等"
        adjs = detect_adjustments("你的技术栈", text)
        assert any(a.key == "term_stacking" for a in adjs)

    def test_causal_words_suppress_term_stacking(self):
        """有因果展开就不算堆砌——规则不能把"讲清楚了"当成"背概念"。"""
        text = "我用了 Redis、Kafka，因为写入压力大，所以引入了消息队列削峰"
        adjs = detect_adjustments("你的技术栈", text)
        assert not any(a.key == "term_stacking" for a in adjs)

    def test_blame_shift(self):
        adjs = detect_adjustments("这个项目你做了什么",
                                  "这个模块不是我负责的，是其他团队做的。")
        assert any(a.key == "blame_shift" for a in adjs)

    def test_quantified_bonus(self):
        text = "P99 从 800ms 降到 200ms，QPS 提升了 3 倍，覆盖 200 万用户。"
        adjs = detect_adjustments("优化效果", text)
        assert any(a.key == "quantified" and a.delta > 0 for a in adjs)

    def test_candid_gap_bonus(self):
        text = "这个我不太了解，后续我会去查一下资料把这块补上。"
        adjs = detect_adjustments("q", text)
        assert any(a.key == "candid_gap" and a.delta > 0 for a in adjs)

    def test_penalty_capped_per_answer(self):
        adjs = detect_adjustments("q", "不是我负责的，不清楚。")
        total = sum(-a.delta for a in adjs if a.delta < 0)
        assert total <= MAX_PENALTY_PER_ANSWER

    def test_apply_clamps_and_skips_unscored(self):
        dims = {DIM_QUANT: 1.0, "star_completeness": 0, "professional_depth": 5.0}
        adjs = [
            Adjustment("a", "a", DIM_QUANT, -2.0, ""),
            Adjustment("b", "b", "star_completeness", -1.0, ""),
            Adjustment("c", "c", "professional_depth", 1.0, ""),
        ]
        out = apply_adjustments(dims, adjs)
        assert out[DIM_QUANT] == 1.0               # 夹紧下限
        assert out["star_completeness"] == 0       # 未评分不得被规则抬升
        assert out["professional_depth"] == 5.0    # 夹紧上限

    def test_normalize_result_applies_and_records_both_scores(self):
        diag = {k: {"score": 3, "comment": ""} for k in DIM_KEYS}
        r = normalize_result(diag, {}, None,
                             question="说说优化",
                             answer="我们做了很多优化，性能提升明显，效果不错。")
        assert r["raw_dimensions"][DIM_QUANT] == 3.0      # 模型原始分
        assert r["dimensions"][DIM_QUANT] == 2.0          # 修正后
        assert any(a["key"] == "no_quantification" for a in r["score_adjustments"])
        assert r["overall_score"] < 3.0

    def test_normalize_result_without_answer_unchanged(self):
        """兼容旧调用：不传 question/answer 时与 v6.2 行为一致。"""
        diag = {k: {"score": 3, "comment": ""} for k in DIM_KEYS}
        r = normalize_result(diag, {}, None)
        assert r["dimensions"] == r["raw_dimensions"]
        assert r["score_adjustments"] == []


# ==================== P1-2 JD gap 出题优先级 ====================

class TestJdGapPriority:
    @pytest.mark.asyncio
    async def test_jd_gap_block_injected(self, monkeypatch):
        captured = {}

        def _chat_json(system, user, *a, **kw):
            captured["user"] = user
            return {"questions": []}

        llm = MagicMock()
        llm.chat_json = _chat_json
        # 市场上下文要查库，此处与断言无关，隔离掉
        monkeypatch.setattr(qg, "_build_market_context_block", AsyncMock(return_value=""))

        await qg.generate_round_questions(
            llm_client=llm, resume_text="r", jd_text="j",
            round_idx=1, round_name="技术广度", count=3,
            jd_gaps=["分布式系统经验：简历只有单体项目"],
        )
        user = captured.get("user", "")
        assert "JD 匹配缺口" in user
        assert "分布式系统经验" in user
        assert "出题优先级" in user

    @pytest.mark.asyncio
    async def test_no_gap_block_when_absent(self, monkeypatch):
        captured = {}

        def _chat_json(system, user, *a, **kw):
            captured["user"] = user
            return {"questions": []}

        llm = MagicMock()
        llm.chat_json = _chat_json
        monkeypatch.setattr(qg, "_build_market_context_block", AsyncMock(return_value=""))

        await qg.generate_round_questions(
            llm_client=llm, resume_text="r", jd_text="j",
            round_idx=1, round_name="技术广度", count=3,
        )
        assert "JD 匹配缺口" not in captured.get("user", "")

    def test_session_carries_jd_gaps(self):
        s = _make_session(jd_gaps=["分布式：缺失", "  ", "高并发：偏弱"])
        assert s.jd_gaps == ["分布式：缺失", "高并发：偏弱"]


# ==================== P1-3 压力题库 ====================

class TestPressureBank:
    def test_bank_has_five_topics(self):
        qs = list_questions()
        assert len({q["topic"] for q in qs}) == 5
        assert len(qs) >= 15

    def test_sample_avoids_duplicates_and_stops_when_exhausted(self):
        all_q = [q["question"] for q in list_questions()]
        picked = sample_questions(1, exclude=all_q, rng=random.Random(0))
        assert picked == []

    def test_sample_spreads_topics(self):
        picked = sample_questions(3, rng=random.Random(7))
        assert len(picked) == 3
        assert len({p["topic"] for p in picked}) == 3

    def test_gate_break_round_never_injects(self, monkeypatch):
        monkeypatch.setattr(random, "random", lambda: 0.0)  # 抽签必中
        s = _make_session(interview_style="pressure")
        s.current_round = 0
        assert len(s._maybe_inject_pressure([{"question": "a"}])) == 1

    def test_gate_closing_round_never_injects(self, monkeypatch):
        monkeypatch.setattr(random, "random", lambda: 0.0)
        s = _make_session(interview_style="pressure")
        s.current_round = len(s.rounds) - 1
        assert len(s._maybe_inject_pressure([{"question": "a"}])) == 1

    def test_gate_friendly_style_never_injects(self, monkeypatch):
        """友好型注入概率为 0：否则会出现人设撕裂。"""
        monkeypatch.setattr(random, "random", lambda: 0.0)
        s = _make_session(interview_style="friendly")
        s.current_round = 1
        assert len(s._maybe_inject_pressure([{"question": "a"}])) == 1

    def test_injects_when_prob_hit(self, monkeypatch):
        monkeypatch.setattr(random, "random", lambda: 0.0)
        s = _make_session(interview_style="pressure")
        s.current_round = 1
        out = s._maybe_inject_pressure([{"question": "普通题"}])
        assert len(out) == 2
        assert out[1]["is_pressure"] is True
        assert out[1]["intent"]
        assert s.pressure_injected == 1

    def test_injected_pressure_is_registered_for_dedup(self, monkeypatch):
        """压力题必须进入已问题目台账，否则换题可能换出同一道。"""
        monkeypatch.setattr(random, "random", lambda: 0.0)
        s = _make_session(interview_style="pressure")
        s.current_round = 1
        questions = s._maybe_inject_pressure([{"question": "普通题"}])
        s._note_asked_questions(questions)
        assert s._is_duplicate_question(questions[1]["question"]) is True


# ==================== P1-4 恢复态红线与 assisted 标记 ====================

class TestRecoveryGuards:
    def test_answer_leak_detection(self):
        assert contains_answer_leak("参考答案是这样的：先说背景再说结果")
        assert contains_answer_leak("正确答案应该是使用连接池")
        assert not contains_answer_leak("你先想想这个问题的核心在问什么")

    def test_streak_counts_consecutive_only(self):
        s = _make_session()
        for _ in range(RECOVERY_SKIP_THRESHOLD):
            s._update_recovery_streak(True)
        assert s.recovery_streak == RECOVERY_SKIP_THRESHOLD
        assert s.recovery_total == RECOVERY_SKIP_THRESHOLD
        s._update_recovery_streak(False)
        assert s.recovery_streak == 0           # 正常回答归零
        assert s.recovery_total == RECOVERY_SKIP_THRESHOLD  # 总次数保留

    def test_skip_advice_fires_once(self):
        s = _make_session()
        s.recovery_streak = RECOVERY_SKIP_THRESHOLD
        assert s._guard_recovery_output("原追问", True) == RECOVERY_SKIP_ADVICE
        assert s._recovery_advice_done is True
        # 只建议一次，不能每题都来一遍
        assert s._guard_recovery_output("第二次追问", True) == "第二次追问"

    def test_leak_replaced_by_guidance_in_recovery(self):
        s = _make_session()
        out = s._guard_recovery_output("参考答案应该这样写：先说背景", True)
        assert out == RECOVERY_FALLBACK_PROMPT

    def test_non_recovery_output_not_touched(self):
        """非恢复态不得误伤正常话术。"""
        s = _make_session()
        text = "你刚才提到 QPS 提升了 3 倍，这个数字怎么测的？"
        assert s._guard_recovery_output(text, False) == text

    def test_should_follow_up_allows_advice_beyond_cap(self):
        """建议跳过是保护性干预，必须能突破追问次数上限。"""
        s = _make_session()
        s.follow_up_count = 99
        s.recovery_streak = RECOVERY_SKIP_THRESHOLD
        assert s.should_follow_up("", {}) is True

    @pytest.mark.asyncio
    async def test_assisted_flag_recorded(self):
        s = _make_session()
        s.round_questions = [{"question": "Q1"}]
        s.current_question_idx = 0
        await s.handle_answer("这个我不会，没思路")
        assert s.all_diagnoses[-1]["assisted"] is True

    @pytest.mark.asyncio
    async def test_normal_answer_not_marked_assisted(self):
        s = _make_session()
        s.round_questions = [{"question": "Q1"}]
        s.current_question_idx = 0
        await s.handle_answer("我用了 Redis 缓存，QPS 提升了 3 倍。")
        assert s.all_diagnoses[-1]["assisted"] is False

    def test_report_carries_assistance_stats(self):
        s = _make_session()
        s.round_questions = [{"question": "Q1"}, {"question": "Q2"}]
        s.current_question_idx = 0
        dims = {k: 3 for k in DIM_KEYS}
        s.record_answer("不会", {"dimensions": dict(dims), "overall_score": 3}, 0,
                        assisted=True)
        s.record_answer("正常回答", {"dimensions": dict(dims), "overall_score": 4}, 0)

        rep = build_report(s)
        assert rep["assistance_stats"]["total"] == 2
        assert rep["assistance_stats"]["assisted_count"] == 1
        assert rep["assistance_stats"]["assisted_ratio"] == 0.5
        assert rep["qa_breakdown"][0]["assisted"] is True
        assert rep["qa_breakdown"][1]["assisted"] is False
        assert rep["pressure_questions_injected"] == 0
