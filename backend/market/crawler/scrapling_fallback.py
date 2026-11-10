"""
[AI 求职领航] 51job 实时采集 Scrapling 回落引擎（v8.22）。

Playwright 主路径（python_job_scraper.scrape_jobs）失败或整场空手而归时，
用 Scrapling StealthySession（Camoufox 反指纹浏览器）过 WAF，并通过
``record_requests`` 被动捕获页面自己发出的 search-pc JSON 响应——
无需注入任何 JS（主路径的 JS_FETCH_API 注入串在此路径完全不需要维护）。

实测记录（2026-11-11，single-run）:
- 纯 HTTP 直调 search-pc 返回 ``_waf_bd8ce2ce37`` JS 挑战页 → 必须真实浏览器；
- Camoufox 打开搜索页即可过 WAF（页面自身 XHR 被挑战一次后自动重试成功）；
- 会话网络历史可取到完整 JSON（约 200KB/页、20 条），DOM 与 JSON 双通道可用；
- StealthySession 暂无 cookie 导出口 → "浏览器预热一次、翻页走纯 HTTP"
  的混合模式在本版本做不到，每页都由页面导航自身触发（每页约 3~6 秒）。

依赖（可选，未安装时回落自动跳过、主路径语义不变）:
    pip install "scrapling[all]"
    scrapling install --force

契约与主路径 ``scrape_jobs`` 对齐:
    scrape_jobs_scrapling(keyword, cities, pages_per_city=3, sort_type='0',
                          progress_callback=None, should_cancel=None)
        -> (jobs, pages_collected)
取消: should_cancel 在页间检查点轮询，命中即抛主路径的 CrawlCancelled，
由 tasks.py 统一落终态（回落路径不自定义取消类型）。

已知取舍:
- 【翻页限制】SPA 全新导航时忽略 URL 里的 pageNum（实测携带 pageNum=2 打开
  搜索页，页面自身 XHR 仍拉 pageNum=1，2026-11-11 诊断记录）——翻页需页面内
  交互触发，本通道做不到。因此回落路径每城取第 1 页（20 条）；多页需求由
  主路径满足。pages_per_city 循环保留：若 SPA 将来支持 pageNum 直达，自动生效。
- sort_type 以 URL 参数追加透传，SPA 是否尊重未验证——回落路径排序可能
  退化为默认综合排序（回落定位是应急通道，不为排序保真加复杂度）。
- 每页数据靠"导航到搜索 URL → 页面自身 XHR → 网络历史捞取"，
  页面结构再怎么改版，只要页面自己还调 search-pc 就能拿到数据。
"""
import json
import logging
import random
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from .python_job_scraper import (
    CrawlCancelled,
    build_search_url,
    resolve_city_code,
    to_job_record,
)

_logger = logging.getLogger('market.crawler')

_PAGE_TIMEOUT_MS = 60000  # 单页导航硬超时（与主路径 page.set_default_timeout 同量级）
_MAX_NAV_ATTEMPTS = 2     # 单页导航重试次数：首次可能只留下 WAF 挑战响应


class ScraplingNotAvailable(RuntimeError):
    """scrapling 未安装或浏览器未就绪——回落链据此判断"回落不可用"。"""


