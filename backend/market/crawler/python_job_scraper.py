"""
[AI 求职领航] 51job 实时采集模块(可参数化版本)。

从 job-crawler (https://github.com/cloudy-one1/job-crawler) 的
data/python_job_scraper.py 复制并改造:
- import 改为子包内相对导入(消除 sys.path 注入与顶层 data. 包依赖)
- 删除 __main__ 命令行块(该文件不再直接运行写库,由 tasks.py 后台线程驱动)
- 日志名改为 market.crawler

技术思路参考: https://github.com/gitychzh/jobSpider (无LICENSE声明,
本文件未直接复制该仓库代码,而是参考其"Playwright过WAF + 浏览器内fetch调用
真实API"的思路自行重写)。

依赖安装: pip install playwright playwright-stealth
         playwright install chromium

用法(被其他代码调用):
    from backend.market.crawler.python_job_scraper import scrape_jobs
    jobs, pages_collected = scrape_jobs(keyword='java', cities=['杭州', '成都'],
                                        pages_per_city=2, progress_callback=...,
                                        save_callback=...)
"""
import time
import random
import logging
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .job_site_dicts import (
    CITY_CODES,
    PROVINCE_MAP,
    CITY_PINYIN,
    JS_FETCH_API,
)

_logger = logging.getLogger('market.crawler')


def get_province_city_map():
    """返回 {省份名: [(城市名, 城市代码), ...]} 的映射,用于前端级联选择"""
    grouped = {}
    for city, code in CITY_CODES.items():
        prefix = code[:2]
        province = PROVINCE_MAP.get(prefix, f'其他({prefix})')
        grouped.setdefault(province, []).append((city, code))
    return grouped


def resolve_city_code(city_name):
    """把用户输入的城市名转成51job城市代码,找不到返回None"""
    city_name = city_name.strip()
    if city_name in CITY_CODES:
        return CITY_CODES[city_name]
    # 容错: 用户输入"广东"这种省份名,或者打错字带了"市"字,做一个宽松匹配。
    # 但只在输入长度合理(<=6个字符)时才做这个模糊匹配——
    # 真实城市/省份名不会很长,如果传进来的是一长串没拆开的文字
    # (比如逗号分隔符没识别导致多个城市名粘在一起),不应该被误判匹配上
    # 某个城市(这是实测踩到过的真实bug,城市拆分失败时曾经误判成功过)。
    if len(city_name) <= 6:
        for name, code in CITY_CODES.items():
            if name in city_name or city_name in name:
                return code
    return None


def build_api_params(keyword, job_area, page_num, sort_type='0'):
    return {
        'api_key': '51job',
        'timestamp': int(time.time() * 1000),
        'keyword': keyword,
        'searchType': '2',
        'jobArea': job_area,
        'issueDate': '4',
        'sortType': sort_type,
        'pageNum': page_num,
        'keywordType': '2',
        'pageSize': '20',
        'source': '1',
        'pageCode': 'sou|sou|soulb',
        'scene': '7',
    }


def _evaluate_with_timeout(page, js_func, params, timeout_ms=28000):
    """
    调用 page.evaluate() 并带上显式超时(默认28s), 处理超时与异常。

    返回值:
        (result_data, page_dead: bool)
        page_dead=True 表示页面可能已失效, 调用方应重建 page。

    说明:
        page.set_default_timeout() 控制的是 Playwright 内部事件循环的等待上限,
        但在浏览器进程半僵死时(time_wait状态/WebSocket半开), 内部超时可能也失效。
        此时本函数会阻塞至多 timeout_ms 毫秒后放弃, 并告知调用方重建页面。
    """
    from playwright.sync_api import TimeoutError as PWTimeoutError
    try:
        result = page.evaluate(js_func, params)
        return result, False
    except PWTimeoutError:
        _logger.warning('page.evaluate() 超时(%dms), 页面可能已僵死', timeout_ms)
        return {'error': f'evaluate超时({timeout_ms}ms)'}, True
    except Exception as e:
        err_msg = str(e).lower()
        # 连接断开/页面关闭类错误也意味着页面死亡
        if any(kw in err_msg for kw in ('closed', 'target closed', 'been closed',
                                          'websocket', 'connection', 'disconnected')):
            _logger.warning('page.evaluate() 连接断开: %s', e)
            return {'error': f'连接断开: {e}'}, True
        raise  # 其他异常继续上抛


