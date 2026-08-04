"""
interview_engine/report.py 测试：维度趋势分析、建议生成、Markdown复盘。
"""

import pytest
from backend.interview_engine.report import (
    analyze_trends,
    generate_suggestions,
    generate_review_markdown,
    _dimension_advice,
)

DIM_KEYS = [
    "star_completeness",
    "quantification",
    "logic_coherence",
    "job_relevance",
    "professional_depth",
]

DEFAULT_WEIGHTS = {k: 0.20 for k in DIM_KEYS}


class TestAnalyzeTrends:
    """analyze_trends() — 从各维度分数序列中识别强项/弱项"""

    def test_all_equal_no_extremes(self):
        """所有维度均分 3.0，均分 3.0 — 无显著差异，不产生强/弱项"""
        trends = {
            k: {"scores": [3.0, 3.0], "rounds": [0, 1]}
            for k in DIM_KEYS
        }
        strengths, weaknesses = analyze_trends(trends, DEFAULT_WEIGHTS)
        assert strengths == []
        assert weaknesses == []

    def test_clear_strength_and_weakness(self):
        """一维 4.5、一维 1.5，其他 3.0 → 分别产生强项和弱项"""
        trends = {
            "star_completeness": {"scores": [4.5, 4.5], "rounds": [0, 1]},
            "quantification": {"scores": [1.5, 1.5], "rounds": [0, 1]},
            "logic_coherence": {"scores": [3.0, 3.0], "rounds": [0, 1]},
            "job_relevance": {"scores": [3.0, 3.0], "rounds": [0, 1]},
            "professional_depth": {"scores": [3.0, 3.0], "rounds": [0, 1]},
        }
        strengths, weaknesses = analyze_trends(trends, DEFAULT_WEIGHTS)
        assert len(strengths) >= 1
        assert len(weaknesses) >= 1
        assert any("STAR" in s or "star" in s.lower() for s in strengths)
        assert any("量化" in w for w in weaknesses)

    def test_empty_trends(self):
        trends = {k: {"scores": [], "rounds": []} for k in DIM_KEYS}
        strengths, weaknesses = analyze_trends(trends, DEFAULT_WEIGHTS)
        assert strengths == []
        assert weaknesses == []

    def test_weighted_loss_ordering(self):
        """加权失分排序：高权重维度失分应优先出现"""
        high_weight = {
            "star_completeness": 0.10,
            "quantification": 0.10,
            "logic_coherence": 0.10,
            "job_relevance": 0.10,
            "professional_depth": 0.60,  # 高权重
        }
        trends = {
            "star_completeness": {"scores": [1.5], "rounds": [0]},
            "quantification": {"scores": [1.5], "rounds": [0]},
            "logic_coherence": {"scores": [1.5], "rounds": [0]},
            "job_relevance": {"scores": [1.5], "rounds": [0]},
            "professional_depth": {"scores": [1.5], "rounds": [0]},
        }
        strengths, weaknesses = analyze_trends(trends, high_weight)
        if weaknesses:
            # professional_depth 失分 3.5*0.60 = 2.10，其他 3.5*0.10 = 0.35
            # 高权重维度应排第一位
            assert "专业深度" in weaknesses[0] or "professional" in weaknesses[0].lower()

    def test_none_weights_falls_back(self):
        trends = {
            "star_completeness": {"scores": [5.0, 5.0], "rounds": [0, 1]},
            "quantification": {"scores": [1.0, 1.0], "rounds": [0, 1]},
            "logic_coherence": {"scores": [3.0, 3.0], "rounds": [0, 1]},
            "job_relevance": {"scores": [3.0, 3.0], "rounds": [0, 1]},
            "professional_depth": {"scores": [3.0, 3.0], "rounds": [0, 1]},
        }
        strengths, weaknesses = analyze_trends(trends, None)
        assert len(strengths) >= 1
        assert len(weaknesses) >= 1


