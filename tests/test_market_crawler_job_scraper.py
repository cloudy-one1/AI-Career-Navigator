"""
market/crawler/python_job_scraper.py 测试：
- 城市编码解析（精确 / 模糊 / 异常）
- API 参数构造
- 省份-城市映射与数据完整性
- _evaluate_with_timeout 的超时 / 断连 / 异常传播

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
    build_api_params,
    get_province_city_map,
    resolve_city_code,
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
