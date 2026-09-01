"""市场域：岗位画像研究 + 市场数据导入/检索/统计 + 实时采集（job-crawler B 档内嵌）。"""
import logging
import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request

from .. import db
from ..config import config
from ..market import store as market_store, service as market_service
from ..market import analytics as market_analytics, insight as market_insight
from ..market.crawler import tasks as crawler_tasks
from ..market.crawler.adapters import build_jd_text
from ..web_research import enrich_jd_with_research
from . import state

logger = logging.getLogger(__name__)
router = APIRouter()


async def _annotate_in_library(jobs: list) -> None:
    """为市场岗位批量注入 in_library 字段（已导入岗位库？）。

    前端列表/详情据此渲染「✓ 已在岗位库」vs「＋ 加入」状态。
    仅对有 id 的 dict 生效。v8.3 起无归属过滤，全局查询即可。
    """
    if not jobs:
        return
    ids = [j["id"] for j in jobs if isinstance(j, dict) and j.get("id") is not None]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn = await db.get_db()
    try:
        cur = await conn.execute(
            f"SELECT market_job_id FROM positions WHERE market_job_id IN ({placeholders})",
            ids,
        )
        rows = await cur.fetchall()
    finally:
        await conn.close()
    imported = {r["market_job_id"] for r in rows}
    for j in jobs:
        if isinstance(j, dict) and j.get("id") is not None:
            j["in_library"] = j["id"] in imported


