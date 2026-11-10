"""
[AI 求职领航] 51job 实时采集 Scrapling 回落引擎（v8.22）。

Playwright 主路径（python_job_scraper.scrape_jobs）失败或整场空手而归时，
用 Scrapling StealthySession（Camoufox 反指纹浏览器）过 WAF 取数：
导航让 SPA 自己过 WAF 并发出 search-pc XHR，``record_requests`` 被动捕获
响应 JSON；翻页用 ``page_action`` 点击分页器"下一页"，让 SPA 自己发出
带 WAF 戳的 pageNum=N XHR 后同样被动捕获——全程无需注入任何 JS。

取数通路的三次实测结论（2026-11-11，证据链见 CHANGELOG v8.22）：
1. 纯 HTTP 直调 search-pc 返回 ``_waf_bd8ce2ce37`` JS 挑战页 → 必须真实浏览器；
2. Camoufox 页内 evaluate 注入 fetch（主路径 JS_FETCH_API 同款）即使 DOM 已
   渲染、轮询 20s 仍被 WAF 挑战 → 挑战是**指纹级**的：SPA 自己的 XHR 带
   WAF JS 钩子盖的 ``decode__1048`` 戳所以放行，注入的裸 fetch 在 Firefox
   指纹下不放行（主路径 Chromium 指纹下裸 fetch 可过，两引擎行为不同）；
3. 点击 ``.el-pagination .btn-next`` 后 SPA 发出的 pageNum=2 XHR（带戳）
   正常返回 174KB JSON → 翻页通路成立。

为什么不能靠导航翻页（静态根因，bundle 逆向）：搜索页组件 SearchResult
（chunk-419adfef）的 data() 把 ``pageNum:1`` 硬编码，URL query 只读
jobArea/keyword/landmark/metro——全新导航携带 pageNum=2 时页面自身 XHR
仍拉第 1 页（运行时诊断与静态证据一致）。

依赖（可选，未安装时回落自动跳过、主路径语义不变）:
    pip install "scrapling[all]"
    scrapling install --force

契约与主路径 ``scrape_jobs`` 对齐:
    scrape_jobs_scrapling(keyword, cities, pages_per_city=3, sort_type='0',
                          progress_callback=None, should_cancel=None)
        -> (jobs, pages_collected)

已知取舍:
- 取消检查点为城市级：一城内的翻页点击序列（≤4 次 × 4s）不可中断，
  取消最坏延迟 ≈ 单城总时长（约 25s），远小于主路径单页 60s 硬超时；
- sort_type 不生效：SPA 既不读 URL 里的 sortType，注入 fetch 通道又已死，
  回落路径固定综合排序（回落定位是应急通道，不为排序保真加复杂度）；
- 翻页点击落在末页/无第 2 页时 element-ui 按钮禁用 → click 超时中断，
  多余页在历史里不存在 → 引擎按"无数据即停"自然收口。
"""
import json
import logging
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

_PAGE_TIMEOUT_MS = 60000     # 单次导航硬超时（与主路径 page.set_default_timeout 同量级）
_NAV_ATTEMPTS = 2            # 城市级导航重试次数
_CLICK_WAIT_MS = 4000        # 每次点"下一页"后等 SPA 发出并落好 XHR（实测 4s 足够）
_CLICK_TIMEOUT_MS = 5000     # btn-next 不可点（末页/单页结果）时的 click 超时
_NEXT_BTN = ".el-pagination .btn-next"  # element-ui 分页器"下一页"按钮


class ScraplingNotAvailable(RuntimeError):
    """scrapling 未安装或浏览器未就绪——回落链据此判断"回落不可用"。"""


def scrape_jobs_scrapling(keyword, cities, pages_per_city=3, sort_type='0',
                          progress_callback=None, should_cancel=None):
    """Scrapling(Camoufox) 回落采集：参数与返回值同 python_job_scraper.scrape_jobs。

    - cities 传空列表时默认全国范围搜索（与主路径一致）；
    - should_cancel 在城市间检查点轮询，命中即抛 CrawlCancelled；
    - 未安装 scrapling 时抛 ScraplingNotAvailable（调用方决定是否降级）；
    - sort_type 仅保持签名兼容，本通道不生效（见模块 docstring 取舍）。
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
                page_datas = _fetch_city_pages(session, keyword, code, pages_per_city)
                for pg in range(1, pages_per_city + 1):
                    items = _extract_items(page_datas.get(pg))
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


def _fetch_city_pages(session, keyword, code, pages_per_city):
    """一城一次导航：过 WAF 后点击"下一页"驱动 SPA 翻页，从网络历史回收各页 JSON。

    返回 {pg: data_dict}（缺失页无键）。SPA 的 XHR 带 WAF 钩子盖的
    ``decode__1048`` 戳所以放行（见模块 docstring），本函数绝不自己发请求。
    """
    url = build_search_url(keyword, code, 1)

    def _action(page):
        # page_action 在导航+load_dom+network_idle 之后执行（_stealth.py:298），
        # 此时第 1 页已由 SPA 自己拉好。逐次点"下一页"，每次等 XHR 落地。
        for _ in range(max(0, pages_per_city - 1)):
            page.locator(_NEXT_BTN).first.click(timeout=_CLICK_TIMEOUT_MS)
            page.wait_for_timeout(_CLICK_WAIT_MS)

    for attempt in range(1, _NAV_ATTEMPTS + 1):
        try:
            # 点击序列的异常（末页按钮禁用等）被 Scrapling 吞掉只记日志
            # （_stealth.py:302），不影响 fetch 返回；已点出的页仍可从历史回收
            session.fetch(url, timeout=_PAGE_TIMEOUT_MS, network_idle=True,
                          page_action=_action)
        except Exception as e:
            _logger.warning('[Scrapling回落] 导航失败(尝试%d/%d): %s',
                            attempt, _NAV_ATTEMPTS, e)
            time.sleep(1.5)
            continue
        out = {}
        for pg in range(1, pages_per_city + 1):
            data = _find_api_response(session, code, pg)
            if data is not None:
                out[pg] = data
        if out:
            return out
        time.sleep(1.5)  # WAF 挑战自动重试可能稍晚才落进历史，稍候再试一轮
    return {}


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
