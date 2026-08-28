"""
question_gen.py 测试：
- 系统提示词 / 焦点维度映射
- _extract_keyword_from_text（关键词命中）
- _build_market_context_block（市场数据块拼接）
- generate_round_questions / generate_coach_tip / generate_questions
  通过 mock llm_client 并捕获传入 prompt，验证题型占比 / 弱项定向 / 市场数据注入
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend import question_gen as question_gen_mod
from backend.question_gen import (
    FOCUS_DIMENSION_NAMES,
    FOCUS_DIMENSION_PROMPTS,
    ROUND_PROMPTS,
    TRADITIONAL_ROUND_PROMPTS,
    _build_market_context_block,
    _extract_keyword_from_text,
    generate_coach_tip,
    generate_questions,
    generate_round_questions,
    get_question_gen_system_prompt,
)


def _fake_llm(return_value):
    llm = MagicMock()
    llm.chat_json = MagicMock(return_value=return_value)
    return llm


def _no_market():
    """屏蔽真实 market.db 查询，保证市场块注入可断言。"""
    return patch.object(question_gen_mod, "_build_market_context_block",
                        AsyncMock(return_value=""))


class TestSystemPromptAndMaps:
    def test_system_prompt(self):
        assert "资深技术面试官" in get_question_gen_system_prompt()

    def test_focus_dimension_maps(self):
        assert set(FOCUS_DIMENSION_PROMPTS.keys()) == set(FOCUS_DIMENSION_NAMES.keys())
        for v in FOCUS_DIMENSION_PROMPTS.values():
            assert v

    def test_round_prompt_sets(self):
        assert set(ROUND_PROMPTS.keys()) == set(range(6))
        assert set(TRADITIONAL_ROUND_PROMPTS.keys()) == set(range(5))


class TestExtractKeyword:
    @pytest.mark.asyncio
    @patch("backend.market.store.list_keywords")
    async def test_match(self, mock_list):
        mock_list.return_value = ["python", "java", "go"]
        assert await _extract_keyword_from_text("我熟悉 python 与 django") == "python"
        assert await _extract_keyword_from_text("精通 java 与 python") == "python"

    @pytest.mark.asyncio
    @patch("backend.market.store.list_keywords")
    async def test_no_match(self, mock_list):
        mock_list.return_value = ["python", "java"]
        assert await _extract_keyword_from_text("没有任何相关技术栈") == ""

    @pytest.mark.asyncio
    async def test_empty_text(self):
        assert await _extract_keyword_from_text("") == ""

    @pytest.mark.asyncio
    @patch("backend.market.store.list_keywords")
    async def test_store_error(self, mock_list):
        mock_list.side_effect = Exception("db down")
        assert await _extract_keyword_from_text("python 开发") == ""


class TestMarketBlock:
    @pytest.mark.asyncio
    @patch("backend.market.store.list_keywords")
    async def test_no_keyword_returns_empty(self, mock_list):
        mock_list.return_value = []
        assert await _build_market_context_block("任意岗位描述") == ""

    @pytest.mark.asyncio
    @patch("backend.market.store.list_keywords")
    @patch("backend.market.store.get_stats")
    @patch("backend.market.store.query_jobs")
    async def test_block_built(self, mock_jobs, mock_stats, mock_list):
        mock_list.return_value = ["python"]
        mock_stats.return_value = {
            "total": 5,
            "top_skills": [{"skill": "python"}],
            "education_distribution": [{"education": "本科", "cnt": 3}],
            "avg_salary": {"avg_k": 15, "min_k": 8, "max_k": 25},
        }
        mock_jobs.return_value = {"items": [{"company": "示例科技"}]}
        block = await _build_market_context_block("招 python 工程师")
        assert "【市场参考数据】" in block
        assert "python" in block
        assert "示例科技" in block
        assert "15K" in block

    @pytest.mark.asyncio
    @patch("backend.market.store.list_keywords")
    @patch("backend.market.store.get_stats")
    async def test_zero_total_returns_empty(self, mock_stats, mock_list):
        mock_list.return_value = ["python"]
        mock_stats.return_value = {"total": 0}
        assert await _build_market_context_block("招 python 工程师") == ""


class TestGenerateRoundQuestions:
    @pytest.mark.asyncio
    async def test_basic(self):
        llm = _fake_llm({"questions": [
            {"question": "Q1", "reference_answer": "A1", "question_type": "knowledge"}
        ]})
        with _no_market():
            qs = await generate_round_questions(llm, "简历内容", "后端岗位JD", 1, "技术广度", 3)
        assert len(qs) == 1
        assert qs[0]["question"] == "Q1"
        prompt = llm.chat_json.call_args.args[1]
        assert "生成 3 道技术广度问题" in prompt
        assert "【题型占比偏好】" not in prompt
        assert "【本题为弱项补强题" not in prompt

    @pytest.mark.asyncio
    async def test_market_block_injection(self):
        llm = _fake_llm({"questions": [{"question": "M1"}]})
        with patch.object(question_gen_mod, "_build_market_context_block",
                          AsyncMock(return_value="\n\n【市场参考数据】（关键词=python，共 5 条岗位）")):
            await generate_round_questions(llm, "简历", "python 岗位", 1, "技术广度", 2)
        prompt = llm.chat_json.call_args.args[1]
        assert "【市场参考数据】" in prompt

    @pytest.mark.asyncio
    async def test_focus_dimension(self):
        llm = _fake_llm({"questions": [{"question": "F1"}]})
        qs = await generate_round_questions(
            llm, "简历", "JD", 0, "破冰环节", 1,
            focus_dimension="quantification", weak_evidence="缺少数字",
        )
        assert qs[0]["focus_dimension"] == "quantification"
        assert qs[0]["focus_dimension_name"] == FOCUS_DIMENSION_NAMES["quantification"]
        prompt = llm.chat_json.call_args.args[1]
        assert "【本题为弱项补强题" in prompt
        assert "量化程度" in prompt
        assert "缺少数字" in prompt

    @pytest.mark.asyncio
    async def test_type_mix(self):
        llm = _fake_llm({"questions": [{"question": "T1"}]})
        with _no_market():
            await generate_round_questions(
                llm, "简历", "JD", 1, "技术广度", 2,
                type_mix={"knowledge": 60, "project": 20, "behavior": 20},
            )
        prompt = llm.chat_json.call_args.args[1]
        assert "【题型占比偏好】" in prompt

    @pytest.mark.asyncio
    async def test_traditional_mode(self):
        llm = _fake_llm({"questions": [{"question": "TR"}]})
        with _no_market():
            await generate_round_questions(llm, "简历", "JD", 2, "技术二面", 3, mode="traditional")
        prompt = llm.chat_json.call_args.args[1]
        assert "技术二面" in prompt

    @pytest.mark.asyncio
    async def test_chat_json_error_returns_empty(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(side_effect=Exception("llm down"))
        assert await generate_round_questions(llm, "简历", "JD", 1, "技术广度", 2) == []


class TestCoachTip:
    @pytest.mark.asyncio
    async def test_basic(self):
        llm = _fake_llm({"question": "讲解标题", "intent": "讲解正文"})
        res = await generate_coach_tip(llm, "简历", "JD", "技术广度")
        assert res["question_type"] == "coach_tip"
        assert res["index"] == -2
        prompt = llm.chat_json.call_args.args[1]
        assert "技术广度" in prompt

    @pytest.mark.asyncio
    async def test_error_returns_none(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(side_effect=Exception("x"))
        assert await generate_coach_tip(llm, "简历", "JD", "技术广度") is None

    @pytest.mark.asyncio
    async def test_missing_question_returns_none(self):
        llm = _fake_llm({"intent": "只有正文"})
        assert await generate_coach_tip(llm, "简历", "JD", "技术广度") is None


class TestGenerateQuestionsV1:
    @pytest.mark.asyncio
    async def test_basic(self):
        payload = {"jd_keywords": ["python"], "questions": [{"question": "Q"}]}
        llm = _fake_llm(payload)
        with _no_market():
            assert await generate_questions(llm, "JD", "RESUME") == payload

    @pytest.mark.asyncio
    async def test_non_dict_returns_empty(self):
        llm = _fake_llm("not a dict")
        with _no_market():
            assert await generate_questions(llm, "JD", "RESUME") == \
                {"jd_keywords": [], "questions": []}

    @pytest.mark.asyncio
    async def test_error_returns_empty(self):
        llm = MagicMock()
        llm.chat_json = MagicMock(side_effect=Exception("x"))
        with _no_market():
            res = await generate_questions(llm, "JD", "RESUME")
        assert res == {"jd_keywords": [], "questions": []}
