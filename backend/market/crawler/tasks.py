"""
[AI 求职领航] 采集后台任务管理器。

设计要点:
- ``scrape_jobs`` 是同步阻塞的 Playwright 逻辑，全部在后台线程中执行，
  HTTP 请求立即返回 task_id，不阻塞 FastAPI 事件循环。
- 任务状态存内存 dict（threading.Lock 保护），前端轮询
  ``GET /api/market/crawl/status/{task_id}`` 获取进度。
- 单实例互斥：同一时刻只允许一个 running 任务（避免并发访问 51job 被封）。
- 终态任务（done/failed）保留 TTL=10 分钟，轮询时惰性清理，防止内存膨胀。
- 采集完成自动回灌 market.db（store.upsert_jobs，按 (source, source_id) 去重）。
"""
import asyncio
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from . import adapters
from .. import store

logger = logging.getLogger("market.crawler.tasks")

_TASK_TTL = 600.0  # 终态任务保留秒数
_CITY_LIMIT = 5    # 单次采集城市上限（与 job-crawler 一致）
_PAGES_RANGE = (1, 5)


@dataclass
class CrawlTask:
    """采集任务状态模型（前端轮询契约）。"""
    id: str
    keyword: str
    cities: list
    pages: int
    sort_type: str
    status: str = "running"                      # running | done | failed
    message: str = "排队中..."
    collected: int = 0                            # 累计采集条数
    pages_collected: dict = field(default_factory=dict)  # {city: 实际翻取页数}
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


_tasks: dict[str, CrawlTask] = {}
_lock = threading.Lock()


def validate(keyword: str, cities: list, pages: int) -> Optional[str]:
    """参数校验，返回错误信息；合法返回 None。"""
    if not keyword or not keyword.strip():
        return "关键词不能为空"
    # 空列表合法：走全国范围搜索（scrape_jobs 内部 fallback 到 ("全国","000000")）
    cities = cities or []
    if len(cities) > _CITY_LIMIT:
        return f"最多选择 {_CITY_LIMIT} 个城市"
    if not isinstance(pages, int) or not (_PAGES_RANGE[0] <= pages <= _PAGES_RANGE[1]):
        return f"页数需为 {_PAGES_RANGE[0]}~{_PAGES_RANGE[1]} 的整数"
    return None


def start_crawl(keyword: str, cities: list, pages: int, sort_type: str = "0") -> tuple:
    """
    注册并启动采集任务。

    返回: (task, error)
        - 校验失败 / 已有任务运行时, task=None, error=原因
        - 成功时 task 为 CrawlTask 实例, error 为空字符串
    """
    error = validate(keyword, cities, pages)
    if error:
        return None, error

    with _lock:
        for existing in _tasks.values():
            if existing.status == "running":
                return None, "已有采集任务进行中，请等待完成后再试"

        task = CrawlTask(
            id=uuid.uuid4().hex[:12],
            keyword=keyword.strip(),
            cities=list(cities),
            pages=pages,
            sort_type=sort_type,
        )
        _tasks[task.id] = task

    logger.info(
        "采集任务启动 id=%s keyword=%s cities=%s pages=%s sort_type=%s",
        task.id, task.keyword, task.cities, task.pages, task.sort_type,
    )
    thread = threading.Thread(target=_run_crawl, args=(task.id,), daemon=True)
    thread.start()
    return task, ""


def get_status(task_id: str) -> Optional[CrawlTask]:
    """轮询任务状态；终态任务超过 TTL 后惰性清理并返回 None。"""
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        if task.status != "running" and time.time() - task.created_at > _TASK_TTL:
            _tasks.pop(task_id, None)
            return None
        return task


def _update(task_id: str, **changes) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        for key, value in changes.items():
            setattr(task, key, value)


def _on_progress(task_id: str, city: str, page: int, added: int) -> None:
    """采集进度回调（采集线程内被调用），线程安全更新任务状态。"""
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        task.collected += added
        task.pages_collected[city] = page
        task.message = f"[{city}] 第{page}页 +{added}条（累计 {task.collected}）"


def _run_crawl(task_id: str) -> None:
    """采集线程入口：scrape_jobs → adapters → store.upsert_jobs 回灌 market.db。"""
    task = _tasks.get(task_id)
    if task is None:
        return
    try:
        # 延迟导入：playwright 未安装时，应用本身与状态轮询仍可用，
        # 只有真正启动采集时才在任务内转为 failed 并给出安装指引
        from .python_job_scraper import scrape_jobs  # noqa: PLC0415

        _update(task_id, status="running", message="正在启动浏览器…")
        jobs, pages_collected = scrape_jobs(
            keyword=task.keyword,
            cities=task.cities,
            pages_per_city=task.pages,
            sort_type=task.sort_type,
            progress_callback=lambda c, p, n: _on_progress(task_id, c, p, n),
        )
        _update(task_id, message="采集完成，正在写入市场数据库…")

        standard = [
            adapters.to_standard_job(j, task.keyword, j.get("address", ""), j.get("job_url", ""))
            for j in jobs
        ]
        inserted = asyncio.run(store.upsert_jobs(standard))

        # 数据已变化，此前的 AI 解读结论全部作废。
        # 延迟导入：不把 llm_client 拉进采集链路，保证无 Key 环境仍能正常采集。
        if inserted:
            from .. import insight  # noqa: PLC0415
            insight.invalidate()

        _update(
            task_id,
            status="done",
            message=f"完成：共采集 {len(jobs)} 条，入库 {inserted} 条",
            pages_collected=pages_collected,
        )
        logger.info(
            "采集任务完成 id=%s keyword=%s 采集=%d 入库=%d",
            task_id, task.keyword, len(jobs), inserted,
        )
    except Exception as e:  # noqa: BLE001 - 采集链路任何异常都转为 failed 状态
        error_msg = f"{type(e).__name__}: {e}"
        _update(task_id, status="failed", error=error_msg, message="采集失败")
        logger.exception("采集任务失败 id=%s keyword=%s", task_id, task.keyword)
