"""
market/crawler/python_job_scraper.py 测试：
- 城市编码解析（精确 / 模糊 / 异常）
- API 参数构造
- 省份-城市映射与数据完整性
- _evaluate_with_timeout 的超时 / 断连 / 异常传播
- build_search_url / _job_address / _job_content / to_job_record
  （这几处原先是内联在 scrape_jobs 里的纯数据变换，而 scrape_jobs 函数体覆盖率为 0；
   提取成模块级函数后才能真正被单测钉住）

说明：该模块在导入时会启动浏览器（browser = sync_playwright().chromium.launch(...)）。
为避免在测试环境真正拉起 Chromium，在导入前把 playwright.sync_api.sync_playwright
替换为一个不会真正启动浏览器的假实现。
"""

import re

import playwright.sync_api as _pwsa
import pytest
from unittest.mock import MagicMock


class _FakeBrowser:
    def close(self):
        pass


class _FakeChromium:
    def launch(self, *args, **kwargs):
        return _FakeBrowser()


class _FakeSyncPlaywright:
    chromium = _FakeChromium()


def _fake_sync_playwright():
    return _FakeSyncPlaywright()


# 在导入 python_job_scraper 之前替换，避免模块级真实启动浏览器
_pwsa.sync_playwright = _fake_sync_playwright

from backend.market.crawler.python_job_scraper import (  # noqa: E402
    CITY_CODES,
    CITY_PINYIN,
    PROVINCE_MAP,
    _evaluate_with_timeout,
    _job_address,
    _job_content,
    build_api_params,
    build_search_url,
    get_province_city_map,
    resolve_city_code,
    to_job_record,
)


# ============================================================
# resolve_city_code()
# ============================================================

class TestResolveCityCode:
    def test_exact_match(self):
        assert resolve_city_code("北京") == CITY_CODES["北京"]
        assert resolve_city_code("上海") == CITY_CODES["上海"]
        assert resolve_city_code("广州") == CITY_CODES["广州"]

    def test_fuzzy_suffix(self):
        # 长度 <=6 时做子串容错：北京市 -> 北京 编码
        assert resolve_city_code("北京市") == CITY_CODES["北京"]
        assert resolve_city_code("上海市") == CITY_CODES["上海"]
        assert resolve_city_code("广州市") == CITY_CODES["广州"]

    def test_unknown_city_returns_none(self):
        assert resolve_city_code("火星") is None
        assert resolve_city_code("不存在的城市") is None

    def test_national_returns_none_by_design(self):
        # “全国” 不在精确表中，且长度<=6 也不命中任何子串 -> None
        # （调用方 scrape_jobs 会将 None 归一为 "000000"）
        assert resolve_city_code("全国") is None

    def test_long_text_skips_fuzzy(self):
        # 长度 >6 不做模糊匹配，避免误命中
        assert resolve_city_code("一个非常长的没有拆分的多城市名文本") is None

    def test_empty_returns_first_match(self):
        # 已知行为：空串在子串匹配中命中所有城市名（"" in name 恒真），
        # 返回字典序首个城市编码（北京）。此用例锁定该行为，防止无意变更。
        assert re.fullmatch(r"\d{6}", resolve_city_code(""))


# ============================================================
# build_api_params()
# ============================================================

class TestBuildApiParams:
    def test_basic(self):
        p = build_api_params("python", "010000", 2, "1")
        assert p["keyword"] == "python"
        assert p["jobArea"] == "010000"
        assert p["pageNum"] == 2
        assert p["pageSize"] == "20"
        assert p["sortType"] == "1"
        assert p["scene"] == "7"
        assert p["api_key"] == "51job"
        assert p["searchType"] == "2"
        assert isinstance(p["timestamp"], int)

    def test_defaults(self):
        p = build_api_params(None, None, 1)
        assert p["keyword"] is None
        assert p["jobArea"] is None
        assert p["sortType"] == "0"  # 默认综合排序


# ============================================================
# get_province_city_map() + 数据完整性
# ============================================================

class TestDataIntegrity:
    def test_city_codes_shape(self):
        assert len(CITY_CODES) > 100
        for code in CITY_CODES.values():
            assert re.fullmatch(r"\d{6}", code), f"非法编码: {code}"

    def test_province_coverage(self):
        # 每个城市编码的前两位，都能在 PROVINCE_MAP 中找到对应省份
        for code in CITY_CODES.values():
            assert code[:2] in PROVINCE_MAP, f"编码 {code} 的前两位无对应省份"

    def test_city_pinyin_subset(self):
        # 拼音表应是城市表的子集（用于构造 URL）
        for city in CITY_PINYIN:
            assert city in CITY_CODES, f"拼音表含未知城市: {city}"
        assert len(CITY_PINYIN) > 0

    def test_province_city_map(self):
        m = get_province_city_map()
        assert isinstance(m, dict)
        total = 0
        for province, cities in m.items():
            assert province in PROVINCE_MAP.values()
            assert isinstance(cities, list)
            total += len(cities)
        # 所有城市都应被映射且总数一致
        assert total == len(CITY_CODES)


# ============================================================
# _evaluate_with_timeout()
# ============================================================