def build_search_url(keyword, city_code, page_num=1):
    """51job PC 搜索页地址。

    导航到它只是为了拿到 WAF 放行的 cookie 与 referer 上下文——真正的数据靠页面内
    fetch 拿（见 JS_FETCH_API），所以两处 goto 都用 wait_until='commit' 不等 DOM。
    """
    return (
        f"https://we.51job.com/pc/search?keyword={keyword}&keywordType=2"
        f"&jobArea={city_code}&issuedDate=4&pageNum={page_num}&pageSize=20"
    )


def _job_address(job_area, city):
    """行政区串规整成 '城市-区-县'：缺城市前缀就补，整条缺失就退化成只剩城市。"""
    area = (job_area or '').strip()
    if not area:
        return city
    if area.startswith(city):
        return area.replace('·', '-')
    return f"{city}-{area.replace('·', '-')}"


def _job_content(job):
    """描述 + 标签 + 福利拼成 content，供后续分词与热词统计。"""
    parts = []
    desc = (job.get('jobDescription') or job.get('description') or '').strip()
    if desc:
        parts.append(desc)
    tags = job.get('jobTags') or []
    if tags:
        parts.append(' '.join(str(t) for t in tags))
    welfare = job.get('jobWelfareList') or []
    if welfare:
        parts.append(' '.join(str(w) for w in welfare))
    return ' '.join(parts).strip()


def to_job_record(job, city, scraped_at):
    """搜索 API 返回的一条 job → 项目 jobs 表的字段字典。

    job_url 依赖城市拼音表：表里没有的城市退化成 city.lower()；拿不到 jobId 时
    给空串，而不是拼出一个指向错误页的半个链接。
    """
    job_id = str(job.get('jobId', '') or job.get('jobid', '') or '')
    city_pinyin = CITY_PINYIN.get(city, city.lower())
    tags = job.get('jobTags') or []
    return {
        'post': (job.get('jobName') or '').strip(),
        'company': (job.get('companyName') or '').strip(),
        'address': _job_address(job.get('jobAreaString'), city),
        'salary_raw': (job.get('provideSalaryString') or '').strip(),
        'edu': (job.get('degreeString') or '').strip(),
        'exper': (job.get('workYearString') or '').strip(),
        'dateT': (job.get('issueDateString') or '').strip(),
        'scrape_date': scraped_at,
        'content': _job_content(job),
        # 单独的 keywords 字段：51job 给的标签（Java/Spring）比从描述里分词出来的精准
        'keywords': ' '.join(str(t).strip() for t in tags if str(t).strip()) if tags else '',
        'job_url': (
            f'https://jobs.51job.com/{city_pinyin}/{job_id}.html'
            if job_id and city_pinyin else ''
        ),
    }


