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
