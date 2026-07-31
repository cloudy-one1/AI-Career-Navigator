"""
数据库 v2.5：SQLite 多表操作 (aiosqlite)
v2.2: 新增 question_bank 表
v2.5: 新增 diagnosis_feedback 表
"""

import aiosqlite
import json
import os
from datetime import datetime
from typing import Optional
import logging

from .config import config

logger = logging.getLogger(__name__)

# 确保 data 目录存在
os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)


async def get_db():
    db = await aiosqlite.connect(config.DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """初始化所有表"""
    db = await get_db()
    try:
        # 会话元信息
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                style TEXT DEFAULT 'friendly',
                resume_filename TEXT DEFAULT '',
                jd_text TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # 面试问答记录
        await db.execute("""
            CREATE TABLE IF NOT EXISTS interview_qa (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round_index INTEGER NOT NULL DEFAULT 0,
                question TEXT NOT NULL,
                answer TEXT DEFAULT '',
                diagnosis_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # 综合报告
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                report_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # v2.2: 题库管理
        await db.execute("""
            CREATE TABLE IF NOT EXISTS question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_type TEXT NOT NULL DEFAULT '',
                question_text TEXT NOT NULL,
                intent TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                difficulty INTEGER DEFAULT 3,
                source TEXT DEFAULT 'manual',
                is_favorited INTEGER DEFAULT 0,
                usage_count INTEGER DEFAULT 0,
                session_id TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # v2.5: 诊断反馈表
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round_idx INTEGER NOT NULL,
                question_idx INTEGER NOT NULL,
                dimension TEXT DEFAULT '',
                feedback_type TEXT NOT NULL,
                comment TEXT DEFAULT '',
                current_score REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        await cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_session ON diagnosis_feedback(session_id)"
        )

        await db.commit()
        logger.info("数据库初始化完成（含 question_bank、diagnosis_feedback 表）")
    finally:
        await db.close()


# ===== Sessions =====

async def save_session(session_id: str, style: str = "friendly",
                        resume_filename: str = "", jd_text: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO sessions (id, style, resume_filename, jd_text) VALUES (?, ?, ?, ?)",
            (session_id, style, resume_filename, jd_text),
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


# ===== v2.2 Question Bank =====

async def add_question(question_text: str, round_type: str = "",
                       intent: str = "", tags: list[str] = None,
                       difficulty: int = 3, source: str = "manual",
                       session_id: str = "") -> int:
    """添加题库题目，返回 id"""
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO question_bank
               (round_type, question_text, intent, tags, difficulty, source, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (round_type, question_text, intent,
             json.dumps(tags or [], ensure_ascii=False),
             difficulty, source, session_id),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_question(question_id: int, **kwargs) -> bool:
    """更新题库题目"""
    allowed = {"round_type", "question_text", "intent", "tags", "difficulty", "source", "is_favorited"}
    updates = {}
    for k, v in kwargs.items():
        if k in allowed:
            if k == "tags" and isinstance(v, list):
                updates[k] = json.dumps(v, ensure_ascii=False)
            else:
                updates[k] = v
    if not updates:
        return False

    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [question_id]

    db = await get_db()
    try:
        await db.execute(
            f"UPDATE question_bank SET {set_clause} WHERE id = ?", values
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_question(question_id: int) -> bool:
    """删除题库题目"""
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def toggle_favorite(question_id: int) -> Optional[bool]:
    """切换收藏状态，返回新状态"""
    db = await get_db()
    try:
        async with db.execute("SELECT is_favorited FROM question_bank WHERE id = ?", (question_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            new_val = 0 if row[0] else 1
            await db.execute("UPDATE question_bank SET is_favorited = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                             (new_val, question_id))
            await db.commit()
            return bool(new_val)
    finally:
        await db.close()


async def increment_usage(question_id: int) -> None:
    """增加使用次数"""
    db = await get_db()
    try:
        await db.execute("UPDATE question_bank SET usage_count = usage_count + 1 WHERE id = ?", (question_id,))
        await db.commit()
    finally:
        await db.close()


async def list_questions(
    round_type: str = None,
    difficulty: int = None,
    favorited: bool = None,
    search: str = None,
    source: str = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """列出题库题目（支持过滤）"""
    db = await get_db()
    try:
        where = ["1=1"]
        params = []

        if round_type:
            where.append("round_type = ?")
            params.append(round_type)
        if difficulty is not None:
            where.append("difficulty = ?")
            params.append(difficulty)
        if favorited:
            where.append("is_favorited = 1")
        if source:
            where.append("source = ?")
            params.append(source)
        if search:
            where.append("(question_text LIKE ? OR intent LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        query = f"""SELECT * FROM question_bank
                    WHERE {' AND '.join(where)}
                    ORDER BY is_favorited DESC, usage_count DESC, created_at DESC
                    LIMIT ? OFFSET ?"""
        params.extend([limit, offset])

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d.get("tags", "[]"))
                d["is_favorited"] = bool(d.get("is_favorited", 0))
                results.append(d)
            return results
    finally:
        await db.close()


async def import_questions_from_session(session_id: str) -> int:
    """从面试会话中导入问题到题库，返回导入数量"""
    qas = await get_session_qas(session_id)
    if not qas:
        return 0

    count = 0
    for qa in qas:
        question = qa.get("question", "")
        if not question or "[追问]" in question:
            continue
        round_index = qa.get("round_index", 0)
        round_names = [r["name"] for r in config.INTERVIEW_ROUNDS]
        round_type = round_names[round_index] if round_index < len(round_names) else ""

        # 避免重复导入
        db = await get_db()
        try:
            async with db.execute(
                "SELECT COUNT(*) FROM question_bank WHERE question_text = ? AND session_id = ?",
                (question, session_id),
            ) as cur:
                row = await cur.fetchone()
                if row and row[0] > 0:
                    continue
        finally:
            await db.close()

        await add_question(
            question_text=question,
            round_type=round_type,
            source="ai_generated",
            session_id=session_id,
            difficulty=3,
        )
        count += 1

    return count


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
