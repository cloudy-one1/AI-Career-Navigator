"""
[v3.0] 市场数据服务层：从 job-crawler 导入 + 岗位画像集成。
导入管道：job-crawler data.db → importer (字段映射) → store (upsert 到 market.db)。
"""

import logging
from typing import Optional

from . import importer, store

logger = logging.getLogger(__name__)


async def import_and_store(
    crawler_db_path: str,
    keyword: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 5000,
) -> dict:
    """
    从 job-crawler data.db 导入岗位到 market.db。
    返回: {imported, total_read, keyword, city}
    """
    await store.init_market_db()

    jobs = await importer.import_from_crawler_db(
        crawler_db_path=crawler_db_path,
        keyword=keyword,
        city=city,
        limit=limit,
    )

    saved = await store.upsert_jobs(jobs) if jobs else 0
    logger.info(f"导入完成: 读取 {len(jobs)} 条, 写入 {saved} 条")
    return {
        "imported": saved,
        "total_read": len(jobs),
        "keyword": keyword,
        "city": city,
    }


async def find_relevant_snapshot(text: str) -> Optional[dict]:
    """
    岗位画像集成点：JD 文本命中已导入关键词时，返回该关键词的市场统计快照。
    用于创建面试会话时把定量市场数据（薪资区间/技能分布）注入定性研究。
    """
    if not text:
        return None
    try:
        keywords = await store.list_keywords()
    except Exception:
        return None
    for kw in keywords:
        if kw and kw in text:
            return await store.get_stats(keyword=kw)
    return None
