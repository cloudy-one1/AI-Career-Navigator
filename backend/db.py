"""
数据库 v2.5：SQLite 多表操作 (aiosqlite)
v2.2: 新增 question_bank 表
v2.5: 新增 diagnosis_feedback 表
"""

import aiosqlite
import json
import os
import sqlite3
from datetime import datetime
from typing import Optional
import logging

from .config import config

logger = logging.getLogger(__name__)

# 确保 data 目录存在（:memory: 为 SQLite 内存模式，无须文件系统目录）
_db_dir = os.path.dirname(config.DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)


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
                resume_text TEXT DEFAULT '',
                jd_text TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # v3.1: 迁移旧数据库——补充 resume_text 列
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN resume_text TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # 列已存在（重复 ALTER 会抛 duplicate column，属预期）

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
        # [v3.0 修复] 此前误用未定义变量 cursor，init_db 运行即抛 NameError
        await db.execute("""
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

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_session ON diagnosis_feedback(session_id)"
        )

        # v2.7: 薄弱点画像累积
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weakness_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                dimension TEXT NOT NULL,
                avg_score REAL NOT NULL,
                weight REAL NOT NULL,
                risk_points TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_weakness_session ON weakness_profile(session_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_weakness_dim ON weakness_profile(dimension)"
        )
        # v6.3: 老库升级（必须在 CREATE TABLE IF NOT EXISTS 之后单独做）
        await _ensure_weakness_columns(db)

        # v6.5: 长期薄弱点记忆（EMA 衰减 + 过期淘汰）。
        # 新建表用 CREATE TABLE IF NOT EXISTS 即可（新增表对老库也生效，
        # 只有"给已有表加列"才需要下面的 PRAGMA+ALTER 迁移）。
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weakness_memory (
                dimension TEXT PRIMARY KEY,
                weakness_score REAL NOT NULL DEFAULT 0,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                last_score REAL,
                last_seen TEXT,
                expires_at TEXT,
                updated_at TEXT
            )
        """)

        # v3.1: JD 权重缓存表（避免同一 JD 重复调 LLM 分析权重）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jd_weights_cache (
                jd_hash TEXT PRIMARY KEY,
                jd_preview TEXT NOT NULL,
                weights_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        await db.commit()
        logger.info("数据库初始化完成（含 question_bank、diagnosis_feedback、weakness_profile、jd_weights_cache 表）")
    finally:
        await db.close()


# ===== Sessions =====

async def save_session(session_id: str, style: str = "friendly",
                        resume_filename: str = "", jd_text: str = "",
                        resume_text: str = "") -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO sessions (id, style, resume_filename, jd_text, resume_text) VALUES (?, ?, ?, ?, ?)",
            (session_id, style, resume_filename, jd_text, resume_text),
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


# ===== v2.7: Weakness Profile（v6.3 扩展为长期记忆闭环）=====

async def _ensure_weakness_columns(db) -> None:
    """幂等迁移：为 weakness_profile 补 resolved / updated_at 两列。

    为什么必须独立做：init_db 建表用的是 CREATE TABLE IF NOT EXISTS，
    对**已存在的旧库**完全不生效——直接把新列写进建表语句只对新库有效，
    老库升级后所有查询都会报 "no such column: resolved"。
    故这里先查 PRAGMA table_info 再按需 ALTER，且可重复执行。
    """
    async with db.execute("PRAGMA table_info(weakness_profile)") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    if "resolved" not in existing:
        await db.execute(
            "ALTER TABLE weakness_profile ADD COLUMN resolved INTEGER DEFAULT 0"
        )
        logger.info("[db] weakness_profile 迁移：新增 resolved 列")
    if "updated_at" not in existing:
        await db.execute("ALTER TABLE weakness_profile ADD COLUMN updated_at TEXT")
        logger.info("[db] weakness_profile 迁移：新增 updated_at 列")


async def save_weakness_profile(session_id: str, dimension: str,
                                 avg_score: float, weight: float,
                                 risk_points: list[str] = None) -> None:
    """保存单次会话的维度薄弱点快照"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO weakness_profile
               (session_id, dimension, avg_score, weight, risk_points)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, dimension, avg_score, weight,
             json.dumps(risk_points or [], ensure_ascii=False)),
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


async def get_global_weakness_profile() -> list[dict]:
    """获取全局薄弱点聚合：各维度历史平均分"""
    db = await get_db()
    try:
        async with db.execute("""
            SELECT dimension,
                   ROUND(AVG(avg_score), 2) as historical_avg,
                   ROUND(AVG(weight), 2) as avg_weight,
                   COUNT(DISTINCT session_id) as session_count,
                   SUM(CASE WHEN COALESCE(resolved, 0) = 0 THEN 1 ELSE 0 END) as open_count
            FROM weakness_profile
            GROUP BY dimension
            ORDER BY historical_avg ASC
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        await db.close()


