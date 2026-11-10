"""
market/crawler/scrapling_fallback.py 与 tasks.py 回落派发测试。

真实引擎需要 scrapling + Camoufox 浏览器（另有真机冒烟验证），这里只覆盖：
1. _find_api_response / _extract_items 纯逻辑（响应筛选不依赖 scrapling 类型）
2. scrapling 未安装时的 ScraplingNotAvailable 降级
3. tasks._run_crawl 的回落派发状态机（假件替换 scrape_jobs，不触发真采集）
"""

import json
import sys

import pytest

from backend.market.crawler import scrapling_fallback, tasks
from backend.market.crawler.python_job_scraper import CrawlCancelled


# ---------- 假件 ----------

def _api_url(job_area="530300", page_num=1):
    return (
        "https://we.51job.com/api/job/search-pc"
        f"?api_key=51job&timestamp=1700000000&keyword=python&jobArea={job_area}"
        f"&pageNum={page_num}&pageSize=20"
    )


def _job_item(job_id="1", name="Python开发"):
    return {"jobId": job_id, "jobName": name, "companyName": "某公司",
            "provideSalaryString": "1-2万"}


def _good_body(job_id="1"):
    return json.dumps({"status": "1", "resultbody": {"job": {"items": [_job_item(job_id)]}}}).encode()


_CHALLENGE = (
    b'<textarea id="renderData" style="display:none">'
    b'{"_waf_bd8ce2ce37":"abc"}</textarea><!doctype html>'
)


class _FakeRecord:
    def __init__(self, url, body):
        self.url = url
        self.body = body
        self.meta = {}


class _FakeNetwork:
    def __init__(self, records):
        self._records = records

    def search(self, url_pattern=None, limit=None):
        return list(self._records)


class _FakeSession:
    def __init__(self, records):
        self.network = _FakeNetwork(records)


# ---------- _extract_items / _find_api_response ----------

class TestExtractItems:
    def test_normal(self):
        data = json.loads(_good_body())
        items = scrapling_fallback._extract_items(data)
        assert len(items) == 1 and items[0]["jobId"] == "1"

    def test_non_dict_or_missing_keys(self):
        assert scrapling_fallback._extract_items(None) == []
        assert scrapling_fallback._extract_items("x") == []
        assert scrapling_fallback._extract_items({}) == []
        assert scrapling_fallback._extract_items({"resultbody": {}}) == []
        # 结构变更：items 不是列表 → 空列表而非抛错
        assert scrapling_fallback._extract_items(
            {"resultbody": {"job": {"items": "oops"}}}) == []


class TestFindApiResponse:
    def test_challenge_only_returns_none(self):
        session = _FakeSession([_FakeRecord(_api_url(), _CHALLENGE)])
        assert scrapling_fallback._find_api_response(session, "530300", 1) is None

    def test_good_response_returned(self):
        session = _FakeSession([_FakeRecord(_api_url(), _CHALLENGE),
                                _FakeRecord(_api_url(), _good_body("9"))])
        data = scrapling_fallback._find_api_response(session, "530300", 1)
        assert data is not None
        assert scrapling_fallback._extract_items(data)[0]["jobId"] == "9"

    def test_page_num_must_match(self):
        session = _FakeSession([_FakeRecord(_api_url(page_num=2), _good_body())])
        assert scrapling_fallback._find_api_response(session, "530300", 1) is None

    def test_job_area_must_match(self):
        session = _FakeSession([_FakeRecord(_api_url(job_area="000000"), _good_body())])
        assert scrapling_fallback._find_api_response(session, "530300", 1) is None

    def test_newest_match_wins(self):
        session = _FakeSession([
            _FakeRecord(_api_url(), _good_body("old")),
            _FakeRecord(_api_url(), _CHALLENGE),          # 中间夹一条挑战页
            _FakeRecord(_api_url(), _good_body("new")),
        ])
        data = scrapling_fallback._find_api_response(session, "530300", 1)
        assert scrapling_fallback._extract_items(data)[0]["jobId"] == "new"


# ---------- scrapling 未安装降级 ----------

class TestScraplingNotAvailable:
    def test_missing_package_raises_typed_error(self, monkeypatch):
        # sys.modules 里放 None → from scrapling.fetchers import ... 抛 ImportError
        monkeypatch.setitem(sys.modules, "scrapling.fetchers", None)
        with pytest.raises(scrapling_fallback.ScraplingNotAvailable):
            scrapling_fallback.scrape_jobs_scrapling("python", ["北京"], 1)


# ---------- tasks._run_crawl 回落派发状态机 ----------

def _full_record(post="Python开发"):
    """构造 adapters.to_standard_job 可消费的最小原始记录（字段全 .get 容错）。"""
    return {"post": post, "company": "某公司", "address": "北京-朝阳",
            "salary_raw": "1-2万", "edu": "本科", "exper": "3-5年",
            "dateT": "", "scrape_date": "2026-11-11 00:00:00",
            "content": "职责描述", "keywords": "Python", "job_url": ""}