@router.post("/api/research-position")
@state.limiter.limit("10/minute")
async def research_position(jd_text: str = Form(""), position: str = Form(""),
                             company: str = Form(""), request: Request = None):
    """搜索并分析岗位信息"""
    try:
        result = await enrich_jd_with_research(
            llm_client=state.llm_client,
            jd_text=jd_text,
            position=position,
            company=company,
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error(f"岗位研究失败: {e}")
        raise HTTPException(500, str(e))


@router.post("/api/market/import")
@state.limiter.limit("5/minute")
async def market_import(
    request: Request,
    db_path: str = Form(""),
    keyword: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    limit: int = Form(5000),
):
    """
    从 job-crawler data.db 导入岗位到 market.db。
    db_path 为空时使用 .env 中的 JOB_CRAWLER_DB_PATH 配置。
    同步执行，完成后返回导入摘要。
    """
    if not db_path.strip():
        # 未指定 → 仅允许使用 .env 中配置的可信源
        crawler_path = config.JOB_CRAWLER_DB_PATH
    else:
        # 指定路径 → 必须位于可信数据目录内且以 .db 结尾，防止任意文件存在性探测（路径遍历）
        allowed_base = os.path.normpath(os.path.dirname(os.path.abspath(config.MARKET_DB_PATH)))
        candidate = os.path.normpath(os.path.abspath(db_path.strip()))
        if candidate != allowed_base and not candidate.startswith(allowed_base + os.sep):
            raise HTTPException(400, "仅允许导入可信数据目录内的数据库文件")
        if not candidate.endswith(".db"):
            raise HTTPException(400, "仅支持导入 .db 文件")
        crawler_path = candidate

    if not crawler_path:
        raise HTTPException(400,
            "请提供 db_path 或在 .env 中配置 JOB_CRAWLER_DB_PATH")

    if not os.path.exists(crawler_path):
        raise HTTPException(400, f"job-crawler 数据库不存在: {crawler_path}")

    result = await market_service.import_and_store(
        crawler_db_path=crawler_path,
        keyword=keyword.strip() if keyword else None,
        city=city.strip() if city else None,
        limit=max(1, min(limit, 10000)),
    )
    # 数据已变化，此前生成的 AI 解读结论全部作废
    market_insight.invalidate()
    return {"status": "ok", **result}


@router.get("/api/market/jobs")
async def market_jobs(
    keyword: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    education: Optional[str] = Query(None),
    salary_min: Optional[float] = Query(None, ge=0),
    salary_max: Optional[float] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """岗位列表查询（关键词/城市/学历/薪资区间过滤 + 分页）"""
    result = await market_store.query_jobs(
        keyword=keyword, city=city, education=education,
        salary_min=salary_min, salary_max=salary_max,
        limit=limit, offset=offset,
    )
    # 注入 in_library：前端据此渲染「✓ 已在岗位库」vs「＋ 加入」
    await _annotate_in_library(result.get("items", []))
    return result


@router.get("/api/market/stats")
async def market_stats(keyword: Optional[str] = Query(None)):
    """市场统计概览：总量/城市/薪资/学历分布、平均薪资、热门技能"""
    return await market_store.get_stats(keyword=keyword)


def _get_city_map():
    """延迟加载城市映射：依赖 playwright 安装，未装时给出明确指引。"""
    try:
        from ..market.crawler.python_job_scraper import get_province_city_map  # noqa: PLC0415
        return get_province_city_map()
    except ModuleNotFoundError as e:
        raise HTTPException(
            500,
            f"实时采集组件未就绪：{e}。请执行 pip install playwright playwright-stealth "
            "并运行 playwright install chromium",
        )


@router.post("/api/market/crawl")
@state.limiter.limit(config.MARKET_CRAWL_RATE_LIMIT)
async def market_crawl(
    request: Request,
    keyword: str = Form(..., min_length=1, max_length=50),
    cities: Optional[List[str]] = Form(None),  # 不传 = 全国范围搜索（底层 scrape_jobs 支持）
    pages: int = Form(3),
    sort_type: str = Form("0"),
    token: Optional[str] = Form(None),
):
    """启动 51job 实时采集（后台任务，立即返回 task_id）。

    单实例互斥：已有 running 任务时返回 409；
    参数不合法返回 400；playwright 未安装返回 500（含安装指引）。
    """
    if config.MARKET_CRAWL_TOKEN and token != config.MARKET_CRAWL_TOKEN:
        raise HTTPException(401, "采集口令不正确")
    cities = [c for c in (cities or []) if c and c.strip()]  # 归一化：不传/空串 → []（全国）
    if len(cities) > config.MARKET_CRAWL_CITY_LIMIT:
        raise HTTPException(400, f"单次最多选择 {config.MARKET_CRAWL_CITY_LIMIT} 个城市")
    if not (1 <= pages <= config.MARKET_CRAWL_PAGE_LIMIT):
        raise HTTPException(400, f"页数需为 1~{config.MARKET_CRAWL_PAGE_LIMIT}")

    err = crawler_tasks.validate(keyword, cities, pages)
    if err:
        raise HTTPException(400, err)
    task, err2 = crawler_tasks.start_crawl(keyword, cities, pages, sort_type)
    if task is None:
        raise HTTPException(409, err2)
    return {"task_id": task.id}


@router.get("/api/market/crawl/status/{task_id}")
async def market_crawl_status(task_id: str):
    """查询采集任务状态（前端 1.5s 轮询；终态任务 TTL 10 分钟后惰性清理）。"""
    task = crawler_tasks.get_status(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在或已过期")
    return task.to_dict()


@router.get("/api/market/city-map")
async def market_city_map():
    """省份→城市级联数据（采集表单用，前端不内嵌 388 城市表）。"""
    return _get_city_map()


@router.get("/api/market/jobs/{job_id}")
async def market_job_detail(job_id: int):
    """岗位详情 + Gap 分析用 JD 文本（title/company/salary/edu/exp/tags/描述）。"""
    job = await market_store.get_job_by_id(job_id)
    if job is None:
        raise HTTPException(404, "岗位不存在")
    await _annotate_in_library([job])
    return {"job": job, "jd_text": build_jd_text(job)}


@router.post("/api/market/jobs/{job_id}/interest")
async def market_toggle_interest(job_id: int):
    """切换岗位「感兴趣」收藏状态（持久化到 market.db）。

    与题库收藏（question_bank.is_favorited）同模式：全局标记、不区分用户，
    因为本项目 market.db 为单机单用户库且支持免登录使用。
    返回新状态；岗位不存在返回 404。
    """
    state_ = await market_store.toggle_interest(job_id)
    if state_ is None:
        raise HTTPException(404, "岗位不存在")
    return {"job_id": job_id, "is_interested": state_}


@router.post("/api/market/jobs/{job_id}/to-position")
async def market_job_to_position(job_id: int):
    """把市场岗位导入岗位库，之后在面试页可直接选用这份 JD。

    为什么是"物化"而不是"引用"：market.db 与面试库物理分离（前者是可再采集的
    公共缓存，后者是用户私有记录，生命周期不同），跨库无法用外键或 JOIN；
    且岗位库要求 JD 文本随时可用，不能依赖"市场库那条记录还在"。
    因此把 JD 文本复制进 positions，仅保留 market_job_id 用于溯源与幂等。

    幂等：同一市场岗位重复导入不会产生第二条，返回 created=False 与既有记录。
    """
    job = await market_store.get_job_by_id(job_id)
    if job is None:
        raise HTTPException(404, "岗位不存在")

    existed = await db.find_position_by_market_job(job_id)
    if existed:
        return {"position": await db.get_position(existed["id"]), "created": False}

    # 原文链接只在岗位库里补：build_jd_text 同时供 Gap 分析喂 LLM，
    # 不宜为其掺入与能力评估无关的 URL。
    jd_text = build_jd_text(job)
    if job.get("url"):
        jd_text = f"{jd_text}\n\n原文链接：{job['url']}"

    position_id = uuid.uuid4().hex[:12]
    await db.save_position(
        position_id,
        title=(job.get("title") or "未命名岗位").strip(),
        jd_text=jd_text,
        department=job.get("company") or None,   # 卡片徽章位展示公司名
        source="market",
        market_job_id=job_id,
    )
    logger.info("市场岗位导入岗位库: job_id=%s -> position_id=%s", job_id, position_id)
    return {"position": await db.get_position(position_id), "created": True}


@router.get("/api/market/charts")
async def market_charts(keyword: Optional[str] = Query(None)):
    """全部分析图表的聚合数据（一次性取回，避免每张卡片各发一次请求）。

    纯 SQL 聚合 + Python 侧分档，毫秒级；空库返回 total=0 与各维度空数组，
    前端据此渲染空态，无需特判异常。
    """
    return await market_analytics.get_charts(keyword=keyword)


@router.post("/api/market/insight")
@state.limiter.limit("20/minute")
async def market_insight_api(
    request: Request,
    section: str = Form("overview"),
    keyword: Optional[str] = Form(None),
    fresh: bool = Form(False),
):
    """对指定图表 section 生成 AI 解读（点击触发，服务端 TTL 缓存 5 分钟）。

    section 取值见 ``backend/market/insight.py`` 的 SECTIONS 注册表。
    失败统一返回 ``{"error": ...}`` 而非抛 500——解读是增强能力，
    失败只应在卡片内降级展示，绝不影响图表本身。
    """
    return await market_insight.analyze(
        section=section.strip(),
        keyword=keyword.strip() if keyword else None,
        fresh=fresh,
    )
