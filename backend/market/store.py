"""
[v3.0] 市场岗位存储：独立 data/market.db。
与面试库（interview.db）物理分离——市场数据是可再采集的公共缓存，
面试数据是用户私有记录，两类数据生命周期不同，互不拖累。
"""

import json
import logging
import os
from collections import Counter
from typing import Optional

import aiosqlite

from ..config import config

logger = logging.getLogger(__name__)


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(config.MARKET_DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(config.MARKET_DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_market_db() -> None:
    """初始化 job_postings 表（幂等）"""
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS job_postings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT '51job',
                source_id TEXT NOT NULL,
                keyword TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT DEFAULT '',
                city TEXT DEFAULT '',
                salary_raw TEXT DEFAULT '',
                salary_min REAL,
                salary_max REAL,
                exp_min REAL,
                exp_max REAL,
                education TEXT DEFAULT '不限',
                tags TEXT DEFAULT '[]',
                description TEXT DEFAULT '',
                url TEXT DEFAULT '',
                collected_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(source, source_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_keyword ON job_postings(keyword)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_city ON job_postings(city)")
        await db.commit()
        logger.info("市场数据库初始化完成 (market.db)")
    finally:
        await db.close()


async def upsert_jobs(jobs: list[dict]) -> int:
    """批量写入（按 (source, source_id) 去重，存在则更新），返回写入条数"""
    if not jobs:
        return 0
    rows = [{**j, "tags": json.dumps(j.get("tags", []), ensure_ascii=False)} for j in jobs]
    db = await get_db()
    try:
        await db.executemany("""
            INSERT INTO job_postings
                (source, source_id, keyword, title, company, city,
                 salary_raw, salary_min, salary_max, exp_min, exp_max,
                 education, tags, description, url)
            VALUES
                (:source, :source_id, :keyword, :title, :company, :city,
                 :salary_raw, :salary_min, :salary_max, :exp_min, :exp_max,
                 :education, :tags, :description, :url)
            ON CONFLICT(source, source_id) DO UPDATE SET
                keyword=excluded.keyword, title=excluded.title, company=excluded.company,
                city=excluded.city, salary_raw=excluded.salary_raw,
                salary_min=excluded.salary_min, salary_max=excluded.salary_max,
                exp_min=excluded.exp_min, exp_max=excluded.exp_max,
                education=excluded.education, tags=excluded.tags,
                description=excluded.description, url=excluded.url,
                updated_at=datetime('now', 'localtime')
        """, rows)
        await db.commit()
        return len(rows)
    finally:
        await db.close()


async def query_jobs(keyword: Optional[str] = None, city: Optional[str] = None,
                     education: Optional[str] = None,
                     salary_min: Optional[float] = None, salary_max: Optional[float] = None,
                     limit: int = 50, offset: int = 0) -> dict:
    """岗位查询（多条件过滤 + 分页）。空库返回 total=0 空列表，不报错。"""
    where, params = ["1=1"], []
    if keyword:
        where.append("(keyword LIKE ? OR title LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if city:
        where.append("city LIKE ?")
        params.append(f"%{city}%")
    if education:
        where.append("education = ?")
        params.append(education)
    if salary_min is not None:
        where.append("salary_max >= ?")   # 岗位能给到的上限 ≥ 期望下限
        params.append(salary_min)
    if salary_max is not None:
        where.append("salary_min <= ?")   # 岗位起薪 ≤ 期望上限
        params.append(salary_max)

    where_sql = " AND ".join(where)
    db = await get_db()
    try:
        async with db.execute(
            f"SELECT COUNT(*) FROM job_postings WHERE {where_sql}", params
        ) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            f"""SELECT * FROM job_postings WHERE {where_sql}
                ORDER BY collected_at DESC LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ) as cur:
            items = []
            for row in await cur.fetchall():
                d = dict(row)
                d["tags"] = json.loads(d.get("tags") or "[]")
                items.append(d)
        return {"total": total, "items": items, "limit": limit, "offset": offset}
    finally:
        await db.close()


async def get_job_by_id(job_id: int) -> Optional[dict]:
    """按主键查询单条岗位；不存在返回 None（tags 反序列化为 list）"""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM job_postings WHERE id = ?", (job_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        return d
    finally:
        await db.close()


async def list_keywords() -> list[str]:
    """所有已采集过的搜索关键词（用于 JD 文本反向命中）"""
    db = await get_db()
    try:
        async with db.execute("SELECT DISTINCT keyword FROM job_postings") as cur:
            return [r[0] for r in await cur.fetchall()]
    finally:
        await db.close()


async def _keyword_counts(db) -> list[dict]:
    async with db.execute(
        "SELECT keyword, COUNT(*) AS cnt FROM job_postings GROUP BY keyword ORDER BY cnt DESC LIMIT 20"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def get_stats(keyword: Optional[str] = None) -> dict:
    """
    市场统计概览：总量、城市分布、薪资分布、学历分布、平均薪资、热门技能。
    空库返回 total=0 的友好空态。
    """
    db = await get_db()
    try:
        if keyword:
            where, params = "WHERE keyword = ?", [keyword]
        else:
            where, params = "", []

        async with db.execute(f"SELECT COUNT(*) FROM job_postings {where}", params) as cur:
            total = (await cur.fetchone())[0]

        if total == 0:
            return {"total": 0, "keyword": keyword, "cities": [],
                    "salary_distribution": [], "education_distribution": [],
                    "avg_salary": None, "top_skills": [],
                    "keywords": await _keyword_counts(db)}

        async with db.execute(
            f"""SELECT city, COUNT(*) AS cnt FROM job_postings {where}
                GROUP BY city ORDER BY cnt DESC LIMIT 10""", params) as cur:
            cities = [dict(r) for r in await cur.fetchall()]

        salary_where = (where + " AND" if keyword else "WHERE") + \
                       " salary_min IS NOT NULL AND salary_max IS NOT NULL"
        async with db.execute(f"""
            SELECT CASE
                     WHEN (salary_min + salary_max) / 2 < 10 THEN '<10K'
                     WHEN (salary_min + salary_max) / 2 < 20 THEN '10-20K'
                     WHEN (salary_min + salary_max) / 2 < 30 THEN '20-30K'
                     WHEN (salary_min + salary_max) / 2 < 50 THEN '30-50K'
                     ELSE '>=50K' END AS bucket,
                   COUNT(*) AS cnt
            FROM job_postings {salary_where}
            GROUP BY bucket
        """, params) as cur:
            salary_dist = [dict(r) for r in await cur.fetchall()]

        async with db.execute(
            f"""SELECT ROUND(AVG((salary_min + salary_max) / 2), 1) AS avg_k,
                       ROUND(MIN(salary_min), 1) AS min_k,
                       ROUND(MAX(salary_max), 1) AS max_k
                FROM job_postings {salary_where}""", params) as cur:
            row = dict(await cur.fetchone())
            avg_salary = row if row and row.get("avg_k") is not None else None

        async with db.execute(
            f"""SELECT education, COUNT(*) AS cnt FROM job_postings {where}
                GROUP BY education ORDER BY cnt DESC""", params) as cur:
            edu_dist = [dict(r) for r in await cur.fetchall()]

        # 技能 Top20：tags 为 JSON 文本，Python 侧聚合
        async with db.execute(f"SELECT tags FROM job_postings {where} LIMIT 3000", params) as cur:
            counter: Counter = Counter()
            for (tags_json,) in await cur.fetchall():
                try:
                    for t in json.loads(tags_json or "[]"):
                        counter[t] += 1
                except Exception:
                    continue
        top_skills = [{"skill": k, "count": c} for k, c in counter.most_common(20)]

        return {
            "total": total,
            "keyword": keyword,
            "cities": cities,
            "salary_distribution": salary_dist,
            "education_distribution": edu_dist,
            "avg_salary": avg_salary,
            "top_skills": top_skills,
            "keywords": await _keyword_counts(db),
        }
    finally:
        await db.close()
