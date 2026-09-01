"""
[v7.3.1] 市场岗位持久化测试（backend/market/store.py）。

钉住三条最容易悄悄回归的持久化语义：

1. **upsert 幂等**：按 (source, source_id) 去重，重复采集只更新不新增——
   市场数据是可再采集的公共缓存，重复采集若无限堆行，库会无声膨胀。
2. **收藏不覆盖**：重新采集（upsert）不得清空用户的「感兴趣」标记。
   v7.1 把收藏从 localStorage 升级为落库，这条承诺正是它值钱的地方
   （实现上依赖 ON CONFLICT DO UPDATE 的字段清单里**不含** is_interested）。
3. **查询边界**：空库返回友好空态而非报错；关键字/城市/学历/薪资过滤与分页生效。

TTL 清理不在这里：那是采集任务表（内存态任务）的职责，
见 tests/test_market_crawler_tasks.py::TestGetStatus::test_expired_done_task_cleaned。
"""
import uuid

import pytest
import pytest_asyncio

from backend.config import config as cfg
from backend.market import store


@pytest_asyncio.fixture(autouse=True)
async def market_db(tmp_path):
    """每个用例独享一个临时 market.db，与真实 data/market.db 物理隔离。"""
    original = cfg.MARKET_DB_PATH
    cfg.MARKET_DB_PATH = str(tmp_path / f"m{uuid.uuid4().hex}.db")
    await store.init_market_db()
    yield
    cfg.MARKET_DB_PATH = original


