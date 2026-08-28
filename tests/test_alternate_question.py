"""
v6.3 备选题 / 换题测试（借鉴 HakiMeet 的"随机备选题 + 注入去重"机制）。

本项目的题目由 LLM 生成（非固定题库抽取），因此"备选题"落地为两条规程：
1. 出题/换题时把本次会话已问过的题目作为【已问题目清单·严禁重复】负向约束传入；
2. 模型无视约束又吐出重复题时，把那道重复题追加进排除清单重试**一次**——
   给出具体反例比反复强调规则有效，但重试有 LLM 往返成本，故只做一次。

覆盖：已问题台账、出题侧传参、换题重试与重试上限、登记防连续重复。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.interview_engine import session as session_mod
from backend.interview_engine.session import InterviewSession
from backend.resume_retriever import content_hash


def _make_session(**overrides) -> tuple:
    llm = MagicMock()
    llm.chat = MagicMock(return_value="生成追问")
    diag = MagicMock()
    diag.diagnose = AsyncMock(return_value={"overall_score": 3, "dimensions": {}})
    kwargs = dict(
        session_id="s1",
        resume_text="3 年 Python 开发经验",
        jd_text="招聘 Python 后端工程师",
        llm_client=llm,
        diagnosis_engine=diag,
        db=MagicMock(),
        mode="simulation",
    )
    kwargs.update(overrides)
    return InterviewSession(**kwargs), llm, diag


class TestAskedQuestionLedger:
    def test_avoid_payload_empty_initially(self):
        s, _, _ = _make_session()
        assert s.avoid_questions_payload() == []

    def test_note_records_text_and_fingerprint(self):
        s, _, _ = _make_session()
        s._note_asked_questions([{"question": "讲讲你的 RAG 项目"}])
        assert s.asked_questions == ["讲讲你的 RAG 项目"]
        assert content_hash("讲讲你的 RAG 项目") in s.asked_question_hashes

    def test_note_skips_invalid_entries(self):
        s, _, _ = _make_session()
        s._note_asked_questions([
            None,
            {"no_question_key": "x"},
            {"question": "   "},
            "not a dict",
            {"question": "有效题目"},
        ])
        assert s.asked_questions == ["有效题目"]

    def test_is_duplicate_semantics(self):
        s, _, _ = _make_session()
        s._note_asked_questions([{"question": "讲讲 RAG"}])
        assert s._is_duplicate_question("讲讲 RAG") is True
        assert s._is_duplicate_question("讲讲缓存") is False
        assert s._is_duplicate_question("") is False

    def test_avoid_payload_respects_limit(self):
        s, _, _ = _make_session()
        s._note_asked_questions([{"question": f"题目{i}"} for i in range(10)])
        assert len(s.avoid_questions_payload(limit=3)) == 3
        assert s.avoid_questions_payload(limit=3) == ["题目7", "题目8", "题目9"]


class TestGenerateQuestionsPassesAvoidList:
    @pytest.mark.asyncio
    async def test_first_call_sends_empty_avoid_list(self):
        s, _, _ = _make_session()
        captured = {}

        async def fake(**kwargs):
            captured.update(kwargs)
            return [{"question": "第一题", "intent": "了解背景",
                     "question_type": "knowledge"}]

        with patch.object(session_mod, "generate_round_questions",
                          new=AsyncMock(side_effect=fake)):
            await s.generate_questions()

        assert captured["avoid_questions"] == []
        assert s.avoid_questions_payload() == ["第一题"]

    @pytest.mark.asyncio
    async def test_later_call_carries_previously_asked(self):
        s, _, _ = _make_session()

        async def fake(**kwargs):
            return [{"question": f"题目{len(s.asked_questions)}",
                     "intent": "考察", "question_type": "knowledge"}]

        mock = AsyncMock(side_effect=fake)
        with patch.object(session_mod, "generate_round_questions", new=mock):
            await s.generate_questions()
            s.current_round = 1
            await s.generate_questions()

        assert mock.await_count == 2
        assert mock.call_args.kwargs["avoid_questions"] == ["题目0"]
        assert s.asked_questions == ["题目0", "题目1"]


class TestGenerateExtraQuestionDedup:
    @pytest.mark.asyncio
    async def test_retries_once_with_duplicate_sample(self):
        s, _, _ = _make_session()
        s._note_asked_questions([{"question": "讲讲你的 RAG 项目"}])
        mock = AsyncMock(side_effect=[
            [{"question": "讲讲你的 RAG 项目"}],      # 模型无视约束，重复
            [{"question": "讲讲缓存雪崩怎么应对"}],     # 带上反例后给出新题
        ])
        with patch.object(session_mod, "generate_round_questions", new=mock):
            q = await s.generate_extra_question()

        assert q is not None
        assert q["question"] == "讲讲缓存雪崩怎么应对"
        assert mock.await_count == 2
        # 重试时排除清单里应带上那道重复题作为反例
        assert "讲讲你的 RAG 项目" in mock.call_args.kwargs["avoid_questions"]

    @pytest.mark.asyncio
    async def test_retry_happens_only_once(self):
        """重试仍重复时不再继续重试，避免无限 LLM 往返。"""
        s, _, _ = _make_session()
        s._note_asked_questions([{"question": "讲讲你的 RAG 项目"}])
        mock = AsyncMock(return_value=[{"question": "讲讲你的 RAG 项目"}])
        with patch.object(session_mod, "generate_round_questions", new=mock):
            q = await s.generate_extra_question()

        assert mock.await_count == 2, "最多重试一次"
        assert q is not None and q["question"] == "讲讲你的 RAG 项目"

    @pytest.mark.asyncio
    async def test_no_retry_when_question_is_new(self):
        s, _, _ = _make_session()
        s._note_asked_questions([{"question": "讲讲你的 RAG 项目"}])
        mock = AsyncMock(return_value=[{"question": "讲讲分布式事务"}])
        with patch.object(session_mod, "generate_round_questions", new=mock):
            q = await s.generate_extra_question()

        assert mock.await_count == 1
        assert q["question"] == "讲讲分布式事务"
        # 换出的题同样登记，防止连续换出同一道
        assert s._is_duplicate_question("讲讲分布式事务") is True
