"""
dimension_weights.py 测试：权重归一化、加权计分、权重描述、TOP维度。
LLM 相关函数（analyze_jd_weights）不在此测试（需 mock LLM+DB）。
"""

import pytest
from backend.dimension_weights import (
    DEFAULT_WEIGHTS,
    DIM_KEYS,
    MIN_WEIGHT,
    MAX_WEIGHT,
    normalize_weights,
    weighted_score,
    describe_weights,
    top_dimension,
)


class TestNormalizeWeights:
    """normalize_weights() — 任意权重字典 → 合法权重"""

    def test_normal_dict_returns_normalized(self):
        raw = {
            "star_completeness": 0.30,
            "quantification": 0.25,
            "logic_coherence": 0.15,
            "job_relevance": 0.20,
            "professional_depth": 0.10,
        }
        result = normalize_weights(raw)
        assert len(result) == 5
        assert abs(sum(result.values()) - 1.0) < 0.0001
        for k in DIM_KEYS:
            assert MIN_WEIGHT <= result[k] <= MAX_WEIGHT

    def test_none_returns_default(self):
        result = normalize_weights(None)
        assert result == DEFAULT_WEIGHTS

    def test_non_dict_returns_default(self):
        result = normalize_weights("not a dict")
        assert result == DEFAULT_WEIGHTS

    def test_missing_dimensions_filled(self):
        raw = {"star_completeness": 0.50, "quantification": 0.50}
        result = normalize_weights(raw)
        for k in DIM_KEYS:
            assert k in result

    def test_negative_values_replaced_with_default(self):
        raw = {
            "star_completeness": -0.5,
            "quantification": 0.25,
            "logic_coherence": 0.25,
            "job_relevance": 0.25,
            "professional_depth": 0.25,
        }
        result = normalize_weights(raw)
        # 负值被替换为 0.20，但随后归一化，所以不会正好等于 0.20
        # 归一化 total=1.20，star_completeness=0.20/1.20≈0.1667
        assert abs(result["star_completeness"] * 1.20 - 0.20) < 0.01
        # 其他值按比例缩小
        for k in ["quantification", "logic_coherence", "job_relevance", "professional_depth"]:
            assert abs(result[k] * 1.20 - 0.25) < 0.01

    def test_non_numeric_values_replaced(self):
        raw = {
            "star_completeness": "high",
            "quantification": 0.25,
            "logic_coherence": 0.25,
            "job_relevance": 0.25,
            "professional_depth": 0.25,
        }
        result = normalize_weights(raw)
        # "high" → float失败 → 回退默认 0.20 → 归一化 total=1.20 → 0.1667
        assert abs(result["star_completeness"] * 1.20 - 0.20) < 0.01

    def test_extreme_values_clamped(self):
        """超过 [0.10, 0.40] 区间的值在裁剪后被归一化"""
        raw = {
            "star_completeness": 0.90,  # 太大 → 裁剪到 0.40
            "quantification": 0.30,
            "logic_coherence": 0.30,
            "job_relevance": 0.05,  # 太小 → 裁剪到 0.10
            "professional_depth": 0.02,  # 太小 → 裁剪到 0.10
        }
        result = normalize_weights(raw)
        # 正常: 0.40+0.30+0.30+0.10+0.10=1.20 → 归一化
        # star_completeness ≈ 0.3333 ≤ 0.40 ✓
        assert result["star_completeness"] <= MAX_WEIGHT
        # job_relevance ≈ 0.0833 < 0.10 — 归一化后的值可能低于 MIN_WEIGHT，这是正确的
        assert result["job_relevance"] > 0  # 至少不为零
        # 各维度都在合理范围内
        for v in result.values():
            assert v > 0
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_all_zero_returns_default(self):
        raw = {k: 0 for k in DIM_KEYS}
        result = normalize_weights(raw)
        # 全 0 时每个维度被替换为 0.20（默认值），所以结果应该是 5 个 0.20
        assert result == DEFAULT_WEIGHTS