def scrape_jobs_scrapling(keyword, cities, pages_per_city=3, sort_type='0',
                          progress_callback=None, should_cancel=None):
    """Scrapling(Camoufox) 回落采集：参数与返回值同 python_job_scraper.scrape_jobs。

    - cities 传空列表时默认全国范围搜索（与主路径一致）；
    - should_cancel 在城市间/页间检查点轮询，命中即抛 CrawlCancelled；
    - 未安装 scrapling 时抛 ScraplingNotAvailable（调用方决定是否降级）。
    """
    try:
        from scrapling.fetchers import StealthySession  # noqa: PLC0415
    except ImportError as e:
        raise ScraplingNotAvailable(
            'scrapling 未安装或不可用：pip install "scrapling[all]" '
            '且 scrapling install --force（安装 Camoufox 浏览器）'
        ) from e

    valid_cities = []
    for c in cities:
        code = resolve_city_code(c)
        if code:
            valid_cities.append((c, code))
    if not valid_cities:
        valid_cities = [("全国", "000000")]

    if pages_per_city > 1:
        _logger.info(
            '[Scrapling回落] pages_per_city=%d：本通道实测每城只能取第1页'
            '（SPA 忽略 URL pageNum，见模块 docstring），多页由主路径满足',
            pages_per_city,
        )

    def _check_cancel():
        if should_cancel is not None and should_cancel():
            raise CrawlCancelled('采集被取消或超过硬超时（Scrapling 回落路径检查点）')

    all_jobs = []
    all_seen = set()
    pages_collected = {}
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    with StealthySession(headless=True, record_requests=True) as session:
        for city, code in valid_cities:
            _check_cancel()
            _logger.info('[Scrapling回落] 开始采集: %s', city)
            pages_collected[city] = 0
            try:
                for pg in range(1, pages_per_city + 1):
                    _check_cancel()
                    # 页间轻节流：回落是应急通道，宁可慢一点也别加重风控
                    time.sleep(random.uniform(0.2, 0.5))
                    data = _fetch_page_json(session, keyword, code, pg, sort_type)
                    items = _extract_items(data)
                    if not items:
                        _logger.info('[Scrapling回落][%s] 第%d页无数据, 跳过后续页', city, pg)
                        break
                    pages_collected[city] += 1

                    added = 0
                    for j in items:
                        jid = str(j.get('jobId', ''))
                        title = (j.get('jobName') or '').strip()
                        if not jid or not title or jid in all_seen:
                            continue
                        all_seen.add(jid)
                        all_jobs.append(to_job_record(j, city, now))
                        added += 1
                    _logger.info('[Scrapling回落][%s] 第%d页: +%d条 (累计 %d)',
                                 city, pg, added, len(all_jobs))
                    if progress_callback:
                        progress_callback(city, pg, added)
                    if added == 0:
                        _logger.info('[Scrapling回落][%s] 第%d页无新数据, 跳过后续页', city, pg)
                        break
            except CrawlCancelled:
                raise
            except Exception as e:
                _logger.warning('[Scrapling回落][%s] 采集异常(跳到下一城): %s', city, e)

    _logger.info('[Scrapling回落] 采集完成: 共 %d 条 (关键词=%s, 城市=%s)',
                 len(all_jobs), keyword, cities)
    return all_jobs, pages_collected


def _fetch_page_json(session, keyword, code, pg, sort_type='0'):
    """导航到第 pg 页搜索页，从会话网络历史里捞出对应 search-pc JSON。

    页面自身 XHR 首次会被 WAF 挑战、随后自动重试，历史里可能残留挑战响应；
    所以按 jobArea+pageNum 过滤并取含 resultbody 的最新一条。拿不到返回 None。
    """
    url = build_search_url(keyword, code, pg)
    if sort_type and sort_type != '0':
        url += f'&sortType={sort_type}'
    for attempt in range(1, _MAX_NAV_ATTEMPTS + 1):
        try:
            session.fetch(url, timeout=_PAGE_TIMEOUT_MS, network_idle=True)
        except Exception as e:
            _logger.warning('[Scrapling回落] 第%d页导航失败(尝试%d/%d): %s',
                            pg, attempt, _MAX_NAV_ATTEMPTS, e)
            time.sleep(1.5)
            continue
        data = _find_api_response(session, code, pg)
        if data is not None:
            return data
        time.sleep(1.5)  # WAF 挑战自动重试可能稍晚才落进历史，稍候再试一轮
    return None


def _find_api_response(session, code, pg):
    """在会话网络历史里找 (jobArea=code, pageNum=pg) 且含 resultbody 的最新响应。

    纯逻辑函数（session 只需鸭子类型提供 network.search）——响应筛选不依赖
    scrapling 类型，方便单测。
    """
    try:
        matches = session.network.search(url_pattern=r'search-pc', limit=None)
    except Exception as e:
        _logger.warning('[Scrapling回落] 网络历史检索失败: %s', e)
        return None
    for record in reversed(matches):  # 最新优先
        try:
            qs = parse_qs(urlparse(record.url).query)
        except Exception:
            continue
        if qs.get('jobArea', [''])[0] != code:
            continue
        if qs.get('pageNum', [''])[0] != str(pg):
            continue
        raw = _record_body(record)
        if b'"resultbody"' not in raw:
            continue  # WAF 挑战页（textarea 包着 _waf cookie）
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if _extract_items(data):
            return data
    return None


def _record_body(record):
    """兼容 body_note / body / str / bytes 的响应体读取，统一为 bytes。"""
    body = record.meta.get('body_note') or record.body
    if isinstance(body, str):
        return body.encode('utf-8', 'replace')
    return body or b''


def _extract_items(data):
    """search-pc JSON → job items 列表；结构变更时安全退化为空列表。"""
    if not isinstance(data, dict):
        return []
    resultbody = data.get('resultbody')
    if not isinstance(resultbody, dict):
        return []
    job = resultbody.get('job')
    if not isinstance(job, dict):
        return []
    items = job.get('items')
    return items if isinstance(items, list) else []
