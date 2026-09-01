"""
v6.2 借鉴 GrillMind 的能力落地测试（对应《GrillMind-深度研读.md》第 9 节 6 条）：

  1. 面试状态机：closing 收尾阶段的工程强控（轮次计数推进 + 内部收尾指令注入）
  2. 简历解析前置追问点：deepDivePoints / vaguePoints
  3. Prompt 输出约束：禁 Markdown / 禁括号动作 / 禁垫词开头（含工程净化兜底）
  4. 任务级模型绑定 + 面试禁思考（实时链路剔除推理类模型）
  5. 报告结构：qaBreakdown 逐题 + realInterviewImpact + thinkingSeconds
  6. 语音链路：VAD 节流与 TTS 结束回调属前端能力，由 vite build 与人工联调覆盖

测试约定：不依赖真实 LLM，全部用 MagicMock / monkeypatch 隔离。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import question_gen as qg
from backend.config import config
from backend.diagnosis_engine import (
    DIAGNOSTICIAN_SYSTEM_PROMPT,
    REWRITER_SYSTEM_PROMPT,
    _build_diagnostician_system,
    normalize_result,
)
from backend.interview_engine.report import (
    _fallback_impact,
    _norm_thinking,
    build_report,
)
from backend.interview_engine.session import (
    _normalize_thinking_seconds,
    InterviewSession,
)
from backend.llm_client import LLMClient, _Candidate, is_reasoning_model
from backend.output_sanitizer import (
    OUTPUT_CONSTRAINTS,
    sanitize_spoken_text,
    strip_leading_fillers,
    strip_markdown,
    strip_stage_actions,
)
from backend.resume_parser import extract_interview_points


def _make_session(**overrides):
    llm = MagicMock()
    llm.chat = MagicMock(return_value="生成追问")
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


# ==================== 1. 面试状态机：closing 收尾强控 ====================

class TestClosingPhase:
    def test_last_round_marked_closing(self):
        """收尾轮在轮次配置里被显式标记 closing。"""
        assert config.INTERVIEW_ROUNDS[-1].get("closing") is True
        assert config.TRADITIONAL_ROUNDS[-1].get("closing") is True

    def test_is_closing_round_by_index(self):
        s = _make_session()
        assert s.is_closing_round() is False          # 第 0 轮
        s.current_round = len(s.rounds) - 1
        assert s.is_closing_round() is True
        s.current_round = len(s.rounds)               # 已结束
        assert s.is_closing_round() is True

    def test_closing_instruction_only_on_closing(self):
        s = _make_session()
        assert s.closing_instruction() == ""
        s.current_round = len(s.rounds) - 1
        assert s.closing_instruction()  # 收尾轮必须有指令；具体文案是配置实现细节

    def test_follow_up_forbidden_on_closing(self):
        """收尾阶段一律不追问 —— 连"回答过短强制追问"也被强控掉。"""
        s = _make_session()
        s.current_round = len(s.rounds) - 1
        assert s.should_follow_up("太短", {"follow_up_question": "再展开？"}) is False
        assert s.should_follow_up("太短", {"overall_score": 1.0}) is False

    @pytest.mark.asyncio
    async def test_no_extra_question_on_closing(self):
        s = _make_session()
        s.current_round = len(s.rounds) - 1
        assert await s.generate_extra_question() is None

    @pytest.mark.asyncio
    async def test_closing_instruction_injected_into_prompt(self):
        """收尾指令必须真的进入出题 prompt，而不是只存在于配置里。"""
        llm = MagicMock()
        llm.chat_json = MagicMock(return_value={"questions": [
            {"index": 0, "question": "你有什么想问我们的吗？", "intent": "收尾",
             "question_type": "behavior"},
        ]})
        await qg.generate_round_questions(
            llm_client=llm, resume_text="简历", jd_text="JD",
            round_idx=5, round_name="反问收尾", count=1,
            closing_instruction=config.CLOSING_INSTRUCTION,
        )
        user_prompt = llm.chat_json.call_args[0][1]
        assert "收尾阶段" in user_prompt

    def test_closing_message_configured(self):
        assert "面试到此结束" in config.CLOSING_MESSAGE


# ==================== 2. 简历解析前置追问点 ====================

class TestResumePoints:
    def test_extract_success(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(return_value={
            "deep_dive_points": ["提到 P99 优化但未说明手段", "负责架构设计需核实边界"],
            "vague_points": ["参与项目但无个人贡献"],
        })
        out = extract_interview_points("三年 Python 经验" * 20, llm)
        assert len(out["deep_dive_points"]) == 2
        assert out["vague_points"] == ["参与项目但无个人贡献"]

    def test_extract_degrades_on_failure(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(side_effect=RuntimeError("boom"))
        assert extract_interview_points("简历内容", llm) == {}

    def test_extract_skipped_on_short_resume(self):
        llm = MagicMock()
        assert extract_interview_points("太短", llm) == {}
        assert extract_interview_points("", llm) == {}
        assert extract_interview_points("内容", None) == {}
        llm.chat_json.assert_not_called()

    def test_extract_cleans_and_dedups(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(return_value={
            "deep_dive_points": ["  - 点A ", "点A", "", "x" * 200, "点B"],
            "vague_points": "not a list",
        })
        out = extract_interview_points("简历内容" * 50, llm)
        # 去空白/去列表符/去重/丢弃超长项
        assert out["deep_dive_points"] == ["点A", "点B"]
        assert out["vague_points"] == []

    def test_extract_returns_empty_when_nothing_usable(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(return_value={"deep_dive_points": [], "vague_points": []})
        assert extract_interview_points("简历内容" * 50, llm) == {}

    def test_points_block_rendering(self):
        block = qg.build_resume_points_block({
            "deep_dive_points": ["点A"], "vague_points": ["点B"],
        })
        assert "简历前置追问点" in block
        assert "点A" in block and "点B" in block
        # 空 / 非法输入不产生注入片段
        assert qg.build_resume_points_block({}) == ""
        assert qg.build_resume_points_block(None) == ""
        assert qg.build_resume_points_block("bad") == ""

    def test_points_flow_into_session_evidence(self):
        """追问点要进入诊断证据包，追问才有据可依。"""
        s = _make_session(resume_points={"deep_dive_points": ["点A"]})
        evidence = s._evidence_for("我做过缓存优化")
        assert "点A" in evidence


# ==================== 3. Prompt 输出约束 + 工程净化 ====================

class TestOutputConstraints:
    def test_constraints_injected_into_prompts(self):
        assert "禁 Markdown" in qg.get_question_gen_system_prompt()
        assert "禁 Markdown" in REWRITER_SYSTEM_PROMPT
        # Diagnostician 是 format 模板，约束以占位符注入，运行时展开
        assert "{output_constraints}" in DIAGNOSTICIAN_SYSTEM_PROMPT
        assert "禁 Markdown" in _build_diagnostician_system(None)

    def test_diagnostician_asks_real_interview_impact(self):
        """借鉴点 5：诊断 prompt 必须要求产出 real_interview_impact 字段。"""
        assert "real_interview_impact" in DIAGNOSTICIAN_SYSTEM_PROMPT
        assert "真实面试" in DIAGNOSTICIAN_SYSTEM_PROMPT

    def test_strip_markdown(self):
        assert strip_markdown("**重点**问题") == "重点问题"
        assert strip_markdown("## 标题") == "标题"
        assert strip_markdown("- 列表项") == "列表项"
        assert strip_markdown("`code`") == "code"

    def test_strip_stage_actions_keeps_term_parentheses(self):
        assert strip_stage_actions("（微笑）请介绍一下") == "请介绍一下"
        assert strip_stage_actions("*停顿*继续") == "继续"
        # 术语括号必须保留，否则会破坏题目信息
        assert strip_stage_actions("Redis（缓存）用过吗") == "Redis（缓存）用过吗"
        assert strip_stage_actions("RAG（检索增强生成）了解吗") == "RAG（检索增强生成）了解吗"

    def test_strip_leading_fillers(self):
        assert strip_leading_fillers("好的，你刚才提到 Redis") == "你刚才提到 Redis"
        assert strip_leading_fillers("嗯，我们来聊聊项目") == "我们来聊聊项目"
        # 垫词后无标点时不剥离，避免误伤实义表达
        assert strip_leading_fillers("好问题，值得展开") == "好问题，值得展开"

    def test_sanitize_pipeline(self):
        out = sanitize_spoken_text("好的，**（微笑）**请介绍一下 P99（延迟指标）")
        assert "**" not in out and "微笑" not in out
        assert out.startswith("请介绍一下")
        assert "P99（延迟指标）" in out

    def test_sanitize_safe_on_bad_input(self):
        assert sanitize_spoken_text("") == ""
        assert sanitize_spoken_text(None) == ""

    def test_diagnosis_output_is_sanitized(self):
        res = normalize_result(
            {
                "follow_up_question": "好的，**你刚才提到 Redis**，能展开吗（停顿）",
                "overall_comment": "**整体不错**",
                "real_interview_impact": "嗯，**真实面试会被追问**",
            },
            {"rewritten_answer": "**改写后**的回答"},
            None,
        )
        assert "**" not in res["follow_up_question"]
        assert res["follow_up_question"].startswith("你刚才提到 Redis")
        assert "**" not in res["overall_comment"]
        assert "**" not in res["real_interview_impact"]
        assert "**" not in res["rewritten_answer"]


# ==================== 4. 任务级模型绑定 + 面试禁思考 ====================

def _cand(model="m", provider="p"):
    return _Candidate(provider=provider, model=model,
                      client=MagicMock(), async_client=MagicMock())


def _client_with(candidates):
    client = LLMClient(provider="deepseek")
    client._candidates = candidates
    return client


class TestReasoningModelDetection:
    def test_reasoning_models(self):
        for m in ("deepseek-reasoner", "o1-mini", "qwen3-thinking", "glm-z1"):
            assert is_reasoning_model(m) is True

    def test_normal_models(self):
        for m in ("deepseek-chat", "qwen-plus", "glm-4-flash", "gpt-4o-mini"):
            assert is_reasoning_model(m) is False

    def test_empty(self):
        assert is_reasoning_model("") is False
        assert is_reasoning_model(None) is False


class TestTaskModelBinding:
    def test_parse_valid(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_MODELS",
                           json.dumps({"diagnosis": "deepseek-chat", "report": "qwen:qwen-max"}))
        m = config.LLM_TASK_MODELS
        assert m["diagnosis"]["model"] == "deepseek-chat"
        assert m["report"]["provider"] == "qwen"
        assert m["report"]["model"] == "qwen-max"

    def test_parse_invalid_json(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_MODELS", "{not json")
        assert config.LLM_TASK_MODELS == {}

    def test_skip_unknown_task_and_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_MODELS",
                           json.dumps({"unknown_task": "x", "report": "nope:qwen-max"}))
        assert config.LLM_TASK_MODELS == {}

    def test_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("LLM_TASK_MODELS", raising=False)
        assert config.LLM_TASK_MODELS == {}

    def test_no_task_returns_global_pool(self):
        client = _client_with([_cand("a"), _cand("b")])
        assert [c.model for c in client.task_candidates(None)] == ["a", "b"]

    def test_realtime_tasks_skip_reasoning(self):
        """面试是实时链路：推理类模型被剔除，保证低延迟。"""
        client = _client_with([_cand("deepseek-reasoner"), _cand("deepseek-chat")])
        got = client.task_candidates("diagnosis")
        assert [c.model for c in got] == ["deepseek-chat"]

    def test_offline_tasks_keep_reasoning(self):
        """报告/规划类离线任务不受禁思考限制。"""
        client = _client_with([_cand("deepseek-reasoner")])
        got = client.task_candidates("report")
        assert [c.model for c in got] == ["deepseek-reasoner"]

    def test_keep_pool_when_only_reasoning_available(self):
        """只配了推理模型时不能把候选清空 —— 宁可慢，也不能没候选。"""
        client = _client_with([_cand("deepseek-reasoner")])
        got = client.task_candidates("diagnosis")
        assert len(got) == 1

    def test_binding_skipped_when_key_invalid(self, monkeypatch):
        """绑定模型的 Key 无效时应回退默认池，而不是构造一个必然失败的候选。"""
        monkeypatch.setenv("LLM_TASK_MODELS", json.dumps({"report": "qwen:qwen-max"}))
        monkeypatch.setenv("QWEN_API_KEY", "")       # 清空 Key
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        client = _client_with([_cand("main-model")])
        assert [c.model for c in client.task_candidates("report")] == ["main-model"]

    def test_realtime_binding_rejects_reasoning(self, monkeypatch):
        """给实时链路绑定推理模型时按禁思考策略跳过。"""
        monkeypatch.setenv("LLM_TASK_MODELS", json.dumps({"diagnosis": "deepseek-reasoner"}))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
        client = _client_with([_cand("deepseek-chat", "deepseek")])
        assert [c.model for c in client.task_candidates("diagnosis")] == ["deepseek-chat"]

    def test_resolve_task_model(self):
        client = _client_with([_cand("main-model")])
        assert client.resolve_task_model() == "main-model"
        assert client.resolve_task_model("report") == "main-model"


# ==================== 5. 报告结构：逐题拆解 ====================

def _diag(question="介绍一下你的项目", score=4.0, thinking=12.0, impact="",
          rewritten="改写后的回答", round_idx=0):
    return {
        "round": round_idx,
        "round_name": "项目拷问",
        "question": question,
        "overall_score": score,
        "dimensions": {
            "star_completeness": score, "quantification": score,
            "logic_coherence": score, "job_relevance": score,
            "professional_depth": score,
        },
        "weakest_dimension": "quantification",
        "weakest_dimension_name": "量化程度",
        "overall_comment": "整体不错",
        "real_interview_impact": impact,
        "thinking_seconds": thinking,
        "risk_points": ["指标来源未说明"],
        "rewritten_answer": rewritten,
        "key_changes": ["补了数据"],
    }


def _fake_session(diagnoses, resume_points=None):
    return SimpleNamespace(
        session_id="s1", mode="simulation", stage="tech_round_1",
        style="friendly", interviewer_history=[],
        rounds=config.INTERVIEW_ROUNDS, all_diagnoses=diagnoses,
        dim_weights=None, _weakness_counts={"量化不足": 2},
        resume_points=resume_points or {},
        weight_reason="", weight_source="default",
    )


class TestThinkingSeconds:
    def test_normalize_valid(self):
        assert _normalize_thinking_seconds(12.34) == 12.3
        assert _normalize_thinking_seconds("30") == 30.0

    def test_normalize_invalid(self):
        for bad in (None, "", "abc", -5, 99999, float("nan")):
            assert _normalize_thinking_seconds(bad) == 0.0

    def test_report_norm_thinking(self):
        assert _norm_thinking("abc") == 0.0
        assert _norm_thinking(-1) == 0.0
        assert _norm_thinking(8) == 8.0

    def test_record_answer_keeps_thinking(self):
        s = _make_session()
        s.round_questions = [{"question": "Q1", "question_type": "project"}]
        s.current_question_idx = 0
        s.record_answer("回答", {"overall_score": 3}, 15.5)
        assert s.answer_history[-1]["thinking_seconds"] == 15.5
        assert s.all_diagnoses[-1]["thinking_seconds"] == 15.5

    def test_follow_up_accumulates_thinking(self):
        s = _make_session()
        s.round_questions = [{"question": "Q1", "question_type": "project"}]
        s.current_question_idx = 0
        s.record_answer("回答", {"overall_score": 3}, 10.0)
        s.handle_follow_up_answer("补充", 5.0)
        assert s.answer_history[-1]["thinking_seconds"] == 15.0
        assert s.all_diagnoses[-1]["thinking_seconds"] == 15.0


class TestQaBreakdown:
    def test_breakdown_shape(self):
        report = build_report(_fake_session([_diag()]))
        qa = report["qa_breakdown"]
        assert len(qa) == 1
        item = qa[0]
        assert item["index"] == 1
        assert item["question"] == "介绍一下你的项目"
        assert item["overall_score"] == 4.0
        assert item["thinking_seconds"] == 12.0
        assert item["weakest_dimension"] == "quantification"
        assert item["real_interview_impact"]
        assert set(item["dimensions"].keys()) == {
            "star_completeness", "quantification", "logic_coherence",
            "job_relevance", "professional_depth",
        }
        assert item["has_rewrite"] is True

    def test_thinking_stats(self):
        report = build_report(_fake_session([
            _diag(question="Q1", thinking=10.0),
            _diag(question="Q2", thinking=30.0, round_idx=1),
        ]))
        st = report["thinking_stats"]
        assert st["answered_count"] == 2
        assert st["tracked_count"] == 2
        assert st["avg_seconds"] == 20.0
        assert st["max_seconds"] == 30.0
        assert st["min_seconds"] == 10.0

    def test_reassessment_fields_exposed(self):
        """v8.6: 补评过的题必须同时给出终评与首评原分。

        只给终评等于让读者无从判断这个分数的成色——与 assisted（借助引导）、
        follow_up_skipped（跳过追问）是同一条诚实披露纪律。
        """
        d = _diag(score=4.0)
        d.update({
            "follow_up_reassessed": True,
            "pre_follow_up": {
                "dimensions": {"quantification": 2.0},
                "overall_score": 2.8,
                "weakest_dimension": "quantification",
            },
            "reassessment_delta": 1.2,
            "reassessment_note": "补充了转化率数据",
        })
        item = build_report(_fake_session([d]))["qa_breakdown"][0]
        assert item["follow_up_reassessed"] is True
        assert item["overall_score"] == 4.0
        assert item["pre_follow_up"]["overall_score"] == 2.8
        assert item["reassessment_delta"] == 1.2
        assert item["reassessment_note"] == "补充了转化率数据"

    def test_reassessment_stats(self):
        """补评统计要能看出"有几道题被重评、平均变动多少、有没有反而降分的"。"""
        up = _diag(question="Q1", score=4.5)
        up.update({"follow_up_reassessed": True, "reassessment_delta": 1.0,
                   "pre_follow_up": {"overall_score": 3.5}})
        down = _diag(question="Q2", score=2.0, round_idx=1)
        down.update({"follow_up_reassessed": True, "reassessment_delta": -0.5,
                     "pre_follow_up": {"overall_score": 2.5}})
        plain = _diag(question="Q3", score=3.0, round_idx=1)

        report = build_report(_fake_session([up, down, plain]))
        st = report["reassessment_stats"]
        assert st["total"] == 3
        assert st["reassessed_count"] == 2
        assert st["avg_delta"] == 0.25      # (1.0 + (-0.5)) / 2
        assert st["max_delta"] == 1.0
        assert st["min_delta"] == -0.5
        assert st["downgraded_questions"] == ["Q2"]
        # 补评作为复盘信号进建议，不混入打分链路
        assert "追问补充后" in report["suggestions"]

    def test_reassessment_stats_empty_when_no_reassessment(self):
        """没有补评时不产生统计噪音，也不往建议里塞无关内容。"""
        report = build_report(_fake_session([_diag()]))
        assert report["reassessment_stats"]["reassessed_count"] == 0
        assert report["reassessment_stats"]["avg_delta"] == 0
        assert "追问补充后" not in report["suggestions"]

    def test_real_impact_uses_model_output_when_present(self):
        report = build_report(_fake_session([_diag(impact="会被追问数据来源")]))
        assert report["qa_breakdown"][0]["real_interview_impact"] == "会被追问数据来源"

    def test_real_impact_fallback(self):
        """模型没产出时用规则兜底，字段不为空。"""
        report = build_report(_fake_session([_diag(impact="")]))
        assert "真实面试" in report["qa_breakdown"][0]["real_interview_impact"]

    def test_fallback_impact_rules(self):
        assert "耗时偏长" in _fallback_impact(4.5, 200)
        assert "追问" in _fallback_impact(4.5, 30)
        assert "不扣分" in _fallback_impact(3.2, 40)
        assert "低于通过线" in _fallback_impact(1.5, 20)
        assert "无法判断" in _fallback_impact(0, 0)

    def test_resume_points_in_report(self):
        points = {"deep_dive_points": ["点A"], "vague_points": ["点B"]}
        report = build_report(_fake_session([_diag()], resume_points=points))
        assert report["resume_points"]["deep_dive_points"] == ["点A"]

    def test_detailed_qa_aligned_with_breakdown(self):
        """detailed_qa 与 qa_breakdown 字段保持一致，前端可复用同一套渲染。"""
        report = build_report(_fake_session([_diag()]))
        dq = report["detailed_qa"][0]
        assert dq["thinking_seconds"] == 12.0
        assert dq["real_interview_impact"]

    def test_empty_session_report(self):
        report = build_report(_fake_session([]))
        assert report["qa_breakdown"] == []
        assert report["thinking_stats"]["answered_count"] == 0
        assert report["resume_points"] == {}