class TestWeightedScore:
    """weighted_score() — 按权重加权计算总分"""

    def test_all_perfect_scores(self):
        dims = {k: 5.0 for k in DIM_KEYS}
        score = weighted_score(dims, DEFAULT_WEIGHTS)
        assert score == 5.0

    def test_all_min_scores(self):
        dims = {k: 1.0 for k in DIM_KEYS}
        score = weighted_score(dims, DEFAULT_WEIGHTS)
        assert score == 1.0

    def test_weighted_difference(self):
        """高权重维度分数高，加权分应偏高"""
        dims = {
            "star_completeness": 1.0, "quantification": 1.0,
            "logic_coherence": 1.0, "job_relevance": 1.0,
            "professional_depth": 5.0,
        }
        equal_score = weighted_score(dims, DEFAULT_WEIGHTS)
        # 专业深度加权更高
        heavy_weights = {**DEFAULT_WEIGHTS, "professional_depth": 0.60}
        heavy_weights["star_completeness"] = 0.10
        heavy_weights["quantification"] = 0.10
        heavy_weights["logic_coherence"] = 0.10
        heavy_weights["job_relevance"] = 0.10
        score_heavy = weighted_score(dims, heavy_weights)
        assert score_heavy > equal_score

    def test_empty_dimensions(self):
        score = weighted_score({}, DEFAULT_WEIGHTS)
        assert score == 0.0

    def test_none_weights_falls_back(self):
        dims = {k: 5.0 for k in DIM_KEYS}
        score = weighted_score(dims, None)
        assert score == 5.0

    def test_excluded_dimensions_skipped(self):
        """0 分 / 非数值 / 仅部分维度 三种情况都按权重正确加权，无效维度不计入。"""
        # 0 分维度不参与加权计算
        dims_zero = {
            "star_completeness": 0, "quantification": 5.0,
            "logic_coherence": 0, "job_relevance": 5.0,
            "professional_depth": 0,
        }
        assert weighted_score(dims_zero, DEFAULT_WEIGHTS) == 5.0
        # 非数值维度跳过
        dims_bad = {
            "star_completeness": "N/A",
            "quantification": 3.0,
            "logic_coherence": 4.0,
            "job_relevance": 2.0,
            "professional_depth": 5.0,
        }
        score_bad = weighted_score(dims_bad, DEFAULT_WEIGHTS)
        assert 1.0 < score_bad < 5.0
        # 只提供部分维度
        assert weighted_score(
            {"star_completeness": 3.0, "quantification": 4.0}, DEFAULT_WEIGHTS
        ) == 3.5


class TestDescribeWeights:
    """describe_weights()"""

    def test_default_describes_correctly(self):
        desc = describe_weights(DEFAULT_WEIGHTS)
        for name in ["STAR 完整度", "量化程度", "逻辑连贯性", "岗位相关性", "专业深度"]:
            assert name in desc
        assert "20%" in desc

    def test_custom_weights_described(self):
        w = {
            "star_completeness": 0.10,
            "quantification": 0.30,
            "logic_coherence": 0.20,
            "job_relevance": 0.25,
            "professional_depth": 0.15,
        }
        desc = describe_weights(w)
        assert "STAR 完整度 10%" in desc
        assert "量化程度 30%" in desc

    def test_missing_key_uses_default(self):
        """缺失的 key 应使用 0.20"""
        desc = describe_weights({})
        assert "20%" in desc


class TestTopDimension:
    """top_dimension()"""

    def test_returns_highest_weight_key(self):
        w = {
            "star_completeness": 0.10,
            "quantification": 0.30,
            "logic_coherence": 0.15,
            "job_relevance": 0.25,
            "professional_depth": 0.20,
        }
        assert top_dimension(w) == "quantification"

    def test_empty_weights_returns_default(self):
        assert top_dimension({}) == "job_relevance"

    def test_none_weights_returns_default(self):
        assert top_dimension(None) == "job_relevance"

    def test_tie_returns_first_in_dim_keys(self):
        """平票时返回 DIM_KEYS 中排前面的"""
        w = {k: 0.20 for k in DIM_KEYS}
        result = top_dimension(w)
        assert result == DIM_KEYS[0]  # "star_completeness"
