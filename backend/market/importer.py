"""
[v3.0] job-crawler 数据导入适配层。
从 job-crawler 的 data.db 读取已采集岗位，字段映射后标准化输出。
不依赖 Playwright、不需要反爬——数据来源是 job-crawler 已验证的采集管道。

字段映射 (job-crawler jobs → market.db job_postings):
  url            → source_id (去重键)
  category       → keyword
  title/company/city  → 直通
  salary         → salary_raw
  salary_min/max → 直通（单位相同：千元）
  experience(TEXT) → exp_min/exp_max (经由 cleaner.parse_experience)
  education      → 直通（job-crawler 已标准化）
  job_tags(逗号分隔) → tags (list[str])
  description/url → 直通
  crawl_time     → collected_at
"""

import json
import logging
from typing import Optional

import aiosqlite

from .cleaner import parse_experience, extract_skills

logger = logging.getLogger(__name__)


async def import_from_crawler_db(
    crawler_db_path: str,
    keyword: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    """
    从 job-crawler 的 data.db 读取 jobs 表，字段映射后返回标准化记录列表。

    参数:
        crawler_db_path: job-crawler 的 data.db 绝对/相对路径
        keyword: 限定 category 列（None=全量）
        city: 限定 city 列模糊匹配（None=不限）
        limit:  最大导入条数（防止一次性撑爆内存）
    返回:
        标准化后的岗位记录列表，可直接传给 store.upsert_jobs()
    """
    jobs: list[dict] = []
    try:
        db = await aiosqlite.connect(f"file:{crawler_db_path}?mode=ro", uri=True)
        db.row_factory = aiosqlite.Row
    except Exception as e:
        logger.error(f"无法打开 job-crawler 数据库 {crawler_db_path}: {e}")
        return jobs

    try:
        # 检查 jobs 表是否存在
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        ) as cur:
            if not await cur.fetchone():
                logger.error(f"job-crawler 数据库中未找到 jobs 表: {crawler_db_path}")
                return jobs

        where_clauses = ["1=1"]
        params: list = []
        if keyword:
            where_clauses.append("category = ?")
            params.append(keyword)
        if city:
            where_clauses.append("city LIKE ?")
            params.append(f"%{city}%")

        where_sql = " AND ".join(where_clauses)
        query = f"SELECT * FROM jobs WHERE {where_sql} LIMIT ?"
        params.append(limit)

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

        for row in rows:
            row_dict = dict(row)
            exp_raw = str(row_dict.get("experience", "") or "")
            exp_min, exp_max = parse_experience(exp_raw)

            job_tags_raw = str(row_dict.get("job_tags", "") or "")
            tags = (
                [t.strip() for t in job_tags_raw.split(",") if t.strip()]
                if job_tags_raw else []
            )

            description = str(row_dict.get("description", "") or "")[:4000]
            title = str(row_dict.get("title", "") or "")

            job = {
                "source": "51job",
                "source_id": str(row_dict.get("url", "")),
                "keyword": keyword or str(row_dict.get("category", "")),
                "title": title,
                "company": str(row_dict.get("company", "")),
                "city": str(row_dict.get("city", "")),
                "salary_raw": str(row_dict.get("salary", "")),
                "salary_min": row_dict.get("salary_min"),
                "salary_max": row_dict.get("salary_max"),
                "exp_min": exp_min,
                "exp_max": exp_max,
                "education": str(row_dict.get("education", "不限")),
                "tags": tags,
                "description": description,
                "url": str(row_dict.get("url", "")),
                "collected_at": str(row_dict.get("crawl_time", "")),
            }
            jobs.append(job)

        logger.info(f"从 job-crawler 读取 {len(jobs)} 条岗位记录"
                     f"{'（关键词=' + keyword + '）' if keyword else ''}"
                     f"{'（城市=' + city + '）' if city else ''}")
    except Exception as e:
        logger.error(f"导入失败: {e}")
    finally:
        await db.close()

    return jobs
