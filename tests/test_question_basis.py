"""v6.4: 出题依据透出（借鉴 MockFlow 面试页"本题依据"chip）测试。

覆盖 session.question_basis 的确定性拼装：
- 特殊题优先：压力题 / 破冰题 / 教练讲解；
- 薄弱维度补强 > JD 缺口优先考察 > 简历锚点；
- JD 缺口只取前 2 条；锚点类别与 question_gen 实际注入的一致（同款合并逻辑）；
- 无可靠依据时返回空串（前端不渲染，宁缺毋谎）；非 dict 输入安全返回。
"""

from unittest.mock import MagicMock

import pytest

from backend.interview_engine.session import InterviewSession


def _make_session(**overrides) -> InterviewSession:
    llm = MagicMock()
    diag = MagicMock()
    kwargs = dict(
        session_id="s-basis",
        resume_text="3 年 Python 开发经验",
        jd_text="招聘 Python 后端工程师",
        llm_client=llm,
        diagnosis_engine=diag,
        interview_style="friendly",
        db=None,
        mode="simulation",
    )
    kwargs.update(overrides)
    return InterviewSession(**kwargs)


class TestSpecialQuestionBasis:
    def test_pressure_question(self):
        s = _make_session()
        basis = s.question_basis({"is_pressure": True, "topic": "方案被否", "question": "…"})
        assert basis == "压力题，不基于简历与 JD（方案被否）"

    def test_pressure_question_without_topic(self):
        s = _make_session()
        basis = s.question_basis({"is_pressure": True, "question": "…"})
        assert basis == "压力题，不基于简历与 JD"

    def test_pressure_by_question_type(self):
        """压力题也可能只带 question_type 标记（换题路径重建的 dict）。"""
        s = _make_session()
        assert "压力题" in s.question_basis({"question_type": "pressure", "topic": "故障"})

    def test_self_intro(self):
        s = _make_session()
        assert s.question_basis({"question_type": "self_intro"}) == "固定破冰题"

    def test_coach_tip(self):
        s = _make_session()
        assert s.question_basis({"question_type": "coach_tip"}) == "教练模式知识点讲解"


class TestRoutineQuestionBasis:
    def test_focus_dimension_takes_priority_over_jd_gaps(self):
        s = _make_session(jd_gaps=["分布式：缺失"])
        basis = s.question_basis({"focus_dimension_name": "量化程度"})
        assert basis == "薄弱维度补强：量化程度"
        assert "JD" not in basis

    def test_jd_gaps_only_first_two(self):
        s = _make_session(jd_gaps=["缺口A", "缺口B", "缺口C"])
        basis = s.question_basis({})
        assert "缺口A" in basis and "缺口B" in basis
        assert "缺口C" not in basis

    def test_anchor_labels_from_llm_anchors(self):
        s = _make_session(resume_points={
            "anchors": {"tech_choice": ["使用 Redis 做缓存"], "metric": ["QPS 提升 3 倍"]},
        })
        basis = s.question_basis({})
        assert "结合简历锚点（技术选型、量化数据）" in basis

    def test_anchor_labels_fall_back_to_rule_classification(self):
        """LLM 锚点缺失时，用与 question_gen 相同的规则分类兜底。"""
        s = _make_session(resume_points={
            "deep_dive_points": ["基于 Kafka 做削峰"],
        })
        basis = s.question_basis({})
        assert "技术选型" in basis

    def test_jd_gaps_and_anchors_combined(self):
        s = _make_session(
            jd_gaps=["高并发：偏弱"],
            resume_points={"anchors": {"metric": ["延迟降低 40%"]}},
        )
        basis = s.question_basis({})
        assert basis.index("JD 缺口") < basis.index("简历锚点")

    def test_empty_when_no_basis_available(self):
        """无缺口、无锚点、无补强时返回空串——宁缺毋谎。"""
        s = _make_session()
        assert s.question_basis({"question": "普通题"}) == ""

    def test_anchor_limit_three_labels(self):
        s = _make_session(resume_points={"anchors": {
            "tech_choice": ["a"], "metric": ["b"], "architecture": ["c"],
            "business_decision": ["d"], "team": ["e"],
        }})
        basis = s.question_basis({})
        assert "技术选型、量化数据、架构设计" in basis
        assert "团队管理" not in basis


class TestSafety:
    def test_non_dict_returns_empty(self):
        s = _make_session(jd_gaps=["缺口A"])
        assert s.question_basis("not a dict") == ""
        assert s.question_basis(None) == ""

    def test_anchor_labels_empty_when_no_resume_points(self):
        s = _make_session()
        assert s._anchor_labels() == []
