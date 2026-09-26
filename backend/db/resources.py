"""简历与岗位库的 CRUD。"""

import logging
from typing import Optional

from .connection import get_db

logger = logging.getLogger(__name__)


# ===== v7.0: 简历库 / 岗位库（可复用输入资产）=====
#
# 归属过滤（owner_id）随认证下线一并移除。
# 列表类接口一律不返回大字段（raw_text / jd_text 可能上万字符），详情才返回 ——
# 否则 N 条简历能把响应撑到几 MB。

_RESUME_LIST_COLUMNS = "id, title, filename, char_count, created_at, updated_at"
_POSITION_LIST_COLUMNS = ("id, title, department, "
                          "source, market_job_id, created_at, updated_at")


async def save_resume(resume_id: str, title: str, raw_text: str,
                      filename: str | None = None,
                      parsed_json: str | None = None) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO resumes
               (id, title, filename, raw_text, parsed_json, char_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))""",
            (resume_id, title, filename, raw_text, parsed_json, len(raw_text or "")),
        )
        await db.commit()
    finally:
        await db.close()


async def get_resume(resume_id: str) -> Optional[dict]:
    """详情（含 raw_text）。"""
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def list_resumes(limit: int = 50) -> list[dict]:
    """列表（不含 raw_text）。"""
    db = await get_db()
    try:
        async with db.execute(
            f"SELECT {_RESUME_LIST_COLUMNS} FROM resumes ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def update_resume(resume_id: str, title: str | None = None,
                        parsed_json: str | None = None) -> None:
    """改标题 / 写回解析结果。

    刻意不提供改 raw_text：改内容应重新上传。半截文本比旧文本更难发现问题。
    """
    db = await get_db()
    try:
        if title is not None:
            await db.execute(
                "UPDATE resumes SET title = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (title, resume_id),
            )
        if parsed_json is not None:
            await db.execute(
                "UPDATE resumes SET parsed_json = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (parsed_json, resume_id),
            )
        await db.commit()
    finally:
        await db.close()


async def delete_resume(resume_id: str) -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
        await db.commit()
    finally:
        await db.close()


async def save_position(position_id: str, title: str, jd_text: str,
                        department: str | None = None,
                        source: str = "manual",
                        market_job_id: int | None = None) -> None:
    """保存岗位。source/market_job_id 仅市场导入时需要传入，手工新建走默认值。"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO positions
               (id, title, department, jd_text, source, market_job_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))""",
            (position_id, title, department, jd_text, source, market_job_id),
        )
        await db.commit()
    finally:
        await db.close()


async def find_position_by_market_job(market_job_id: int) -> Optional[dict]:
    """按市场岗位 id 查找已导入的岗位，用于幂等判断（同一市场岗位只导入一次）。

    v8.3: 归属过滤消失后这条查询退化为单条件，不再需要处理
    `owner_id = NULL` 恒不匹配的坑（那是"可空归属列"带来的，不是本查询固有）。
    """
    db = await get_db()
    try:
        async with db.execute(
            "SELECT id, title FROM positions WHERE market_job_id = ?",
            (market_job_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_position(position_id: str) -> Optional[dict]:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM positions WHERE id = ?", (position_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def list_positions(limit: int = 50) -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            f"SELECT {_POSITION_LIST_COLUMNS} FROM positions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def update_position(position_id: str, title: str | None = None,
                          jd_text: str | None = None,
                          department: str | None = None) -> None:
    sets, params = [], []
    for col, val in (("title", title), ("jd_text", jd_text), ("department", department)):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)
    if not sets:
        return
    db = await get_db()
    try:
        sets.append("updated_at = datetime('now', 'localtime')")
        params.append(position_id)
        await db.execute(
            f"UPDATE positions SET {', '.join(sets)} WHERE id = ?", tuple(params)
        )
        await db.commit()
    finally:
        await db.close()


async def delete_position(position_id: str) -> None:
    db = await get_db()
    try:
        await db.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        await db.commit()
    finally:
        await db.close()
