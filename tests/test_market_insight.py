"""
[v8.2] 市场图表 AI 解读测试（backend/market/insight.py）。

解读是**增强能力**，所以这里钉的是**降级与缓存**，而不是 LLM 输出质量——
质量依赖模型，不可单测（见 README「已知局限」）。

钉住五条：
1. 空库 / 该维度无数据 → 短路返回 error，**不浪费 LLM 调用**；
2. section 非法、LLM 返回 error → 返回 error 而非抛异常；
3. 缓存命中不重复调用 LLM，``fresh=True`` 强制刷新；
4. ``invalidate()`` 让缓存失效（采集/导入新数据后必须调用）；
5. section 注册表与前端卡片一一对应（改名需同步前端）。
"""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio

from backend.config import config as cfg
from backend.market import insight, store


@pytest_asyncio.fixture(autouse=True)
async def market_db(tmp_path):
    original = cfg.MARKET_DB_PATH
    cfg.MARKET_DB_PATH = str(tmp_path / f"m{uuid.uuid4().hex}.db")
    await store.init_market_db()
    yield
    cfg.MARKET_DB_PATH = original


@pytest.fixture(autouse=True)
def clean_cache():
    """用例之间隔离缓存——insight 的缓存是模块级单例，不清理会串味。"""
    insight.invalidate()
    yield
    insight.invalidate()


def _job(source_id: str, **over) -> dict:
    job = {
        "source": "51job",
        "source_id": source_id,
        "keyword": "Python",
        "title": "Python 开发工程师",
        "company": "某某科技",
        "city": "上海-徐汇区",
        "salary_raw": "20-35K",
        "salary_min": 20.0,
        "salary_max": 35.0,
        "exp_min": 3.0,
        "exp_max": 5.0,
        "education": "本科",
        "tags": ["Python", "Django"],
        "description": "负责后端服务开发",
        "url": f"https://example.com/{source_id}",
    }
    job.update(over)
    return job


async def _seed(n: int = 3):
    await store.upsert_jobs([_job(f"s{i}") for i in range(n)])


# ============================================================
# 短路：不该调用 LLM 的场景
# ============================================================

@pytest.mark.asyncio
async def test_empty_db_short_circuits_without_llm():
    """空库直接返回 error，不烧 token"""
    with patch.object(insight.llm_client, "chat_json") as m:
        result = await insight.analyze("overview")

    assert "error" in result
    assert m.call_count == 0, "空库不应触发 LLM 调用"


@pytest.mark.asyncio
async def test_no_data_dimension_short_circuits():
    """该维度无数据（city 全空）→ error，不烧 token"""
    await store.upsert_jobs([_job("x1", city="")])

    with patch.object(insight.llm_client, "chat_json") as m:
        result = await insight.analyze("city")

    assert "error" in result
    assert m.call_count == 0


@pytest.mark.asyncio
async def test_invalid_section_returns_error():
    await _seed()

    with patch.object(insight.llm_client, "chat_json") as m:
        result = await insight.analyze("not_a_section")

    assert "无效的解读类型" in result["error"]
    assert m.call_count == 0


# ============================================================
# 成功路径
# ============================================================

@pytest.mark.asyncio
async def test_analyze_returns_text():
    await _seed()

    with patch.object(insight.llm_client, "chat_json", return_value={"text": "这是解读"}):
        result = await insight.analyze("overview")

    assert result["text"] == "这是解读"
    assert result["section"] == "overview"
    assert result["title"] == "市场总览"
    assert result["cached"] is False
    assert "model" in result


# ============================================================
# 缓存
# ============================================================

@pytest.mark.asyncio
async def test_cache_hit_avoids_second_llm_call():
    """5 分钟内重复请求同一 section 不重复烧 token"""
    await _seed()

    with patch.object(insight.llm_client, "chat_json", return_value={"text": "A"}) as m:
        await insight.analyze("overview")
        second = await insight.analyze("overview")

    assert m.call_count == 1
    assert second["cached"] is True
    assert second["text"] == "A"


@pytest.mark.asyncio
async def test_fresh_bypasses_cache():
    await _seed()

    with patch.object(insight.llm_client, "chat_json", return_value={"text": "A"}) as m:
        await insight.analyze("overview")
        await insight.analyze("overview", fresh=True)

    assert m.call_count == 2


@pytest.mark.asyncio
async def test_cache_keyed_by_keyword():
    """不同关键词是不同解读，不能共用一个缓存条目"""
    await store.upsert_jobs([_job("p1", keyword="Python"), _job("j1", keyword="Java")])

    with patch.object(insight.llm_client, "chat_json", return_value={"text": "A"}) as m:
        await insight.analyze("overview", keyword="Python")
        await insight.analyze("overview", keyword="Java")

    assert m.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_clears_cache():
    await _seed()

    with patch.object(insight.llm_client, "chat_json", return_value={"text": "A"}) as m:
        await insight.analyze("overview")
        insight.invalidate()
        await insight.analyze("overview")

    assert m.call_count == 2, "invalidate 后应重新调用 LLM"


# ============================================================
# 降级
# ============================================================

@pytest.mark.asyncio
async def test_llm_error_degrades_gracefully():
    """LLM 返回 error（如无 Key）→ 转为用户可读 error，绝不抛异常"""
    await _seed()

    with patch.object(insight.llm_client, "chat_json",
                      return_value={"error": "API Key 未配置"}):
        result = await insight.analyze("salary")

    assert result["error"] == "API Key 未配置"
    assert result["section"] == "salary"


@pytest.mark.asyncio
async def test_empty_text_treated_as_failure():
    await _seed()

    with patch.object(insight.llm_client, "chat_json", return_value={"text": "  "}):
        result = await insight.analyze("skill")

    assert "error" in result


@pytest.mark.asyncio
async def test_llm_exception_is_caught():
    """LLM 抛异常（网络抖动）也不能把请求打穿"""
    await _seed()

    with patch.object(insight.llm_client, "chat_json", side_effect=RuntimeError("boom")):
        result = await insight.analyze("city")

    assert "error" in result


# ============================================================
# 注册表契约
# ============================================================

def test_sections_registry_is_complete():
    """section 注册表与前端卡片一一对应；新增/改名必须同步 frontend。"""
    assert set(insight.SECTIONS) == {
        "overview", "salary", "education", "experience",
        "city", "geo", "skill", "cross_exp", "cross_edu", "keyword",
    }


def test_every_section_has_title_and_instruction():
    for key, spec in insight.SECTIONS.items():
        assert spec.key == key
        assert spec.title, f"{key} 缺少标题"
        assert spec.instruction.strip(), f"{key} 缺少指令"
        assert callable(spec.describe)


@pytest.mark.asyncio
async def test_describe_functions_handle_empty_charts():
    """空数据下所有 describe 都返回空串而非抛异常（配合短路逻辑）"""
    empty = {"total": 0, "salary": [], "education": [], "experience": [],
             "city": [], "skill": [], "cross_exp": {}, "cross_edu": {},
             "keyword_dist": []}
    for key, spec in insight.SECTIONS.items():
        assert spec.describe(empty) == "", f"{key} 在空数据下应返回空串"
