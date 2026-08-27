"""
v3.2: 职业规划（career_planner）测试。

覆盖：
1. plan_career 成功路径（mock 现状基线 + mock LLM 路径推理）
2. LLM 失败 / 返回空阶段时的降级路径
3. POST /api/career-plan 路由集成（响应模型 + 请求校验）
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from backend.career_planner import plan_career, _parse_stages
from backend.llm_client import LLMClient
from backend.schemas import CareerPlanRequest

# ——— 测试数据 ———

FAKE_BASELINE = {
    "dimensions": [
        {"key": "skills", "name": "技能匹配", "weight": 0.35, "score": 3,
         "evidence": "Python/Django 匹配，缺微服务", "gap": "缺微服务", "suggestion": "学习 Docker/K8S"},
        {"key": "experience", "name": "经验年限", "weight": 0.15, "score": 3,
         "evidence": "3年 vs 要求3-5年", "gap": "年限偏低", "suggestion": "突出项目影响力"},
    ],
    "overall_score": 3.2,
    "overall_assessment": "候选人基本匹配，主要短板为微服务经验",
    "risk_level": "中",
    "market_source": None,
    "market_reference": None,
}

FAKE_PLAN_RAW = {
    "stages": [
        {
            "order": 1,
            "title": "夯实基础：补齐微服务技能",
            "timeframe": "0-1 年",
            "target_level": "中级后端工程师",
            "skills_to_acquire": ["Docker", "Kubernetes", "微服务设计"],
            "milestones": ["完成微服务实战项目", "取得 CKA 认证"],
            "transition_action": "内部转岗到微服务项目组",
            "rationale": "现状最薄弱维度是技能匹配（3/5），第一阶段先补微服务。",
        },
        {
            "order": 2,
            "title": "独立胜任高级后端工程师",
            "timeframe": "1-2 年",
            "target_level": "高级后端工程师",
            "skills_to_acquire": ["分布式系统设计", "高并发调优"],
            "milestones": ["主导核心服务重构并量化收益"],
            "transition_action": "跳槽至业务复杂度更高的公司",
            "rationale": "在补齐微服务后，通过更大平台历练实现层级跃迁。",
        },
    ],
    "summary": "先补微服务技能，再通过业务跃迁实现层级提升。",
    "risk_level": "低",
}


def _make_req(**overrides) -> CareerPlanRequest:
    base = {"resume_text": "3年Python后端开发经验", "target_role": "高级后端工程师", "timeframe_years": 3}
    base.update(overrides)
    return CareerPlanRequest(**base)


class TestParseStages:
    def test_parses_and_resequences_order(self):
        stages = _parse_stages(FAKE_PLAN_RAW)
        assert len(stages) == 2
        assert [s.order for s in stages] == [1, 2]  # 重排序号

    def test_skips_invalid_items(self):
        raw = {"stages": [{"order": 1, "title": "ok"}, "not-a-dict", None, {}]}
        stages = _parse_stages(raw)
        assert len(stages) == 1
        assert stages[0].title == "ok"

    def test_empty_stages(self):
        assert _parse_stages({"stages": []}) == []

    def test_cleans_empty_lists(self):
        stages = _parse_stages({"stages": [
            {"order": 1, "title": "x", "skills_to_acquire": ["", "Docker", "  "], "milestones": None},
        ]})
        assert stages[0].skills_to_acquire == ["Docker"]
        assert stages[0].milestones == []


class TestPlanCareer:
    @pytest.mark.asyncio
    async def test_success_path_with_mocked_llm(self):
        """mock 基线 + mock LLM：应解析出 2 个阶段并透传 summary/risk"""
        with patch("backend.career_planner.gap_analyzer.analyze_gap",
                   new=AsyncMock(return_value=FAKE_BASELINE)), \
             patch.object(LLMClient, "chat_json", return_value=FAKE_PLAN_RAW):
            fake_client = LLMClient(provider="deepseek")
            result = await plan_career(_make_req(), llm_client=fake_client)

        assert len(result.stages) == 2
        assert result.stages[0].timeframe == "0-1 年"
        assert result.stages[0].skills_to_acquire == ["Docker", "Kubernetes", "微服务设计"]
        assert result.summary == "先补微服务技能，再通过业务跃迁实现层级提升。"
        assert result.risk_level == "低"
        assert result.baseline_gap is not None
        assert result.baseline_gap.overall_score == 3.2

    @pytest.mark.asyncio
    async def test_fallback_when_llm_raises(self):
        """LLM 抛异常 → 降级为启发式三段式，且保留基线"""
        with patch("backend.career_planner.gap_analyzer.analyze_gap",
                   new=AsyncMock(return_value=FAKE_BASELINE)), \
             patch.object(LLMClient, "chat_json", side_effect=RuntimeError("API down")):
            fake_client = LLMClient(provider="deepseek")
            result = await plan_career(_make_req(), llm_client=fake_client)

        assert len(result.stages) == 3
        assert result.risk_level == "中"
        assert "降级" in result.summary
        # 降级路径第一阶段的技能来自最薄弱维度
        assert result.stages[0].skills_to_acquire == ["学习 Docker/K8S"]

    @pytest.mark.asyncio
    async def test_fallback_when_llm_returns_no_stages(self):
        """LLM 返回空阶段列表 → 同样走降级"""
        with patch("backend.career_planner.gap_analyzer.analyze_gap",
                   new=AsyncMock(return_value=FAKE_BASELINE)), \
             patch.object(LLMClient, "chat_json", return_value={"stages": [], "summary": ""}):
            fake_client = LLMClient(provider="deepseek")
            result = await plan_career(_make_req(), llm_client=fake_client)

        assert len(result.stages) == 3
        assert "入门级" in result.stages[0].target_level

    @pytest.mark.asyncio
    async def test_no_llm_client_goes_straight_to_fallback(self):
        """不注入 llm_client → 直接降级（不发起真实调用）"""
        with patch("backend.career_planner.gap_analyzer.analyze_gap",
                   new=AsyncMock(return_value=FAKE_BASELINE)):
            result = await plan_career(_make_req(), llm_client=None)

        assert len(result.stages) == 3
        assert result.risk_level == "中"

    @pytest.mark.asyncio
    async def test_baseline_failure_still_plans(self):
        """现状基线获取失败也不阻断规划（走降级）"""
        with patch("backend.career_planner.gap_analyzer.analyze_gap",
                   new=AsyncMock(side_effect=RuntimeError("market db broken"))), \
             patch.object(LLMClient, "chat_json", side_effect=RuntimeError("API down")):
            fake_client = LLMClient(provider="deepseek")
            result = await plan_career(_make_req(), llm_client=fake_client)

        assert len(result.stages) == 3
        assert result.baseline_gap is None


class TestCareerPlanApi:
    """POST /api/career-plan 路由集成"""

    def test_validation_error_on_short_resume(self, client: TestClient):
        resp = client.post("/api/career-plan", json={
            "resume_text": "太短", "target_role": "高级后端工程师",
        })
        assert resp.status_code == 422

    def test_validation_error_on_missing_role(self, client: TestClient):
        resp = client.post("/api/career-plan", json={
            "resume_text": "3年Python后端开发经验", "target_role": "",
        })
        assert resp.status_code == 422

    def test_success_returns_structured_plan(self, client: TestClient):
        """mock plan_career：校验路由响应模型序列化"""
        fake_response = {
            "baseline_gap": {
                "dimensions": [{
                    "key": "skills", "name": "技能匹配", "weight": 0.35, "score": 3,
                    "evidence": "缺微服务", "gap": "", "suggestion": "学习 Docker",
                }],
                "overall_score": 3.0, "overall_assessment": "基本匹配", "risk_level": "中",
            },
            "stages": [{
                "order": 1, "title": "夯实基础", "timeframe": "0-1 年", "target_level": "中级",
                "skills_to_acquire": ["Docker"], "milestones": ["完成项目"],
                "transition_action": "转岗", "rationale": "先补短板",
            }],
            "summary": "先补技能再跃迁", "risk_level": "低",
        }
        with patch("backend.main.career_planner.plan_career",
                   new=AsyncMock(return_value=fake_response)):
            resp = client.post("/api/career-plan", json={
                "resume_text": "3年Python后端开发经验",
                "target_role": "高级后端工程师",
                "timeframe_years": 3,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["baseline_gap"]["overall_score"] == 3.0
        assert len(body["stages"]) == 1
        assert body["stages"][0]["skills_to_acquire"] == ["Docker"]
        assert body["risk_level"] == "低"