def _job(source_id: str, **over) -> dict:
    """一条标准采集记录；用 over 覆盖需要变化的字段。"""
    job = {
        "source": "51job",
        "source_id": source_id,
        "keyword": "Python",
        "title": "Python 开发工程师",
        "company": "某某科技",
        "city": "北京",
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


@pytest.mark.asyncio
async def test_upsert_is_idempotent():
    """同 (source, source_id) 重复写入：行数不变，业务字段被更新。"""
    assert await store.upsert_jobs([_job("a1"), _job("a2")]) == 2

    # 重新采集同一岗位：标题与城市变了
    await store.upsert_jobs([_job("a1", title="高级 Python 工程师", city="上海")])

    res = await store.query_jobs()
    assert res["total"] == 2, "重复采集不得新增行"

    a1 = next(i for i in res["items"] if i["source_id"] == "a1")
    assert a1["title"] == "高级 Python 工程师"
    assert a1["city"] == "上海"
    assert a1["tags"] == ["Python", "Django"], "tags 需正确往返序列化"


@pytest.mark.asyncio
async def test_upsert_preserves_interest_flag():
    """v7.1 承诺：重新采集不清空「感兴趣」收藏。"""
    await store.upsert_jobs([_job("a1")])
    job_id = (await store.query_jobs())["items"][0]["id"]
    assert await store.toggle_interest(job_id) is True

    # 重新采集同一岗位，业务字段发生变化
    await store.upsert_jobs([_job("a1", title="Python 工程师(急招)", salary_min=25.0)])

    after = await store.get_job_by_id(job_id)
    assert after["is_interested"] == 1, "重新采集不得清空收藏"
    assert after["title"] == "Python 工程师(急招)", "但业务字段应当被更新"


@pytest.mark.asyncio
async def test_toggle_interest_only_flips_flag():
    """收藏是用户态：只翻 is_interested，不改写业务字段、不改写数据时间戳。"""
    await store.upsert_jobs([_job("a1")])
    before = (await store.query_jobs())["items"][0]
    job_id = before["id"]

    assert await store.toggle_interest(job_id) is True
    assert await store.toggle_interest(job_id) is False, "再点一次应取消收藏"

    after = await store.get_job_by_id(job_id)
    assert after["is_interested"] == 0
    assert after["title"] == before["title"]
    assert after["company"] == before["company"]
    assert after["updated_at"] == before["updated_at"], "收藏不应改写数据时间戳"

    assert await store.toggle_interest(999999) is None, "岗位不存在返回 None"


@pytest.mark.asyncio
async def test_query_jobs_empty_db_returns_friendly_empty():
    """空库返回友好空态，不抛异常（前端依赖这个空态渲染引导）。"""
    res = await store.query_jobs()
    assert res["total"] == 0
    assert res["items"] == []

    stats = await store.get_stats()
    assert stats["total"] == 0
    assert stats["avg_salary"] is None

    assert await store.get_job_by_id(1) is None


@pytest.mark.asyncio
async def test_query_jobs_filters_and_paginates():
    """关键字/城市/学历/薪资过滤与 limit-offset 分页。"""
    await store.upsert_jobs([
        _job("b1", city="北京", education="本科", salary_min=20.0, salary_max=35.0),
        _job("b2", city="上海", education="硕士", salary_min=30.0, salary_max=50.0),
        # 标题也换掉：query_jobs 的 keyword 会同时匹配 keyword 与 title 两列
        _job("b3", keyword="Java", title="Java 开发工程师",
             city="北京", education="本科", salary_min=15.0, salary_max=25.0),
    ])

    assert (await store.query_jobs(keyword="Python"))["total"] == 2
    assert (await store.query_jobs(city="北京"))["total"] == 2
    assert (await store.query_jobs(education="硕士"))["total"] == 1
    # 薪资区间语义：岗位上限 ≥ 期望下限 / 岗位起薪 ≤ 期望上限
    assert (await store.query_jobs(salary_min=28.0))["total"] == 2   # b1(35) b2(50)
    assert (await store.query_jobs(salary_max=22.0))["total"] == 2   # b1(20) b3(15)

    page1 = await store.query_jobs(limit=2, offset=0)
    page2 = await store.query_jobs(limit=2, offset=2)
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    assert page1["items"][0]["id"] != page2["items"][0]["id"]


# ============================================================
# get_stats() 城市归一化
# ============================================================

@pytest.mark.asyncio
async def test_get_stats_cities_are_normalized():
    """城市分布按归一化城市聚合：同一城市的不同行政区不得被拆成多行。

    采集侧存的是完整地址（'上海-徐汇区'），直接 GROUP BY 会得到两个「上海」，
    统计碎片化且地图散点匹配失败。归一化在读取侧完成，不动存量数据。
    """
    await store.upsert_jobs([
        _job("c1", city="上海-徐汇区"),
        _job("c2", city="上海-浦东新区"),
        _job("c3", city="上海"),
        _job("c4", city="北京-朝阳区"),
    ])

    stats = await store.get_stats()
    cities = {c["city"]: c["cnt"] for c in stats["cities"]}

    assert cities.get("上海") == 3, "同一城市的三种写法应合并计数"
    assert cities.get("北京") == 1
    assert "上海-徐汇区" not in cities, "带区名的原始地址不得出现在聚合结果中"


@pytest.mark.asyncio
async def test_get_stats_raw_city_value_preserved():
    """归一化只在读取侧：库里的 city 列保持原始地址（数据保真、可回滚）"""
    await store.upsert_jobs([_job("c1", city="上海-徐汇区")])
    job = (await store.query_jobs())["items"][0]
    assert job["city"] == "上海-徐汇区"


# ============================================================
# get_stats() 响应契约（前后端字段名对齐）
# ============================================================

class TestGetStatsContract:
    """钉住 /api/market/stats 的响应契约。

    前端 marketData.js::loadStats 曾误用 Gap 分析结果的扁平命名
    （total_samples / avg_salary_k / top_cities），而本接口用的是另一套
    （total / avg_salary{avg_k} / cities[{city,cnt}]），导致四张统计卡恒为「—」
    且因引用了不存在的 DOM id 而抛错被静默吞掉。
    这里钉住后端契约：字段改名必须同步改前端。
    """

    EXPECTED_KEYS = {
        "total", "keyword", "cities", "salary_distribution",
        "education_distribution", "avg_salary", "top_skills", "keywords",
    }

    @pytest.mark.asyncio
    async def test_empty_db_keys(self):
        assert set((await store.get_stats()).keys()) == self.EXPECTED_KEYS

    @pytest.mark.asyncio
    async def test_populated_db_shape(self):
        await store.upsert_jobs([_job("d1", city="北京", education="本科")])
        stats = await store.get_stats()

        assert set(stats.keys()) == self.EXPECTED_KEYS
        assert isinstance(stats["total"], int) and stats["total"] == 1

        # avg_salary 是对象而非标量——前端须读 avg_salary.avg_k
        assert isinstance(stats["avg_salary"], dict)
        assert set(stats["avg_salary"]) == {"avg_k", "min_k", "max_k"}

        # 分布类字段均为对象数组——前端须读 .city / .skill / .education / .bucket
        assert stats["cities"] and set(stats["cities"][0]) == {"city", "cnt"}
        assert stats["top_skills"] and set(stats["top_skills"][0]) == {"skill", "count"}
        assert stats["education_distribution"]
        assert set(stats["education_distribution"][0]) == {"education", "cnt"}
        assert stats["salary_distribution"]
        assert set(stats["salary_distribution"][0]) == {"bucket", "cnt"}
