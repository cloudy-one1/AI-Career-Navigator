"""薄弱点画像（每会话每维度一行快照）与风险点查询。"""

import json
import logging

from .connection import get_db

logger = logging.getLogger(__name__)


async def save_weakness_profile(session_id: str, dimension: str,
                                 avg_score: float, weight: float,
                                 risk_points: list[str] = None,
                                 position_id: str | None = None) -> None:
    """保存单次会话的维度薄弱点快照。v8.4: 支持 position_id 岗位隔离。"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO weakness_profile
               (session_id, dimension, avg_score, weight, risk_points, position_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, dimension, avg_score, weight,
             json.dumps(risk_points or [], ensure_ascii=False), position_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_weakness_profile(session_id: str) -> list[dict]:
    """获取指定会话的薄弱点快照"""
    db = await get_db()
    try:
        async with db.execute(
            """SELECT * FROM weakness_profile
               WHERE session_id = ? ORDER BY dimension""",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["risk_points"] = json.loads(d.get("risk_points", "[]"))
                results.append(d)
            return results
    finally:
        await db.close()


async def get_global_weakness_profile(position_id: str | None = None) -> list[dict]:
    """获取薄弱点聚合：各维度历史平均分。v8.4: 支持按岗位过滤。"""
    db = await get_db()
    try:
        sql = """
            SELECT dimension,
                   ROUND(AVG(avg_score), 2) as historical_avg,
                   ROUND(AVG(weight), 2) as avg_weight,
                   COUNT(DISTINCT session_id) as session_count,
                   SUM(CASE WHEN COALESCE(resolved, 0) = 0 THEN 1 ELSE 0 END) as open_count
            FROM weakness_profile
        """
        params: list = []
        if position_id:
            sql += " WHERE position_id = ?"
            params.append(position_id)
        sql += " GROUP BY dimension ORDER BY historical_avg ASC"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        await db.close()


# ===== v6.3: 长期记忆闭环（记忆图谱 / 复习建议 / 面试回注入共用同一查询口径）=====

async def list_weakness_points(include_resolved: bool = False,
                               limit: int | None = None,
                               position_id: str | None = None) -> list[dict]:
    """薄弱点明细列表（长期记忆的数据源）。v8.4: 支持按岗位过滤。

    include_resolved=False（默认）只返回未解决的——这是面试回注入、
    复习建议、图谱主视图的统一口径。

    排序：avg_score 升序（越薄弱越靠前）+ weight 降序（岗位越看重越靠前），
    与"优先复习最要命的短板"这一产品意图一致。
    """
    sql = """
        SELECT id, session_id, dimension, avg_score, weight, risk_points, position_id,
               COALESCE(resolved, 0) as resolved, created_at, updated_at
        FROM weakness_profile
    """
    params: list = []
    # 岗位过滤
    if position_id:
        sql += " WHERE position_id = ?"
        params.append(position_id)
    # 已解决过滤（注意：与岗位过滤是 AND 关系）
    if not include_resolved:
        sql += " WHERE" if not params else " AND"
        sql += " COALESCE(resolved, 0) = 0"
    sql += " ORDER BY avg_score ASC, weight DESC"
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    db = await get_db()
    try:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["risk_points"] = json.loads(d.get("risk_points", "[]"))
                results.append(d)
            return results
    finally:
        await db.close()


async def list_unresolved_weaknesses(limit: int = 10) -> list[dict]:
    """未解决薄弱点 top N（面试初始化回注入用）。

    与 list_weakness_points 同口径，只是默认带 limit——三处调用方
    （回注入 / 建议 / 图谱）共用同一排序语义，避免各写一套 SQL 后漂移。
    """
    return await list_weakness_points(include_resolved=False, limit=limit)


async def mark_weakness_resolved(point_id: int, resolved: bool = True) -> bool:
    """标记薄弱点已解决 / 恢复未解决。返回是否命中行。"""
    db = await get_db()
    try:
        cur = await db.execute(
            """UPDATE weakness_profile
               SET resolved = ?, updated_at = datetime('now', 'localtime')
               WHERE id = ?""",
            (1 if resolved else 0, point_id),
        )
        await db.commit()
        return (cur.rowcount or 0) > 0
    finally:
        await db.close()


async def delete_weakness(point_id: int) -> bool:
    """删除单条薄弱点记录。返回是否命中行。"""
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM weakness_profile WHERE id = ?", (point_id,)
        )
        await db.commit()
        return (cur.rowcount or 0) > 0
    finally:
        await db.close()


async def get_latest_risk_points(dimensions: list[str]) -> dict[str, list[str]]:
    """批量取各维度最近一次快照中的风险点（供回注入 prompt 引用）。

    取"最近一次"而非聚合，因为风险点是最新的才最有指向性。
    """
    result: dict[str, list[str]] = {}
    dims = [d for d in (dimensions or []) if d]
    if not dims:
        return result
    placeholders = ",".join("?" * len(dims))
    db = await get_db()
    try:
        async with db.execute(
            f"""SELECT dimension, risk_points FROM weakness_profile
                WHERE id IN (
                    SELECT MAX(id) FROM weakness_profile
                    WHERE dimension IN ({placeholders})
                    GROUP BY dimension
                )""",
            dims,
        ) as cur:
            for row in await cur.fetchall():
                d = row[0]
                try:
                    result[d] = json.loads(row[1] or "[]")
                except (json.JSONDecodeError, TypeError):
                    result[d] = []
    finally:
        await db.close()
    return result
