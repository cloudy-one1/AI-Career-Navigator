"""长期薄弱点记忆（EMA 衰减 + 过期淘汰）的 CRUD。
与 weakness.py 分工：weakness_profile 是历史流水，weakness_memory 是当前状态。
纯计算在 L2 的 backend/weakness_memory.py，这里只做 CRUD（L1 不得反向依赖 L2）。"""

import logging

from .connection import get_db

logger = logging.getLogger(__name__)


# ===== v6.5: 长期薄弱点记忆（EMA 衰减 + 过期淘汰）=====
# 与 weakness_profile（每会话每维度一行快照，历史）分工：
#   weakness_profile = 历史流水（图谱/建议/回注入的素材）
#   weakness_memory  = 当前状态（每维度一行，带薄弱度/计数/过期时间）
# 纯计算在 L2 的 weakness_memory.py，这里只做 CRUD（L1 不得反向依赖 L2）。

def _normalize_position_id(position_id: str | None) -> str:
    """v8.4: SQLite 的 UNIQUE 约束中 NULL != NULL，故用空字符串作为'全局'哨兵值。

    这样 (dimension, '') 能正确匹配 ON CONFLICT，实现同一维度全局数据的 upsert 语义。
    """
    return position_id if position_id is not None else ''


async def get_weakness_memory(dimension: str,
                             position_id: str | None = None) -> dict | None:
    """读取单个维度的长期薄弱点状态（不存在返回 None）。v8.4: 支持按岗位隔离。"""
    db = await get_db()
    pid = _normalize_position_id(position_id)
    try:
        async with db.execute(
            """SELECT dimension, position_id, weakness_score, occurrence_count, last_score,
                      last_seen, expires_at, updated_at
               FROM weakness_memory WHERE dimension = ? AND position_id = ?""",
            (dimension, pid),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def upsert_weakness_memory(dimension: str, state: dict,
                                 position_id: str | None = None) -> None:
    """写入/更新单个维度的长期薄弱点状态（由 L2 算好状态后传入）。v8.4: 支持岗位隔离。"""
    db = await get_db()
    pid = _normalize_position_id(position_id)
    try:
        await db.execute(
            """INSERT INTO weakness_memory
               (dimension, position_id, weakness_score, occurrence_count, last_score,
                last_seen, expires_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(dimension, position_id) DO UPDATE SET
                   weakness_score=excluded.weakness_score,
                   occurrence_count=excluded.occurrence_count,
                   last_score=excluded.last_score,
                   last_seen=excluded.last_seen,
                   expires_at=excluded.expires_at,
                   updated_at=excluded.updated_at""",
            (
                dimension,
                pid,
                float(state.get("weakness_score") or 0.0),
                int(state.get("occurrence_count") or 0),
                float(state.get("last_score") or 0.0),
                state.get("last_seen"),
                state.get("expires_at"),
                state.get("updated_at"),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_weakness_memory(dimension: str,
                               position_id: str | None = None) -> None:
    """删除单个维度的长期薄弱点状态（计数归零 / 已解决时调用）。v8.4: 支持岗位隔离。"""
    db = await get_db()
    pid = _normalize_position_id(position_id)
    try:
        await db.execute(
            "DELETE FROM weakness_memory WHERE dimension = ? AND position_id = ?",
            (dimension, pid),
        )
        await db.commit()
    finally:
        await db.close()


async def list_active_weakness_memory(limit: int = 10,
                                     position_id: str | None = None) -> list[dict]:
    """未过期的长期薄弱点，按薄弱度降序（最要命的排最前）。v8.4: 支持按岗位过滤。

    过期判定与写入端一致用 localtime（数据库里存的是 localtime 文本）。
    """
    sql = """
        SELECT dimension, position_id, weakness_score, occurrence_count, last_score,
               last_seen, expires_at, updated_at
        FROM weakness_memory
        WHERE weakness_score > 0
          AND (expires_at IS NULL OR expires_at > datetime('now', 'localtime'))
    """
    params: list = []
    if position_id:
        pid = _normalize_position_id(position_id)
        sql += " AND position_id = ?"
        params.append(pid)
    sql += " ORDER BY weakness_score DESC, occurrence_count DESC"
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    db = await get_db()
    try:
        async with db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def prune_expired_weakness_memory() -> int:
    """清理已过期的长期薄弱点，返回删除行数。"""
    db = await get_db()
    try:
        cur = await db.execute(
            """DELETE FROM weakness_memory
               WHERE expires_at IS NOT NULL
                 AND expires_at <= datetime('now', 'localtime')"""
        )
        await db.commit()
        return cur.rowcount or 0
    finally:
        await db.close()
