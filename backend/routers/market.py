"""市场域：岗位画像研究 + 市场数据导入/检索/统计 + 实时采集（job-crawler B 档内嵌）。"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request

from ..config import config
from ..market import store as market_store, service as market_service
from ..market.crawler import tasks as crawler_tasks
from ..market.crawler.adapters import build_jd_text
from ..web_research import enrich_jd_with_research
from . import state

logger = logging.getLogger(__name__)
router = APIRouter()


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
    return await market_store.query_jobs(
        keyword=keyword, city=city, education=education,
        salary_min=salary_min, salary_max=salary_max,
        limit=limit, offset=offset,
    )


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
