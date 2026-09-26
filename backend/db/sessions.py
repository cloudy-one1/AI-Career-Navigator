"""面试会话、问答记录、报告与旅程标记的读写。"""

import json
import logging
from typing import Optional

from .connection import get_db

logger = logging.getLogger(__name__)


async def save_session(session_id: str, style: str = "friendly",
                        resume_filename: str = "", jd_text: str = "",
                        resume_text: str = "",
                        resume_id: str | None = None,
                        position_id: str | None = None) -> None:
    """新建 / 覆盖会话。v8.3: 已无 owner_id 参数（认证下线）。"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO sessions
               (id, style, resume_filename, jd_text, resume_text, resume_id, position_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, style, resume_filename, jd_text, resume_text,
             resume_id, position_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_session_flow(session_id: str, flow_state: str,
                               answered_count: int | None = None) -> None:
    """v7.0 D4：落库流程位置与已答题数（只落进度，不做断点续答）。"""
    db = await get_db()
    try:
        if answered_count is None:
            await db.execute(
                """UPDATE sessions SET flow_state = ?,
                   flow_updated_at = datetime('now', 'localtime') WHERE id = ?""",
                (flow_state, session_id),
            )
        else:
            await db.execute(
                """UPDATE sessions SET flow_state = ?, answered_count = ?,
                   flow_updated_at = datetime('now', 'localtime') WHERE id = ?""",
                (flow_state, answered_count, session_id),
            )
        await db.commit()
    finally:
        await db.close()


async def update_session_status(session_id: str, status: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE sessions SET status = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
            (status, session_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_session(session_id: str) -> Optional[dict]:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def list_sessions(limit: int = 50) -> list[dict]:
    """最近 N 个会话，按更新时间倒序。

    v8.3: owner_id 过滤参数随认证下线——单用户下"按归属过滤"等价于"不过滤"。
    """
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


# ===== QA Records =====

async def save_qa(session_id: str, round_index: int, question: str,
                  answer: str, diagnosis: dict) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO interview_qa (session_id, round_index, question, answer, diagnosis_json) VALUES (?, ?, ?, ?, ?)",
            (session_id, round_index, question, answer, json.dumps(diagnosis, ensure_ascii=False)),
        )
        await db.execute(
            "UPDATE sessions SET updated_at = datetime('now', 'localtime') WHERE id = ?",
            (session_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_session_qas(session_id: str) -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM interview_qa WHERE session_id = ? ORDER BY id", (session_id,)
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()


# ===== Reports =====

async def save_report(session_id: str, report: dict) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO reports (session_id, report_json) VALUES (?, ?)",
            (session_id, json.dumps(report, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_report(session_id: str) -> Optional[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM reports WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def mark_journey_step(step_key: str) -> None:
    """打点一个旅程关键动作（幂等：同一步重复写入只更新，不报错）。

    v8.3: owner_id 参数随认证下线——单用户下它只会带来"匿名要不要落库"的
    伪问题（此前未登录一律不落库，导致第⑤步在匿名模式下永远打不上）。
    """
    if not step_key:
        return
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO journey_marks (step_key) VALUES (?) "
            "ON CONFLICT(step_key) DO UPDATE SET marked_at = datetime('now', 'localtime')",
            (step_key,),
        )
        await db.commit()
    finally:
        await db.close()


async def list_journey_marks() -> dict:
    """读取已打点的旅程步骤 → {step_key: marked_at}。"""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT step_key, marked_at FROM journey_marks"
        ) as cur:
            return {row[0]: row[1] for row in await cur.fetchall()}
    finally:
        await db.close()


async def list_recent_reports(limit: int = 10) -> list[dict]:
    """最近 N 份报告（含时间与 JSON），按时间倒序。

    为什么必须一次 JOIN 取回：能力成长曲线要的是"每场一份"的历史序列，
    若沿用 get_report 逐份查询，N 场就是 N 次 IO（N+1 问题）。

    v8.3: `reports` 表本就没有 owner 列，归属此前靠 JOIN `sessions` 判定，
    认证下线后过滤条件消失；JOIN 本身保留，确保只取"会话仍在"的报告——
    让成长曲线不会画出无主的场次。
    """
    db = await get_db()
    try:
        async with db.execute(
            """SELECT r.session_id, r.report_json, r.created_at
               FROM reports r
               JOIN sessions s ON s.id = r.session_id
               ORDER BY r.created_at DESC LIMIT ?""",
            (limit,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
    finally:
        await db.close()