# ===== v6.3: 长期记忆闭环（记忆图谱 / 复习建议 / 面试回注入共用同一查询口径）=====

async def list_weakness_points(include_resolved: bool = False,
                               limit: int | None = None) -> list[dict]:
    """薄弱点明细列表（长期记忆的数据源）。

    include_resolved=False（默认）只返回未解决的——这是面试回注入、
    复习建议、图谱主视图的统一口径。

    排序：avg_score 升序（越薄弱越靠前）+ weight 降序（岗位越看重越靠前），
    与"优先复习最要命的短板"这一产品意图一致。
    """
    sql = """
        SELECT id, session_id, dimension, avg_score, weight, risk_points,
               COALESCE(resolved, 0) as resolved, created_at, updated_at
        FROM weakness_profile
    """
    params: list = []
    if not include_resolved:
        sql += " WHERE COALESCE(resolved, 0) = 0"
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


# ===== v6.5: 长期薄弱点记忆（EMA 衰减 + 过期淘汰）=====
# 与 weakness_profile（每会话每维度一行快照，历史）分工：
#   weakness_profile = 历史流水（图谱/建议/回注入的素材）
#   weakness_memory  = 当前状态（每维度一行，带薄弱度/计数/过期时间）
# 纯计算在 L2 的 weakness_memory.py，这里只做 CRUD（L1 不得反向依赖 L2）。

async def get_weakness_memory(dimension: str) -> dict | None:
    """读取单个维度的长期薄弱点状态（不存在返回 None）。"""
    db = await get_db()
    try:
        async with db.execute(
            """SELECT dimension, weakness_score, occurrence_count, last_score,
                      last_seen, expires_at, updated_at
               FROM weakness_memory WHERE dimension = ?""",
            (dimension,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def upsert_weakness_memory(dimension: str, state: dict) -> None:
    """写入/更新单个维度的长期薄弱点状态（由 L2 算好状态后传入）。"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO weakness_memory
               (dimension, weakness_score, occurrence_count, last_score,
                last_seen, expires_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(dimension) DO UPDATE SET
                   weakness_score=excluded.weakness_score,
                   occurrence_count=excluded.occurrence_count,
                   last_score=excluded.last_score,
                   last_seen=excluded.last_seen,
                   expires_at=excluded.expires_at,
                   updated_at=excluded.updated_at""",
            (
                dimension,
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


async def delete_weakness_memory(dimension: str) -> None:
    """删除单个维度的长期薄弱点状态（计数归零 / 已解决时调用）。"""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM weakness_memory WHERE dimension = ?", (dimension,)
        )
        await db.commit()
    finally:
        await db.close()


async def list_active_weakness_memory(limit: int = 10) -> list[dict]:
    """未过期的长期薄弱点，按薄弱度降序（最要命的排最前）。

    过期判定与写入端一致用 localtime（数据库里存的是 localtime 文本）。
    """
    sql = """
        SELECT dimension, weakness_score, occurrence_count, last_score,
               last_seen, expires_at, updated_at
        FROM weakness_memory
        WHERE weakness_score > 0
          AND (expires_at IS NULL OR expires_at > datetime('now', 'localtime'))
        ORDER BY weakness_score DESC, occurrence_count DESC
    """
    params: list = []
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


# ===== v3.1: JD 权重缓存 =====

async def lookup_jd_weights(jd_hash: str) -> dict | None:
    """根据 JD 哈希查找缓存的权重结果，若有则返回解析后的 dict，否则返回 None"""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT weights_json FROM jd_weights_cache WHERE jd_hash = ?", (jd_hash,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    cached = json.loads(row[0])
                    if isinstance(cached, dict) and "weights" in cached:
                        cached["source"] = "cache"  # 覆盖标记
                        return cached
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"JD 权重缓存数据损坏 (hash={jd_hash[:12]}...)，忽略")
                    return None
        return None
    finally:
        await db.close()


async def save_jd_weights(jd_hash: str, jd_preview: str, weights: dict) -> None:
    """保存 JD 权重分析结果到缓存"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO jd_weights_cache (jd_hash, jd_preview, weights_json) VALUES (?, ?, ?)",
            (jd_hash, jd_preview[:100], json.dumps(weights, ensure_ascii=False)),
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"JD 权重缓存写入失败: {e}")
    finally:
        await db.close()