class TestRunCrawlFallbackDispatch:
    """回落派发：主路径异常/整场空手而归触发回落；取消不触发；错误不掩盖。"""

    def setup_method(self):
        tasks._tasks.clear()

    def teardown_method(self):
        tasks._tasks.clear()

    def _make_task(self, task_id="fb1"):
        task = tasks.CrawlTask(id=task_id, keyword="python", cities=["北京"],
                               pages=1, sort_type="0")
        tasks._tasks[task.id] = task
        return task

    def _patch_store(self, monkeypatch):
        async def fake_upsert(standard):
            return 0
        monkeypatch.setattr(tasks.store, "upsert_jobs", fake_upsert)

    def _patch_primary(self, monkeypatch, fn):
        monkeypatch.setattr(
            "backend.market.crawler.python_job_scraper.scrape_jobs", fn)

    def _patch_fallback(self, monkeypatch, fn):
        monkeypatch.setattr(
            "backend.market.crawler.scrapling_fallback.scrape_jobs_scrapling", fn)

    def test_primary_success_skips_fallback(self, monkeypatch):
        self._patch_store(monkeypatch)
        self._patch_primary(
            monkeypatch, lambda **kw: ([_full_record()], {"北京": 1}))
        fallback_calls = []

        def _spy(**kw):
            fallback_calls.append(kw)
            return ([], {})
        self._patch_fallback(monkeypatch, _spy)
        self._make_task()
        tasks._run_crawl("fb1")
        assert fallback_calls == []
        assert tasks._tasks["fb1"].status == "done"

    def test_primary_empty_triggers_fallback(self, monkeypatch):
        """主路径'成功但整场 0 条'是 WAF 静默拦截的典型形态，必须回落。"""
        self._patch_store(monkeypatch)
        self._patch_primary(monkeypatch, lambda **kw: ([], {"北京": 0}))
        self._patch_fallback(
            monkeypatch, lambda **kw: ([_full_record("回落岗位")], {"北京": 1}))
        self._make_task()
        tasks._run_crawl("fb1")
        assert tasks._tasks["fb1"].status == "done"
        assert "回落" in tasks._tasks["fb1"].message or \
               "1" in tasks._tasks["fb1"].message

    def test_primary_error_triggers_fallback(self, monkeypatch):
        self._patch_store(monkeypatch)

        def _boom(**kw):
            raise RuntimeError("WAF 拦截模拟")
        self._patch_primary(monkeypatch, _boom)
        self._patch_fallback(
            monkeypatch, lambda **kw: ([_full_record("回落岗位")], {"北京": 1}))
        self._make_task()
        tasks._run_crawl("fb1")
        assert tasks._tasks["fb1"].status == "done"

    def test_primary_error_fallback_disabled_keeps_original_error(self, monkeypatch):
        """回落关闭时维持原失败语义，错误信息不被回落层掩盖。"""
        self._patch_store(monkeypatch)
        monkeypatch.setattr(
            "backend.config.config.MARKET_CRAWL_SCRAPLING_FALLBACK", False)

        def _boom(**kw):
            raise RuntimeError("原始错误信息")
        self._patch_primary(monkeypatch, _boom)
        self._patch_fallback(
            monkeypatch, lambda **kw: (_ for _ in ()).throw(
                AssertionError("回落被关闭时不应调用")))
        self._make_task()
        tasks._run_crawl("fb1")
        task = tasks._tasks["fb1"]
        assert task.status == "failed"
        assert "原始错误信息" in task.error

    def test_primary_error_fallback_fails_also_keeps_original_error(self, monkeypatch):
        self._patch_store(monkeypatch)

        def _boom(**kw):
            raise RuntimeError("原始错误信息")
        self._patch_primary(monkeypatch, _boom)

        def _fallback_boom(**kw):
            raise RuntimeError("回落也炸了")
        self._patch_fallback(monkeypatch, _fallback_boom)
        self._make_task()
        tasks._run_crawl("fb1")
        task = tasks._tasks["fb1"]
        assert task.status == "failed"
        assert "原始错误信息" in task.error

    def test_cancel_propagates_and_skips_fallback(self, monkeypatch):
        """取消/硬超时不是技术故障，穿透回落直接落终态。"""
        self._patch_store(monkeypatch)

        def _cancel(**kw):
            raise CrawlCancelled("采集被取消")
        self._patch_primary(monkeypatch, _cancel)
        self._patch_fallback(
            monkeypatch, lambda **kw: (_ for _ in ()).throw(
                AssertionError("取消后不应触发回落")))
        self._make_task().cancel_requested = True
        tasks._run_crawl("fb1")
        task = tasks._tasks["fb1"]
        assert task.status == "cancelled"