class TestGenerateSuggestions:
    """generate_suggestions() — 文字建议生成"""

    def test_low_score_suggests_foundation(self):
        result = generate_suggestions(
            [], [], overall_avg=2.0, weights=DEFAULT_WEIGHTS, dim_avgs={}
        )
        assert "基础" in result or "弱" in result

    def test_medium_score_suggests_room(self):
        result = generate_suggestions(
            [], [], overall_avg=3.0, weights=DEFAULT_WEIGHTS, dim_avgs={}
        )
        assert "及格" in result or "提升" in result

    def test_high_score_suggests_good(self):
        result = generate_suggestions(
            [], [], overall_avg=4.5, weights=DEFAULT_WEIGHTS, dim_avgs={}
        )
        assert "良好" in result or "保持" in result

    def test_includes_weight_description(self):
        result = generate_suggestions(
            [], [], overall_avg=3.0, weights=DEFAULT_WEIGHTS, dim_avgs={}
        )
        assert "%" in result  # 权重百分比

    def test_weaknesses_appear(self):
        result = generate_suggestions(
            [], ["STAR完整度（平均 2.0 分，权重 20%）"],
            overall_avg=3.0, weights=DEFAULT_WEIGHTS, dim_avgs={}
        )
        assert "STAR" in result

    def test_top_weight_dimension_advice(self):
        """权重最高维度得分低时，应出现定向建议"""
        w = {"star_completeness": 0.10, "quantification": 0.10,
             "logic_coherence": 0.10, "job_relevance": 0.60,
             "professional_depth": 0.10}
        dim_avgs = {k: 3.0 for k in DIM_KEYS}
        dim_avgs["job_relevance"] = 2.0  # 高权重维度得分低
        result = generate_suggestions(
            [], [], overall_avg=3.0, weights=w, dim_avgs=dim_avgs
        )
        assert "岗位相关" in result or "job_relevance" in result

    def test_top_weight_dim_high_no_advice(self):
        """权重最高维度得分高时，不应出现定向建议"""
        w = {"star_completeness": 0.10, "quantification": 0.10,
             "logic_coherence": 0.10, "job_relevance": 0.60,
             "professional_depth": 0.10}
        dim_avgs = {k: 4.0 for k in DIM_KEYS}
        # job_relevance already 4.0 ≥ 3.5, no special advice expected
        result = generate_suggestions(
            [], [], overall_avg=4.0, weights=w, dim_avgs=dim_avgs
        )
        assert "通用建议" in result


class TestGenerateReviewMarkdown:
    """generate_review_markdown() — 复盘 Markdown 生成"""

    def test_basic_markdown(self):
        report = {
            "overall_avg": 3.5,
            "interview_mode": "拟真模式",
            "rounds": [
                {"round_name": "破冰", "avg_score": 4.0, "dimension_details": {}},
                {"round_name": "技术广度", "avg_score": 3.0, "dimension_details": {}},
            ],
            "detailed_qa": [],
        }
        md = generate_review_markdown(report)
        assert "# 面试复盘报告" in md
        assert "3.50" in md
        assert "破冰" in md
        assert "技术广度" in md

    def test_weakness_section(self):
        report = {
            "overall_avg": 2.0,
            "interview_mode": "传统模式",
            "rounds": [
                {
                    "round_name": "笔试",
                    "avg_score": 2.0,
                    "dimension_details": {
                        "star_completeness": {"average": 2.5, "suggestion": "使用STAR方法"},
                        "quantification": {"average": 2.0, "suggestion": "加数字"},
                    },
                }
            ],
            "detailed_qa": [],
        }
        md = generate_review_markdown(report)
        assert "薄" in md
        assert "2.00" in md or "2.0" in md

    def test_rewritten_answers_section(self):
        report = {
            "overall_avg": 4.0,
            "interview_mode": "拟真模式",
            "rounds": [],
            "detailed_qa": [
                {
                    "question": "请介绍你做过的最有挑战的项目",
                    "rewritten_answer": "在我的实习项目中，我负责重构了一个核心模块...",
                }
            ],
        }
        md = generate_review_markdown(report)
        assert "参考答案" in md
        assert "最有挑战" in md

    def test_todo_section(self):
        report = {
            "overall_avg": 3.0,
            "interview_mode": "传统模式",
            "rounds": [],
            "detailed_qa": [],
        }
        md = generate_review_markdown(report)
        assert "TODO" in md
        assert "STAR" in md


class TestDimensionAdvice:
    """_dimension_advice()"""

    @pytest.mark.parametrize("key", DIM_KEYS)
    def test_returns_non_empty_string(self, key):
        advice = _dimension_advice(key)
        assert isinstance(advice, str)
        assert len(advice) > 10

    def test_unknown_key_returns_generic(self):
        advice = _dimension_advice("unknown")
        assert "专项练习" in advice
