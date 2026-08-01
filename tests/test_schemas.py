"""
Pydantic Schema 验证测试：确保请求/响应模型字段类型与约束正确。
"""
import pytest
from backend.schemas import (
    SessionCreateRequest, GapAnalysisRequest, GapAnalysisResponse,
    GapDimensionItem, DiagnosisFeedbackRequest,
    CrossJobCompareRequest, JDEntry, CrossJobCompareResponse, JobCompareItem,
)


class TestSessionCreateRequest:
    def test_minimal_request(self):
        req = SessionCreateRequest(resume_text="简历", jd_text="JD")
        assert req.resume_text == "简历"
        assert req.jd_text == "JD"
        assert req.style == "friendly"  # default
        assert req.mode == "simulation"  # default

    def test_empty_strings_accepted_with_default(self):
        """简历/JD 允许空字符串（Schema 不校验非空，由上层业务逻辑处理）"""
        req = SessionCreateRequest(resume_text="", jd_text="")
        assert req.resume_text == ""
        assert req.jd_text == ""


class TestGapAnalysisRequest:
    def test_valid_request(self):
        req = GapAnalysisRequest(resume_text="简历", jd_text="JD", keyword="Python")
        assert req.keyword == "Python"

    def test_empty_keyword_default(self):
        req = GapAnalysisRequest(resume_text="简历", jd_text="JD")
        assert req.keyword == ""


class TestGapDimensionItem:
    def test_all_types_correct(self):
        item = GapDimensionItem(
            key="skills", name="技能匹配", weight=0.35, score=4,
            evidence="匹配", gap="无", suggestion="无需改进",
        )
        assert isinstance(item.score, int)
        assert isinstance(item.weight, float)


class TestDiagnosisFeedback:
    def test_valid_feedback(self):
        req = DiagnosisFeedbackRequest(
            session_id="abc", round_idx=0, question_idx=0,
            feedback_type="up", comment="不错",
        )
        assert req.feedback_type in ("up", "down")
        assert req.round_idx == 0


class TestCrossJobCompare:
    def test_valid_request(self):
        req = CrossJobCompareRequest(
            resume_text="3年Python开发经验",
            jd_list=[
                JDEntry(title="Python开发", text="需要Django经验"),
                JDEntry(title="数据分析", text="需要SQL和Python"),
            ],
        )
        assert len(req.jd_list) == 2
        assert req.resume_text == "3年Python开发经验"

    def test_min_jd_list(self):
        """至少2个岗位才能对比"""
        with pytest.raises(Exception):  # Pydantic validation error
            CrossJobCompareRequest(
                resume_text="简历",
                jd_list=[JDEntry(title="一个岗位", text="描述")],
            )

    def test_empty_jd_title_rejected(self):
        with pytest.raises(Exception):
            JDEntry(title="", text="描述")

    def test_job_compare_item_structure(self):
        item = JobCompareItem(
            title="测试岗位",
            overall_score=4.0,
            risk_level="低风险",
            key_strengths=["技能匹配(4/5)"],
            key_gaps=["逻辑连贯(2/5): 表达不清晰"],
        )
        assert item.overall_score == 4.0
        assert len(item.key_strengths) == 1

    def test_cross_job_response_structure(self):
        resp = CrossJobCompareResponse(
            results=[
                JobCompareItem(title="岗位A", overall_score=4.0, risk_level="低风险"),
                JobCompareItem(title="岗位B", overall_score=3.0, risk_level="中风险"),
            ],
            recommendation="推荐岗位A",
            ranking=["岗位A", "岗位B"],
        )
        assert resp.ranking == ["岗位A", "岗位B"]
