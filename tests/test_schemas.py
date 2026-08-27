"""
Pydantic Schema 验证测试：确保请求/响应模型字段类型与约束正确。
"""
import pytest
from backend.schemas import (
    SessionCreateRequest, GapAnalysisRequest, GapAnalysisResponse,
    GapDimensionItem, DiagnosisFeedbackRequest,
    CrossJobCompareRequest, JDEntry, CrossJobCompareResponse, JobCompareItem,
    CareerPlanRequest, CareerPlanResponse, CareerStage,
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


class TestCareerPlanRequest:
    """v3.2: 职业规划请求模型"""

    def test_valid_request_with_defaults(self):
        req = CareerPlanRequest(resume_text="3年Python后端开发经验", target_role="高级后端工程师")
        assert req.target_role == "高级后端工程师"
        assert req.jd_text == ""          # default
        assert req.timeframe_years == 3   # default

    def test_full_request(self):
        req = CareerPlanRequest(
            resume_text="3年Python后端开发经验",
            target_role="高级后端工程师",
            jd_text="需要微服务架构经验",
            timeframe_years=5,
        )
        assert req.timeframe_years == 5

    def test_resume_too_short_rejected(self):
        with pytest.raises(Exception):
            CareerPlanRequest(resume_text="太短", target_role="高级后端工程师")

    def test_target_role_required(self):
        with pytest.raises(Exception):
            CareerPlanRequest(resume_text="3年Python后端开发经验", target_role="")

    def test_timeframe_bounds(self):
        with pytest.raises(Exception):
            CareerPlanRequest(resume_text="3年Python后端开发经验", target_role="x", timeframe_years=0)
        with pytest.raises(Exception):
            CareerPlanRequest(resume_text="3年Python后端开发经验", target_role="x", timeframe_years=11)


class TestCareerStage:
    """v3.2: 单个发展阶段模型"""

    def test_minimal_stage(self):
        stage = CareerStage(order=1, title="夯实基础", timeframe="0-1 年")
        assert stage.skills_to_acquire == []   # default
        assert stage.milestones == []          # default
        assert stage.transition_action == ""   # default
        assert stage.rationale == ""           # default

    def test_full_stage(self):
        stage = CareerStage(
            order=1, title="夯实基础", timeframe="0-1 年", target_level="中级",
            skills_to_acquire=["Docker", "K8S"],
            milestones=["完成实战项目"],
            transition_action="内部转岗",
            rationale="先补最大缺口",
        )
        assert len(stage.skills_to_acquire) == 2
        assert stage.transition_action == "内部转岗"


class TestCareerPlanResponse:
    """v3.2: 职业规划响应模型"""

    def test_nullable_baseline_gap(self):
        resp = CareerPlanResponse(baseline_gap=None, stages=[], summary="", risk_level="中")
        assert resp.baseline_gap is None

    def test_with_baseline_and_stages(self):
        gap = GapAnalysisResponse(
            dimensions=[],
            overall_score=3.0,
            overall_assessment="基本匹配",
            risk_level="中",
        )
        resp = CareerPlanResponse(
            baseline_gap=gap,
            stages=[CareerStage(order=1, title="阶段一", timeframe="0-1 年")],
            summary="先补技能再跃迁",
            risk_level="低",
        )
        assert resp.baseline_gap.overall_score == 3.0
        assert len(resp.stages) == 1
        assert resp.risk_level == "低"
