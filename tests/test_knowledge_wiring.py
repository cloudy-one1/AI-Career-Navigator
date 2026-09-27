"""知识库接线（v8.17）：knowledge_store 从"建成即休眠"到接通业务流。

三段验证：
  1. 入库 API（POST/GET /api/knowledge，命名空间白名单 + 长度上限）
  2. 出题注入（generate_round_questions 消费 rag:interview，
     会话级指纹集合跨轮去重——原地更新，同一段知识不重复注入）
  3. 职业规划注入（plan_career 消费 rag:career，一次性请求无去重问题）

口径：空库时零行为变化（不配置即不注入，向后兼容）；注入是增强项，
知识库抛异常不允许拖垮出题/规划。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend import question_gen as question_gen_mod
from backend.career_planner import _PLANNER_SYSTEM_PROMPT, plan_career
from backend.config import config
from backend.db import init_db
from backend.knowledge_store import (
    NAMESPACE_CAREER,
    NAMESPACE_INTERVIEW,
    get_knowledge_store,
)
from backend.market.store import init_market_db
from backend.question_gen import generate_round_questions

_seed_kb = get_knowledge_store()


@pytest.fixture(autouse=True)
def _clean_kb():
    """单例知识库跨测试残留会影响其它文件对 prompt 内容的断言，用后即清。"""
    _seed_kb.clear()
    yield
    _seed_kb.clear()


def _no_market():
    return patch.object(question_gen_mod, "_build_market_context_block",
                        AsyncMock(return_value=""))


def _fake_llm(return_value):
    llm = MagicMock()
    llm.chat_json = MagicMock(return_value=return_value)
    return llm


# ==================== 1. 出题注入 ====================

class TestQuestionGenKnowledgeInjection:
    @pytest.mark.asyncio
    async def test_seeded_kb_injects_into_system_prompt(self):
        # 种子文本必须与查询词（JD 抽取的词条）有词面重叠——无关块本就不该被检索
        _seed_kb.add_document(NAMESPACE_INTERVIEW, "测试公司背景",
                              "电商后端岗位背景：本公司主营电商中台，"
                              "仓储业务使用自研 WMS，出题可结合该场景。")
        llm = _fake_llm({"questions": [{"question": "Q1"}]})
        hashes: set = set()
        with _no_market():
            await generate_round_questions(llm, "简历", "电商后端JD", 1, "技术广度", 2,
                                           kb_hashes=hashes)
        system_prompt = llm.chat_json.call_args.args[0]
        assert "【参考知识库相关内容】" in system_prompt
        assert "自研 WMS" in system_prompt
        assert "严禁据此编造" in system_prompt   # 反幻觉约束随注入块一起进入
        assert hashes, "本轮实际注入的指纹必须写回会话级集合"

    @pytest.mark.asyncio
    async def test_second_round_dedupes_via_hashes(self):
        """证伪锚点：指纹集合跨轮累积后，同一段知识不再注入（不重复占预算）。"""
        _seed_kb.add_document(NAMESPACE_INTERVIEW, "测试公司背景",
                              "电商后端岗位背景：本公司主营电商中台，"
                              "仓储业务使用自研 WMS，出题可结合该场景。")
        llm = _fake_llm({"questions": [{"question": "Q1"}]})
        hashes: set = set()
        with _no_market():
            await generate_round_questions(llm, "简历", "电商后端JD", 1, "技术广度", 2, kb_hashes=hashes)
            assert "【参考知识库相关内容】" in llm.chat_json.call_args.args[0]

            await generate_round_questions(llm, "简历", "电商后端JD", 2, "技术深度", 2, kb_hashes=hashes)
            assert "【参考知识库相关内容】" not in llm.chat_json.call_args.args[0]

    @pytest.mark.asyncio
    async def test_empty_kb_leaves_prompt_unchanged(self):
        llm = _fake_llm({"questions": [{"question": "Q1"}]})
        hashes: set = set()
        with _no_market():
            await generate_round_questions(llm, "简历", "JD", 1, "技术广度", 2, kb_hashes=hashes)
        assert "【参考知识库相关内容】" not in llm.chat_json.call_args.args[0]
        assert hashes == set()

    @pytest.mark.asyncio
    async def test_kb_error_does_not_break_generation(self):
        """注入是增强项：知识库抛异常时出题必须照常进行。"""
        llm = _fake_llm({"questions": [{"question": "Q1"}]})
        hashes: set = set()
        with _no_market(), patch.object(question_gen_mod, "get_knowledge_store",
                                        side_effect=Exception("kb down")):
            qs = await generate_round_questions(llm, "简历", "JD", 1, "技术广度", 2,
                                                kb_hashes=hashes)
        assert qs == [{"question": "Q1"}]


# ==================== 2. 职业规划注入 ====================

class TestCareerPlannerKnowledgeInjection:
    @pytest.mark.asyncio
    async def test_seeded_kb_injects_into_planner_system_prompt(self):
        _seed_kb.add_document(NAMESPACE_CAREER, "岗位序列参考",
                              "后端工程师常见路径：中级后端 → 高级后端 → 架构师，通常需要 3-5 年。")
        llm = _fake_llm({"stages": [], "summary": ""})   # 空 stages → 走降级，不影响断言
        req = MagicMock()
        req.target_role = "后端工程师"
        req.jd_text = "电商后端"
        with patch.object(question_gen_mod, "_build_market_context_block",
                          AsyncMock(return_value="")), \
             patch("backend.gap_analyzer.analyze_gap", AsyncMock(return_value=None)):
            await plan_career(req=req, llm_client=llm)
        system_prompt = llm.chat_json.call_args.args[0]
        assert system_prompt.startswith(_PLANNER_SYSTEM_PROMPT)
        assert "【参考知识库相关内容】" in system_prompt
        assert "岗位序列参考" in system_prompt

    @pytest.mark.asyncio
    async def test_empty_kb_keeps_planner_prompt_exact(self):
        llm = _fake_llm({"stages": [], "summary": ""})
        req = MagicMock()
        req.target_role = "后端工程师"
        req.jd_text = ""
        with patch.object(question_gen_mod, "_build_market_context_block",
                          AsyncMock(return_value="")), \
             patch("backend.gap_analyzer.analyze_gap", AsyncMock(return_value=None)):
            await plan_career(req=req, llm_client=llm)
        assert llm.chat_json.call_args.args[0] == _PLANNER_SYSTEM_PROMPT


# ==================== 3. 入库 API ====================

def _client(tmp_path):
    original = (config.DB_PATH, config.MARKET_DB_PATH)
    config.DB_PATH = str(tmp_path / "kb.db")
    config.MARKET_DB_PATH = str(tmp_path / "kb_market.db")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(init_db())
        loop.run_until_complete(init_market_db())
    finally:
        loop.close()
    from backend.main import app
    try:
        yield TestClient(app)
    finally:
        config.DB_PATH, config.MARKET_DB_PATH = original
        _seed_kb.clear()


class TestKnowledgeApi:
    @pytest.fixture()
    def client(self, tmp_path):
        yield from _client(tmp_path)

    def test_add_and_stats(self, client):
        resp = client.post("/api/knowledge", json={
            "namespace": "interview", "source": "公司速写",
            "text": "本公司主营电商中台。仓储线使用自研 WMS。" * 3,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["namespace"] == "rag:interview"
        assert body["chunks_added"] >= 1
        assert body["stats"]["rag:interview"]["chunks"] >= 1

        stats = client.get("/api/knowledge").json()["namespaces"]
        assert stats["rag:interview"]["sources"] == 1

    def test_add_with_rag_prefix_also_accepted(self, client):
        resp = client.post("/api/knowledge", json={
            "namespace": "rag:career", "source": "路径参考", "text": "中级 → 高级 → 架构师。",
        })
        assert resp.status_code == 200
        assert resp.json()["namespace"] == "rag:career"

    def test_unknown_namespace_rejected(self, client):
        resp = client.post("/api/knowledge", json={
            "namespace": "marketing", "source": "x", "text": "内容",
        })
        assert resp.status_code == 400
        assert "interview / career / resume" in resp.json()["detail"]

    def test_empty_text_rejected(self, client):
        resp = client.post("/api/knowledge", json={
            "namespace": "interview", "source": "x", "text": "   ",
        })
        assert resp.status_code == 400

    def test_long_text_truncated(self, client):
        resp = client.post("/api/knowledge", json={
            "namespace": "interview", "source": "超长文档", "text": "字" * 60_000,
        })
        assert resp.status_code == 200
        assert resp.json()["truncated"] is True