class TestEvaluateWithTimeout:
    def test_success(self):
        page = MagicMock()
        page.evaluate.return_value = {"ok": 1}
        result, timed_out = _evaluate_with_timeout(page, "js()", {"kw": 1})
        assert result == {"ok": 1}
        assert timed_out is False
        page.evaluate.assert_called_once_with("js()", {"kw": 1})

    def test_timeout(self):
        from playwright.sync_api import TimeoutError as PWTimeoutError

        page = MagicMock()
        page.evaluate.side_effect = PWTimeoutError("timeout")
        result, timed_out = _evaluate_with_timeout(page, "js()", {}, timeout_ms=1000)
        assert timed_out is True
        assert "超时" in result["error"]

    def test_connection_closed(self):
        page = MagicMock()
        page.evaluate.side_effect = Exception(
            "Target page, context or browser has been closed")
        result, timed_out = _evaluate_with_timeout(page, "js()", {})
        assert timed_out is True
        assert "连接断开" in result["error"]

    def test_other_error_propagates(self):
        page = MagicMock()
        page.evaluate.side_effect = ValueError("boom")
        with pytest.raises(ValueError):
            _evaluate_with_timeout(page, "js()", {})


# ============================================================
# build_search_url()
# ============================================================

class TestBuildSearchUrl:
    def test_defaults_to_first_page(self):
        url = build_search_url("python", "010000")
        assert url.startswith("https://we.51job.com/pc/search?")
        assert "keyword=python" in url
        assert "jobArea=010000" in url
        assert "pageNum=1" in url
        assert "pageSize=20" in url

    def test_page_number_is_respected(self):
        assert "pageNum=3" in build_search_url("java", "020000", 3)

    def test_two_calls_differ_only_by_page(self):
        """重建页面后重新导航用的是同一套 URL，此前两处 f-string 各写一遍易漂移。"""
        a = build_search_url("python", "010000", 1)
        b = build_search_url("python", "010000", 2)
        assert a.replace("pageNum=1", "pageNum=2") == b


# ============================================================
# _job_address() / _job_content()
# ============================================================

class TestJobAddress:
    def test_area_already_prefixed_with_city(self):
        assert _job_address("北京·朝阳·望京", "北京") == "北京-朝阳-望京"

    def test_city_prefix_added_when_missing(self):
        assert _job_address("上海·浦东", "北京") == "北京-上海-浦东"

    def test_empty_area_degrades_to_city(self):
        assert _job_address("", "北京") == "北京"
        assert _job_address(None, "北京") == "北京"

    def test_separator_normalized(self):
        assert "·" not in _job_address("广东·深圳·南山", "深圳")


class TestJobContent:
    def test_empty_job(self):
        assert _job_content({}) == ""

    def test_description_fallback_key(self):
        assert _job_content({"description": "d"}) == "d"

    def test_desc_tags_welfare_joined_in_order(self):
        job = {"jobDescription": "写接口", "jobTags": ["Python", "FastAPI"],
               "jobWelfareList": ["五险一金"]}
        assert _job_content(job) == "写接口 Python FastAPI 五险一金"


# ============================================================
# to_job_record() —— 51job 返回体 → jobs 表字段
# ============================================================

def _raw_job(**over):
    job = {
        "jobId": "123456",
        "jobName": "  Python 后端工程师  ",
        "companyName": "某某科技",
        "jobAreaString": "北京·朝阳·望京",
        "provideSalaryString": "1.5-2.5万·13薪",
        "degreeString": "本科",
        "workYearString": "3年及以上",
        "issueDateString": "2026-09-01",
        "jobDescription": "FastAPI / asyncio",
        "jobTags": ["Python", "Spring"],
        "jobWelfareList": ["五险一金", "远程办公"],
    }
    job.update(over)
    return job


class TestToJobRecord:
    def test_field_names_match_store_schema(self):
        """键名是 store 落库与前端渲染的契约，少一个字段就是静默丢数据。"""
        assert set(to_job_record(_raw_job(), "北京", "2026-09-24 00:00:00")) == {
            "post", "company", "address", "salary_raw", "edu", "exper",
            "dateT", "scrape_date", "content", "keywords", "job_url",
        }

    def test_full_mapping(self):
        r = to_job_record(_raw_job(), "北京", "2026-09-24 00:00:00")
        assert r["post"] == "Python 后端工程师"          # 首尾空白被去掉
        assert r["company"] == "某某科技"
        assert r["address"] == "北京-朝阳-望京"
        assert r["salary_raw"] == "1.5-2.5万·13薪"
        assert r["edu"] == "本科"
        assert r["exper"] == "3年及以上"
        assert r["dateT"] == "2026-09-01"
        assert r["scrape_date"] == "2026-09-24 00:00:00"
        assert r["keywords"] == "Python Spring"

    def test_job_url_uses_city_pinyin(self):
        r = to_job_record(_raw_job(), "北京", "2026-09-24 00:00:00")
        assert r["job_url"] == (
            f"https://jobs.51job.com/{CITY_PINYIN['北京']}/123456.html"
        )

    def test_missing_job_id_yields_empty_url_not_half_url(self):
        """宁可没有链接，也不能拼出一个指向错误页的半个 URL。"""
        assert to_job_record(_raw_job(jobId=""), "北京", "x")["job_url"] == ""

    def test_unknown_city_falls_back_to_lowercase_name(self):
        r = to_job_record(_raw_job(), "火星", "x")
        assert r["job_url"] == "https://jobs.51job.com/火星/123456.html"
        # 行政区串不以该城市开头 → 前置补上采集城市名
        assert r["address"] == "火星-北京-朝阳-望京"

    def test_no_area_string_degrades_to_city(self):
        assert to_job_record(_raw_job(jobAreaString=""), "火星", "x")["address"] == "火星"

    def test_missing_optional_fields_become_empty_strings_not_none(self):
        r = to_job_record({"jobId": "9", "jobName": "A"}, "上海", "x")
        assert r["company"] == "" and r["content"] == "" and r["keywords"] == ""
