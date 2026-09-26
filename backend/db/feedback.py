"""逐题诊断反馈的存取与统计。"""

import logging

from .connection import get_db

logger = logging.getLogger(__name__)


# ===== v2.5: Diagnosis Feedback =====

async def save_feedback(session_id: str, round_idx: int, question_idx: int,
                        feedback_type: str, dimension: str = "",
                        comment: str = "", current_score: float = 0) -> int:
    """保存诊断反馈，返回反馈ID"""
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO diagnosis_feedback
               (session_id, round_idx, question_idx, dimension,
                feedback_type, comment, current_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, round_idx, question_idx, dimension,
             feedback_type, comment, current_score),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def get_session_feedback(session_id: str) -> list[dict]:
    """获取会话的所有反馈记录"""
    db = await get_db()
    try:
        async with db.execute(
            """SELECT * FROM diagnosis_feedback
               WHERE session_id = ?
               ORDER BY created_at DESC""",
            (session_id,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


async def get_feedback_stats(session_id: str) -> dict:
    """获取反馈统计"""
    db = await get_db()
    try:
        async with db.execute(
            """SELECT feedback_type, COUNT(*) as cnt
               FROM diagnosis_feedback
               WHERE session_id = ?
               GROUP BY feedback_type""",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
            stats = {"up": 0, "down": 0, "total": 0}
            for r in rows:
                stats[r[0]] = r[1]
                stats["total"] += r[1]
            return stats
    finally:
        await db.close()
