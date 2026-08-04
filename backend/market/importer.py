"""
[v3.0] job-crawler 数据导入适配层。
从 job-crawler 的 data.db 读取已采集岗位，字段映射后标准化输出。
不依赖 Playwright、不需要反爬——数据来源是 job-crawler 已验证的采集管道。

[v3.1 适配] 新增 project1-enhanced data 表支持（列名不同）：
  标准 jobs 表: url/category/title/company/city/salary/salary_min/salary_max/
                experience/education/job_tags/description/crawl_time
  data 表:      job_url(无category)/post/company/address/salary_min/salary_max/
                exper/edu/keywords/content/dateT
"""

import json
import logging
import re
from typing import Optional

import aiosqlite

from .cleaner import parse_experience

logger = logging.getLogger(__name__)


async def import_from_crawler_db(
    crawler_db_path: str,
    keyword: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    """
    从 job-crawler 的 data.db 读取 jobs/data 表，字段映射后返回标准化记录列表。

    参数:
        crawler_db_path: job-crawler 的 data.db 绝对/相对路径
        keyword: 用于过滤（jobs表=category匹配, data表=post模糊匹配）
        city: 限定城市列模糊匹配（None=不限）
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
        # ── 检测表类型：优先 jobs 表（标准 schema），回退 data 表 ──
        table_name: str | None = None
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('jobs', 'data')"
        ) as cur:
            rows = await cur.fetchall()
            for r in rows:
                name = r[0] if isinstance(r, tuple) else r["name"]
                if name in ("jobs", "data"):
                    table_name = name
                    break

        if not table_name:
            logger.error(f"job-crawler 数据库中未找到 jobs/data 表: {crawler_db_path}")
            return jobs

        # ── 查询字段列名 ──
        col_names: list[str] = []
        async with db.execute(f"PRAGMA table_info('{table_name}')") as cur:
            col_info = await cur.fetchall()
            col_names = [r[1] if isinstance(r, tuple) else r["name"] for r in col_info]

        # ── 构建 WHERE + 限制 ──
        where_clauses = ["1=1"]
        params: list = []
        keyword_filter = keyword  # 保留原始 keyword 用于后续填充

        if keyword_filter:
            if table_name == "jobs":
                where_clauses.append("category = ?")
                params.append(keyword_filter)
            else:
                # data 表无 category 列，用 post 列模糊匹配
                where_clauses.append("post LIKE ?")
                params.append(f"%{keyword_filter}%")

        if city:
            city_col = "city" if "city" in col_names else "address"
            where_clauses.append(f"[{city_col}] LIKE ?")
            params.append(f"%{city}%")

        where_sql = " AND ".join(where_clauses)
        query = f"SELECT * FROM [{table_name}] WHERE {where_sql} LIMIT ?"
        params.append(limit)

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

        # ── 逐行映射 ──
        for row in rows:
            row_dict = dict(row)

            if table_name == "data":
                job = _map_data_row(row_dict, keyword_filter)
            else:
                job = _map_jobs_row(row_dict, keyword_filter)

            jobs.append(job)

        logger.info(
            f"从 job-crawler 读取 {len(jobs)} 条岗位记录（表={table_name}）"
            f"{'（关键词=' + keyword_filter + '）' if keyword_filter else ''}"
            f"{'（城市=' + city + '）' if city else ''}"
        )
    except Exception as e:
        logger.error(f"导入失败: {e}")
    finally:
        await db.close()

    return jobs


def _map_data_row(row_dict: dict, keyword_filter: str | None) -> dict:
    """project1-enhanced data 表 → 标准 job dict"""
    title = str(row_dict.get("post", "") or "")
    exp_raw = str(row_dict.get("exper", "") or "")
    exp_min, exp_max = parse_experience(exp_raw)

    job_tags_raw = str(row_dict.get("keywords", "") or "")
    tags = (
        [t.strip() for t in job_tags_raw.split(",") if t.strip()]
        if job_tags_raw else []
    )

    description = str(row_dict.get("content", "") or "")[:4000]
    job_url = str(row_dict.get("job_url", "") or "")

    salary_min_val = row_dict.get("salary_min")
    salary_max_val = row_dict.get("salary_max")
    salary_raw = f"{salary_min_val or '?'}-{salary_max_val or '?'}K/月"

    # keyword：传入参数优先，否则从 title 推断
    final_keyword = keyword_filter or _infer_keyword_from_title(title)

    return {
        "source": "51job",
        "source_id": job_url,
        "keyword": final_keyword or title,
        "title": title,
        "company": str(row_dict.get("company", "")),
        "city": str(row_dict.get("address", "")),
        "salary_raw": salary_raw,
        "salary_min": salary_min_val,
        "salary_max": salary_max_val,
        "exp_min": exp_min,
        "exp_max": exp_max,
        "education": str(row_dict.get("edu", "不限")),
        "tags": tags,
        "description": description,
        "url": job_url,
        "collected_at": str(row_dict.get("dateT", "")),
    }


def _map_jobs_row(row_dict: dict, keyword_filter: str | None) -> dict:
    """标准 jobs 表 → 标准 job dict"""
    title = str(row_dict.get("title", "") or "")
    exp_raw = str(row_dict.get("experience", "") or "")
    exp_min, exp_max = parse_experience(exp_raw)

    job_tags_raw = str(row_dict.get("job_tags", "") or "")
    tags = (
        [t.strip() for t in job_tags_raw.split(",") if t.strip()]
        if job_tags_raw else []
    )

    description = str(row_dict.get("description", "") or "")[:4000]

    return {
        "source": "51job",
        "source_id": str(row_dict.get("url", "")),
        "keyword": keyword_filter or str(row_dict.get("category", "")),
        "title": title,
        "company": str(row_dict.get("company", "")),
        "city": str(row_dict.get("city", "")),
        "salary_raw": str(row_dict.get("salary", "") or ""),
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


def _infer_keyword_from_title(title: str) -> str:
    """从岗位标题（如 'python开发工程师'）提取简化的关键词"""
    if not title:
        return ""
    # 去掉常见后缀
    for suffix in ["开发工程师", "高级工程师", "工程师", "实习生", "岗"]:
        idx = title.find(suffix)
        if idx > 0:
            title = title[:idx]
    # 去掉括号及内容
    title = re.sub(r"[（(].*?[)）]", "", title)
    title = title.strip()
    return title