def scrape_jobs(keyword, cities, pages_per_city=3, sort_type='0', progress_callback=None, save_callback=None):
    """
    核心函数: 给定关键词 + 城市名列表,实时采集51job数据。

    参数:
        keyword: 搜索关键词,比如 'python' / 'java'
        cities: 城市名列表,比如 ['北京', '上海'];传空列表时默认全国范围搜索
        pages_per_city: 每个城市采集几页,每页20条
        sort_type: 排序方式, '0'=综合排序(默认), '1'=最新发布
        progress_callback: 可选,一个函数(city, page, count) -> None,
                用于在网页上实时显示采集进度(比如Flask里可以传一个打印日志的函数)
        save_callback: 可选,一个函数(city, jobs_for_city) -> None,
                每采集完一个城市后调用,用于增量写入DB(防Ctrl+C丢数据)

    返回: list of dict,字段跟项目数据库schema一致
          (post, company, address, salary_raw, edu, exper, dateT, scrape_date)

    注意: 这个函数会真的打开一个无头浏览器访问51job,耗时通常是
          "5~10秒过WAF" + "每页约0.3秒",城市越多、页数越多越慢。
          调用方(比如Flask路由)要注意这是同步阻塞调用,不要在每个普通请求里
          都触发,只应该作为一个用户主动点击的"实时采集"动作。
    """
    valid_cities = []
    for c in cities:
        code = resolve_city_code(c)
        if code:
            valid_cities.append((c, code))

    if not valid_cities:
        # 没有指定城市 → 全国范围搜索
        valid_cities = [("全国", "000000")]

    all_jobs = []
    all_seen = set()
    pages_collected = {}  # city → 实际翻到的页数

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--lang=zh-CN',
            ],
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            extra_http_headers={
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
            },
        )
        Stealth().apply_stealth_sync(context)

        # CDP 层面彻底覆盖 navigator.webdriver 等自动化指纹
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            window.chrome = {runtime: {}};
        """)

        page = context.new_page()
        # 设置页面默认超时30秒: evaluate/navigation等操作超过30s自动抛异常
        # 解决最后一页JS fetch挂死导致Python主线程无限阻塞的问题
        page.set_default_timeout(30000)

        # 第一步: 先访问 51job 首页预热, 拿到 WAF 放行的 cookie
        # 用 wait_until='commit' 只要导航发生即可, 不等整个 DOM 加载完(首页太重)
        _logger.info('预热中: 访问 51job 首页获取 cookie...')
        try:
            page.goto('https://we.51job.com/', timeout=20000, wait_until='commit')
            # 模拟人类浏览: 随机滚动 + 停留
            time.sleep(random.uniform(1.5, 2.5))
            try:
                page.evaluate("window.scrollTo(0, 300)")
            except Exception:
                pass
            time.sleep(random.uniform(0.8, 1.5))
        except Exception as e:
            _logger.warning('首页预热超时/失败(%s), 直接尝试搜索页', e)

        # 第二步: 跳转到搜索页
        # 用 wait_until='commit' 只要导航发生即可——数据靠浏览器内 fetch API 获取,
        # 不依赖页面 DOM 渲染, 避免 51job 搜索页加载慢导致 domcontentloaded 超时
        first_code = valid_cities[0][1]
        try:
            page.goto(build_search_url(keyword, first_code), timeout=60000, wait_until='commit')
            # 给页面时间让 WAF cookie 落地 + 部分加载
            time.sleep(random.uniform(2.0, 3.0))
        except Exception as e:
            _logger.warning('搜索页加载超时/失败(%s), 尝试继续 fetch...', e)

        # WAF验证等待: 前15轮每0.5s(7.5s), 后20轮每1s(20s), 最多等30s
        waf_passed = False
        last_probe_err = None
        for round_idx in range(35):
            try:
                # 多信号检测: joblist 出现即认为通过
                cnt = page.evaluate(
                    "document.querySelectorAll('.joblist-item, .j_joblist, .el').length"
                )
                if cnt >= 1:
                    waf_passed = True
                    elapsed = round_idx * 0.5 if round_idx < 15 else 7.5 + (round_idx - 15)
                    _logger.info('WAF验证通过 (耗时约 %.1f 秒)', elapsed)
                    break
            except Exception as e:
                # 页面尚未渲染完时 querySelectorAll 就会抛，属正常轮询，逐轮打日志只会刷屏；
                # 但末次异常要带进超时告警，否则分不清"被 WAF 拦"和"浏览器已死"
                last_probe_err = e
            # 模拟人类: 每隔几轮随机小幅滚动, 避免被判定为机器人
            if round_idx > 0 and round_idx % 5 == 0:
                try:
                    page.evaluate(f"window.scrollTo(0, {random.randint(100, 500)})")
                except Exception:
                    pass
            wait_s = 0.5 if round_idx < 15 else 1.0
            time.sleep(wait_s)
        else:
            _logger.warning('WAF验证超时(30s), 51job可能拦截了请求, 尝试继续... '
                            '(末次探测异常: %s)',
                            last_probe_err if last_probe_err is not None
                            else '无——页面始终查不到职位列表')

        if waf_passed:
            # 通过 WAF 后再模拟一次人类停留, 让会话更自然
            time.sleep(random.uniform(0.5, 1.0))

        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        for city, code in valid_cities:
            _logger.info('开始采集: %s', city)
            pages_collected[city] = 0
            city_start_idx = len(all_jobs)  # 记录该城市采集前的数据量,用于增量保存
            _interrupted = False
            try:
                for pg in range(1, pages_per_city + 1):
                    # 单页硬超时: 每页(含重试)最多60秒, 超时跳过该城市后续页
                    page_start = time.time()
                    params = build_api_params(keyword, code, pg, sort_type)
                    # 前3页快速翻(模拟正常浏览),后面逐渐放慢避免触发风控
                    delay = random.uniform(0.1, 0.3) if pg <= 3 else random.uniform(0.3, 0.6)
                    time.sleep(delay)

                    # 单页重试机制: 最多尝试3次, 失败时模拟人类行为后重试
                    data = None
                    page_dead = False
                    for attempt in range(3):
                        # 检查是否超出单页总时限
                        if time.time() - page_start > 60:
                            _logger.warning('[%s] 第%d页超过60秒硬超时, 跳过该城市后续页', city, pg)
                            break
                        # 如果上一轮页面已失效, 先重建
                        if page_dead:
                            try:
                                page.close()
                            except Exception:
                                pass
                            page = context.new_page()
                            page.set_default_timeout(30000)
                            # 重建后需重新导航到搜索页, 否则 cookie/上下文丢失
                            try:
                                page.goto(build_search_url(keyword, code, pg),
                                          timeout=30000, wait_until='commit')
                                time.sleep(random.uniform(1.5, 2.5))
                            except Exception as nav_err:
                                _logger.warning('[%s] 页面重建后导航失败: %s', city, nav_err)
                            _logger.info('[%s] 重建浏览器页面(上次调用超时/断连)', city)
                            page_dead = False
                        try:
                            data, page_dead = _evaluate_with_timeout(page, JS_FETCH_API, params, timeout_ms=28000)
                        except Exception as e:
                            _logger.warning('[%s] 第%d页 evaluate 异常(尝试%d/3): %s', city, pg, attempt + 1, e)
                            data = None
                            if attempt < 2:
                                time.sleep(random.uniform(1.5, 3.0))
                            continue

                        if page_dead:
                            # 页面失效(超时/断连), 下一轮重建页面重试
                            if attempt < 2:
                                _logger.warning('[%s] 第%d页 调用失效(尝试%d/3): %s, 将重建页面重试...',
                                                city, pg, attempt + 1, data.get('error', 'unknown') if isinstance(data, dict) else 'unknown')
                                time.sleep(random.uniform(1.5, 2.5))
                                continue
                            else:
                                _logger.warning('[%s] 第%d页 调用失效(已重试3次), 跳过', city, pg)
                        elif isinstance(data, dict) and 'error' in data:
                            if attempt < 2:
                                _logger.warning('[%s] 第%d页 API 错误(尝试%d/3): %s, 模拟人类行为后重试...',
                                                city, pg, attempt + 1, data['error'])
                                # 重试前模拟人类: 滚到底停留再滚回顶
                                try:
                                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                    time.sleep(random.uniform(2.0, 4.0))
                                    page.evaluate("window.scrollTo(0, 0)")
                                    time.sleep(random.uniform(0.5, 1.0))
                                except Exception:
                                    pass
                                time.sleep(random.uniform(1.0, 2.0))
                                continue
                            else:
                                _logger.warning('[%s] 第%d页 API 错误(已重试3次): %s', city, pg, data['error'])
                        break

                    if data is None:
                        break
                    if isinstance(data, dict) and 'error' in data:
                        break

                    job_list = data.get('resultbody', {}).get('job', {}).get('items', [])
                    if not job_list:
                        break
                    pages_collected[city] += 1

                    added = 0
                    for j in job_list:
                        jid = str(j.get('jobId', ''))
                        title = (j.get('jobName') or '').strip()
                        if not jid or not title or jid in all_seen:
                            continue
                        all_seen.add(jid)
                        all_jobs.append(to_job_record(j, city, now))
                        added += 1

                    _logger.info('[%s] 第%d页: +%d条 (累计 %d)', city, pg, added, len(all_jobs))
                    if progress_callback:
                        progress_callback(city, pg, added)
                    if added == 0:
                        _logger.info('[%s] 第%d页无新数据, 跳过后续页', city, pg)
                        break
            except (KeyboardInterrupt, Exception) as e:
                if isinstance(e, KeyboardInterrupt):
                    _logger.warning('[%s] 采集被中断(Ctrl+C), 保存已采集数据...', city)
                    _interrupted = True
                else:
                    _logger.warning('[%s] 采集异常: %s', city, e)
            finally:
                # 无论正常结束/超时break/Ctrl+C中断,都把该城市已采集的数据写入DB
                if save_callback and len(all_jobs) > city_start_idx:
                    city_jobs = all_jobs[city_start_idx:]
                    try:
                        save_callback(city, city_jobs)
                        _logger.info('[%s] 已增量保存 %d 条到数据库', city, len(city_jobs))
                    except Exception as cb_e:
                        _logger.warning('[%s] 增量保存失败(不影响继续采集): %s', city, cb_e)
            if _interrupted:
                raise KeyboardInterrupt()

        page.close()
        browser.close()

    _logger.info('采集完成: 共 %d 条数据 (关键词=%s, 城市=%s)', len(all_jobs), keyword, cities)
    return all_jobs, pages_collected
