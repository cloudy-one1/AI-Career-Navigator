"""
[v8.2] 市场图表聚合测试（backend/market/analytics.py）。

钉住四条最容易悄悄回归的性质：

1. **分档顺序固定且含 0 值档位**——否则前端图表 X 轴刻度会随数据跳变；
2. **城市已归一化**——同一城市的不同行政区必须合并，否则地图散点大面积 miss；
3. **交叉统计只计入有薪资的岗位**——面议岗位进入均值会把均薪整体拉偏；
4. **空库返回规范空态**——前端依赖空态渲染引导，不抛异常。
"""

import uuid

import pytest
import pytest_asyncio

from backend.config import config as cfg
from backend.market import analytics, store


@pytest_asyncio.fixture(autouse=True)
async def market_db(tmp_path):
    """每个用例独享临时 market.db"""
    original = cfg.MARKET_DB_PATH
    cfg.MARKET_DB_PATH = str(tmp_path / f"m{uuid.uuid4().hex}.db")
    await store.init_market_db()
    yield
    cfg.MARKET_DB_PATH = original


def _job(source_id: str, **over) -> dict:
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


# ============================================================
# 纯函数：分档
# ============================================================

class TestBuckets:

    @pytest.mark.parametrize("mid,expected", [
        (3, "<5K"),
        (5, "5-8K"),
        (10, "8-11K"),
        (12, "11-14K"),
        (16, "14-17K"),
        (18, "17-20K"),
        (21, "20-23K"),
        (30, "23K+"),
    ])
    def test_salary_bucket(self, mid, expected):
        assert analytics.salary_bucket(mid) == expected

    def test_salary_bucket_boundary_is_left_closed(self):
        """左闭右开：8 落在 8-11K 而非 5-8K"""
        assert analytics.salary_bucket(8) == "8-11K"
        assert analytics.salary_bucket(7.9) == "5-8K"

    @pytest.mark.parametrize("lo,hi,expected", [
        (None, None, "经验不限"),
        (0.0, 0.0, "应届/在校"),       # cleaner.parse_experience 的约定
        (0.0, 1.0, "1年以下"),
        (1.0, 3.0, "1-3年"),
        (3.0, 5.0, "3-5年"),
        (5.0, 10.0, "5-10年"),
        (10.0, None, "10年以上"),
    ])
    def test_exp_bucket(self, lo, hi, expected):
        assert analytics.exp_bucket(lo, hi) == expected


# ============================================================
# 聚合
# ============================================================

@pytest.mark.asyncio
async def test_empty_db_returns_clean_shapes():
    """空库：total=0，固定档位维度返回全 0（X 轴不跳变），TopN 维度返回空数组。"""
    charts = await analytics.get_charts()

    assert charts["total"] == 0

    # 固定档位维度：即使空库也给出完整档位骨架，前端 X 轴刻度恒定
    assert [s["count"] for s in charts["salary"]] == [0] * len(analytics.SALARY_BINS)
    assert [e["count"] for e in charts["education"]] == [0] * len(analytics.EDU_LABELS)
    assert [e["count"] for e in charts["experience"]] == [0] * len(analytics.EXP_LABELS)

    # TopN 维度：无数据即空数组
    for key in ("city", "skill", "keyword_dist"):
        assert charts[key] == [], key

    assert charts["cross_exp"]["labels"] == list(analytics.EXP_LABELS)
    assert charts["cross_edu"]["labels"] == list(analytics.EDU_LABELS)


@pytest.mark.asyncio
async def test_salary_bins_keep_zero_bands():
    """0 值档位必须保留——否则不同筛选条件下 X 轴长度会变，图表抖动。"""
    await store.upsert_jobs([_job("a1", salary_min=20.0, salary_max=24.0)])  # 22K → 20-23K

    charts = await analytics.get_charts()
    labels = [s["label"] for s in charts["salary"]]

    assert labels == [lb for _, _, lb in analytics.SALARY_BINS], "档位顺序固定且完整"
    assert len(labels) == 8
    assert next(s for s in charts["salary"] if s["label"] == "20-23K")["count"] == 1
    assert sum(s["count"] for s in charts["salary"]) == 1


@pytest.mark.asyncio
async def test_city_is_normalized():
    """图表层同样归一化，否则地图散点拿不到坐标"""
    await store.upsert_jobs([
        _job("c1", city="上海-徐汇区"),
        _job("c2", city="上海-浦东新区"),
        _job("c3", city="北京"),
    ])

    charts = await analytics.get_charts()
    cities = {c["city"]: c["cnt"] for c in charts["city"]}

    assert cities == {"上海": 2, "北京": 1}


@pytest.mark.asyncio
async def test_education_and_experience_bins():
    await store.upsert_jobs([
        _job("d1", education="本科", exp_min=3.0, exp_max=5.0),
        _job("d2", education="本科", exp_min=1.0, exp_max=3.0),
    ])

    charts = await analytics.get_charts()
    edu = {e["label"]: e["count"] for e in charts["education"]}
    exp = {e["label"]: e["count"] for e in charts["experience"]}

    assert edu["本科"] == 2
    assert exp["3-5年"] == 1
    assert exp["1-3年"] == 1


@pytest.mark.asyncio
async def test_cross_exp_ignores_jobs_without_salary():
    """面议岗位（薪资为 NULL）不得进入均薪计算，否则均薪被系统性拉低。"""
    await store.upsert_jobs([
        _job("e1", exp_min=1.0, exp_max=2.0, salary_min=10.0, salary_max=12.0),   # 11K
        _job("e2", exp_min=8.0, exp_max=10.0, salary_min=30.0, salary_max=34.0),  # 32K
        _job("e3", exp_min=1.0, exp_max=2.0, salary_min=None, salary_max=None),   # 面议
    ])

    cross = (await analytics.get_charts())["cross_exp"]
    i_1_3 = cross["labels"].index("1-3年")
    i_5_10 = cross["labels"].index("5-10年")

    assert cross["counts"][i_1_3] == 1
    assert cross["avg_salaries"][i_1_3] == 11.0
    assert cross["avg_salaries"][i_5_10] == 32.0
    assert sum(cross["counts"]) == 2, "无薪资岗位不进入交叉统计"


@pytest.mark.asyncio
async def test_cross_edu_uses_normalized_education():
    await store.upsert_jobs([
        _job("f1", education="本科及以上", salary_min=20.0, salary_max=20.0),
        _job("f2", education="本科", salary_min=30.0, salary_max=30.0),
    ])

    cross = (await analytics.get_charts())["cross_edu"]
    i = cross["labels"].index("本科")

    assert cross["counts"][i] == 2, "'本科及以上' 应归一到 '本科'"
    assert cross["avg_salaries"][i] == 25.0


@pytest.mark.asyncio
async def test_keyword_filter():
    await store.upsert_jobs([
        _job("k1", keyword="Python"),
        _job("k2", keyword="Java", title="Java 开发工程师"),
    ])

    assert (await analytics.get_charts())["total"] == 2
    assert (await analytics.get_charts(keyword="Python"))["total"] == 1


@pytest.mark.asyncio
async def test_dirty_tags_do_not_break_aggregation():
    """单条历史脏 tags 不应让整批聚合失败"""
    await store.upsert_jobs([_job("t1"), _job("t2")])

    db = await store.get_db()
    try:
        await db.execute("UPDATE job_postings SET tags = 'not-a-json' WHERE source_id = 't1'")
        await db.commit()
    finally:
        await db.close()

    charts = await analytics.get_charts()
    assert charts["total"] == 2
    assert any(s["skill"] == "Python" for s in charts["skill"]), "其余正常记录仍应统计"
