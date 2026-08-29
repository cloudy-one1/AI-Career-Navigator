"""
diagnosis_engine 测试：聚焦 2026-08-13 整改后的行为。

覆盖：
- normalize_result 的 weakest_dimension 交叉校验（核心信任边界修复）
- _astream 直接消费 chat_stream_async（异步化重构冒烟）

诚实说明：本套件验证的是「工程正确性」（交叉校验逻辑 / 异步桥接是否替换成功），
不验证 LLM 实际打分质量——那是依赖外部模型输出、单测难以断言的部分。
"""
import pytest

from backend.diagnosis_engine import normalize_result, DIM_KEYS, _astream


def _build_diagnosis(scores: dict, weakest: str = "") -> dict:
    d = {k: {"score": v, "comment": "x"} for k, v in scores.items()}
    d["weakest_dimension"] = weakest
    d["follow_up_question"] = ""
    return d


BASE_SCORES = {
    "star_completeness": 4.0,
    "quantification": 2.0,
    "logic_coherence": 3.0,
    "job_relevance": 5.0,
    "professional_depth": 3.5,
}


class TestQuoteEvidence:
    """v7.0: 每维度评分依据（候选人原话摘录）的解析与容错。

    引入动机：没有依据的分数等于感觉，无法复核。quote 把打分锚到文本证据上，
    也让报告页能并排展示"分数 vs 原话"。
    """

    def test_quote_preserved(self):
        diag = _build_diagnosis(BASE_SCORES)
        diag["quantification"]["quote"] = "把响应时间从 800ms 降到 200ms"
        res = normalize_result(diag, {}, weights=None)
        assert res["dimension_details"]["quantification"]["quote"] == "把响应时间从 800ms 降到 200ms"

    def test_missing_quote_defaults_to_empty(self):
        """模型没返回 quote（老 prompt 缓存/降级模型）时补空串，不阻断诊断。

        这是向后兼容的底线：quote 是增强项，缺失不应影响任何既有流程。
        """
        diag = _build_diagnosis(BASE_SCORES)   # 辅助函数不带 quote
        res = normalize_result(diag, {}, weights=None)
        for key in DIM_KEYS:
            assert res["dimension_details"][key]["quote"] == ""

    def test_numeric_dimension_also_gets_quote_key(self):
        """LLM 直接给数字（不给字典）时，quote 键仍需存在且为空。"""
        diag = {k: 3.0 for k in DIM_KEYS}
        diag["weakest_dimension"] = ""
        diag["follow_up_question"] = ""
        res = normalize_result(diag, {}, weights=None)
        assert res["dimension_details"]["logic_coherence"]["quote"] == ""

    def test_non_string_quote_coerced(self):
        """模型返回非字符串（如数字/null）时强制转字符串，不让后续渲染崩。"""
        diag = _build_diagnosis(BASE_SCORES)
        diag["logic_coherence"]["quote"] = None
        diag["job_relevance"]["quote"] = 123
        res = normalize_result(diag, {}, weights=None)
        assert res["dimension_details"]["logic_coherence"]["quote"] == ""
        assert res["dimension_details"]["job_relevance"]["quote"] == "123"


class TestWeakestCrossCheck:
    """normalize_result 必须对模型自报的最薄弱维度与真实分数做交叉校验。"""

    def test_model_declares_wrong_dimension_overridden(self):
        # quantification=2 实际最低，但模型谎报 job_relevance（合法 key，但与分数不符）
        diag = _build_diagnosis(BASE_SCORES, weakest="job_relevance")
        res = normalize_result(diag, {}, weights=None)
        assert res["weakest_dimension"] == "quantification"

    def test_model_declares_correct_dimension_kept(self):
        diag = _build_diagnosis(BASE_SCORES, weakest="quantification")
        res = normalize_result(diag, {}, weights=None)
        assert res["weakest_dimension"] == "quantification"

    def test_model_declares_illegal_key_overridden(self):
        diag = _build_diagnosis(BASE_SCORES, weakest="not_a_real_dimension")
        res = normalize_result(diag, {}, weights=None)
        assert res["weakest_dimension"] == "quantification"

    def test_missing_weakest_declaration_derives_from_scores(self):
        diag = _build_diagnosis(BASE_SCORES, weakest="")
        res = normalize_result(diag, {}, weights=None)
        assert res["weakest_dimension"] == "quantification"

    def test_tie_break_by_weight(self):
        # 两个维度同分最低（2.0），权重更高者更弱
        diag = _build_diagnosis(
            {
                "star_completeness": 5.0,
                "quantification": 2.0,
                "logic_coherence": 2.0,
                "job_relevance": 5.0,
                "professional_depth": 5.0,
            },
            weakest="",
        )
        weights = {
            "star_completeness": 0.2,
            "quantification": 0.2,
            "logic_coherence": 0.4,  # 权重更高 → 更弱
            "job_relevance": 0.1,
            "professional_depth": 0.1,
        }
        res = normalize_result(diag, {}, weights=weights)
        assert res["weakest_dimension"] == "logic_coherence"

    def test_all_zero_scores_no_weakest(self):
        # 全部 0 分时 valid_dims 为空，应回退为空串而非报错
        diag = _build_diagnosis(
            {k: 0.0 for k in DIM_KEYS}, weakest="star_completeness"
        )
        res = normalize_result(diag, {}, weights=None)
        assert res["weakest_dimension"] == ""


class TestNextActionNormalize:
    """v6.0: next_action 三态规整（对标 career-copilot normalizeNextAction）。"""

    def test_valid_action_kept(self):
        diag = _build_diagnosis(BASE_SCORES)
        diag["next_action"] = "next_question"
        res = normalize_result(diag, {}, weights=None)
        assert res["next_action"] == "next_question"

    def test_action_case_normalized(self):
        diag = _build_diagnosis(BASE_SCORES)
        diag["next_action"] = "Complete"
        res = normalize_result(diag, {}, weights=None)
        assert res["next_action"] == "complete"

    def test_invalid_action_derived_from_follow_up_text(self):
        diag = _build_diagnosis(BASE_SCORES)
        diag["next_action"] = "不知道"          # 非法值
        diag["follow_up_question"] = "追问一下"  # 但有追问文本
        res = normalize_result(diag, {}, weights=None)
        assert res["next_action"] == "follow_up"

    def test_missing_action_without_follow_up_is_empty(self):
        # 未声明且无追问文本 → 空串，交由会话层阈值规则兜底
        res = normalize_result(_build_diagnosis(BASE_SCORES), {}, weights=None)
        assert res["next_action"] == ""


class TestAstreamAsync:
    """_astream 应直接消费 llm_client.chat_stream_async，不再有线程池/队列桥接。"""

    @pytest.mark.asyncio
    async def test_astream_consumes_chat_stream_async(self):
        class FakeClient:
            async def chat_stream_async(self, **kwargs):
                for c in ["你好", "世界"]:
                    yield c

        chunks = [c async for c in _astream(FakeClient(), "sys", "usr", 0.3, 100)]
        assert chunks == ["你好", "世界"]

    def test_astream_is_async_generator_function(self):
        import inspect

        assert inspect.isasyncgenfunction(_astream)
