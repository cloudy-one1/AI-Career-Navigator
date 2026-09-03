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
        # v8.4: 主键从 dimension 单键改为 (dimension, position_id) 复合主键，
        #   支持按岗位隔离薄弱点数据。
        #   注意：SQLite UNIQUE 约束中 NULL != NULL，故 position_id 用空字符串 ''
        #   作为'全局/未知岗位'的哨兵值（由 _normalize_position_id 统一处理）。
        # 新建表用 CREATE TABLE IF NOT EXISTS 即可（新增表对老库也生效，
        # 只有"给已有表加列"才需要下面的 PRAGMA+ALTER 迁移）。
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weakness_memory (
                dimension TEXT NOT NULL,
                position_id TEXT NOT NULL DEFAULT '',
                weakness_score REAL NOT NULL DEFAULT 0,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                last_score REAL,
                last_seen TEXT,
                expires_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (dimension, position_id)
            )
        """)
        # v8.4: 老库迁移——为 weakness_memory 补 position_id 列，重建主键
        await _ensure_weakness_memory_position_column(db)

        # v3.1: JD 权重缓存表（避免同一 JD 重复调 LLM 分析权重）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jd_weights_cache (
                jd_hash TEXT PRIMARY KEY,
                jd_preview TEXT NOT NULL,
                weights_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # ===== v7.0: 简历/岗位库（可复用输入资产）=====
        # owner_id 列随认证下线一并移除，老库由
        # _drop_auth_columns 迁移，新建库直接无此列。
        # 注意：不加 FOREIGN KEY —— 见 _ensure_session_columns 注释（SQLite ALTER 限制）。
        await db.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT,
                raw_text TEXT NOT NULL,
                parsed_json TEXT,
                char_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                department TEXT,
                jd_text TEXT NOT NULL,
                -- v8.2 来源区分：manual=手工新建，market=从市场数据收藏导入。
                -- market_job_id 记录 market.db 的岗位 id，仅 market 来源有值：
                -- 既用于溯源（可回看 51job 原文），也用于"同一市场岗位只导入一次"的幂等判断。
                source TEXT DEFAULT 'manual',
                market_job_id INTEGER,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # v8.1: 旅程关键动作打点。
        # 设计取舍——**能推导的就不落库**：五步里前四步都能从档案实时算出来
        # （有简历 / 有目标岗位 / 开过场 / 出过报告），只有"是否已生成发展路径"
        # 无法推导，才需要这张极小的表。避免一张冗余宽表与双写一致性问题。
        # v8.3: 主键由 (owner_id, step_key) 收敛为 step_key——单用户下 owner 是伪维度。
        await db.execute("""
            CREATE TABLE IF NOT EXISTS journey_marks (
                step_key TEXT PRIMARY KEY,
                marked_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # v7.0: 老库升级（给已有表加列必须走 PRAGMA+ALTER 迁移，不能用 CREATE 覆盖）
        await _ensure_session_columns(db)
        await _ensure_position_source_columns(db)
        # v8.3: 认证下线——删 users 表、删 owner_id 列、journey_marks 去 owner
        await _drop_auth_columns(db)

        await db.commit()
        logger.info("数据库初始化完成（含 question_bank、diagnosis_feedback、weakness_profile、jd_weights_cache、resumes、positions、journey_marks 表）")
    finally:
        await db.close()


# ===== Sessions =====

async def _ensure_session_columns(db) -> None:
    """v7.0 幂等迁移：为 sessions 补 resume_id / position_id / flow_state 等列。

    范式与 _ensure_weakness_columns 一致：老库上 CREATE TABLE IF NOT EXISTS 不生效，
    必须 PRAGMA table_info 探测后按需 ALTER，否则所有新列查询报 "no such column"。

    v8.3: 本函数原名为 _ensure_owner_columns、首列是 owner_id，认证下线后
    该列由 _drop_auth_columns 反向删除，这里只留与归属无关的四个列。

    ⚠️ SQLite 限制：ALTER TABLE ADD COLUMN **不支持 REFERENCES**，
    因此这三列都不带外键约束。这是 SQLite 的硬限制，不是实现偷懒 ——
    若将来迁移到 PostgreSQL 应补上外键。
    """
    async with db.execute("PRAGMA table_info(sessions)") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    for col in ("resume_id", "position_id",
                "flow_state", "flow_updated_at", "answered_count"):
        if col in existing:
            continue
        if col == "answered_count":
            await db.execute("ALTER TABLE sessions ADD COLUMN answered_count INTEGER DEFAULT 0")
        else:
            await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
        logger.info(f"[db] sessions 迁移：新增 {col} 列")

    # 报告分享与招聘者收件箱已删除，老库中的 share_links
    # 表一并清掉——历史分享链接已无意义，避免残留数据形成"看得见改不了"的死角。
    await db.execute("DROP TABLE IF EXISTS share_links")


async def _drop_auth_columns(db) -> None:
    """v8.3 幂等迁移：删除认证遗留（users 表 / 三张表的 owner_id 列 / journey_marks 的 owner 维度）。

    为什么是 DROP 而不是"留着不读写"：留一列永不读写的 owner_id 等于在 schema 层
    保留了一套已被废弃的身份模型，下次改动的人必须重新判断"这列还有没有用"。
    删除的代价是一次不可逆迁移，收益是 schema 与代码语义一致。

    为什么整段包 try/except：迁移失败不该让服务起不来。最坏情况是老库仍带着
    死列（代码已不读它，功能不受影响），下次启动会再试一次。

    journey_marks 为什么要重建表而不是 DROP COLUMN：它的主键是
    (owner_id, step_key)，去掉 owner_id 后主键本身要改，SQLite 无法用 ALTER
    改主键，只能建新表搬数据再改名的标准三步。
    """
    try:
        # 1) 先删索引：SQLite 对"被索引引用的列"执行 DROP COLUMN 会报错
        for idx in ("idx_users_username", "idx_resumes_owner", "idx_positions_owner"):
            await db.execute(f"DROP INDEX IF EXISTS {idx}")

        # 2) 删 owner_id 列（sessions / resumes / positions）
        for table in ("sessions", "resumes", "positions"):
            async with db.execute(f"PRAGMA table_info({table})") as cur:
                cols = {row[1] for row in await cur.fetchall()}
            if "owner_id" in cols:
                await db.execute(f"ALTER TABLE {table} DROP COLUMN owner_id")
                logger.info(f"[db] {table} 迁移：删除 owner_id 列")

        # 3) 删 users 表（除认证外无任何用途，无外键引用）
        await db.execute("DROP TABLE IF EXISTS users")

        # 4) journey_marks：带 owner_id 的老表 → 重建为 step_key 主键
        async with db.execute("PRAGMA table_info(journey_marks)") as cur:
            jm_cols = {row[1] for row in await cur.fetchall()}
        if "owner_id" in jm_cols:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS journey_marks_v2 (
                    step_key TEXT PRIMARY KEY,
                    marked_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            # 同一 step_key 在老表里可能有多行（每个 owner 一行），按最晚时间归并
            await db.execute("""
                INSERT OR REPLACE INTO journey_marks_v2 (step_key, marked_at)
                SELECT step_key, MAX(marked_at) FROM journey_marks GROUP BY step_key
            """)
            await db.execute("DROP TABLE journey_marks")
            await db.execute("ALTER TABLE journey_marks_v2 RENAME TO journey_marks")
            logger.info("[db] journey_marks 迁移：重建为 step_key 主键")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[db] 认证遗留清理未完成（不影响使用，下次启动重试）: {e}")


async def _ensure_position_source_columns(db) -> None:
    """v8.2 幂等迁移：为 positions 补 source / market_job_id 列。

    与 _ensure_owner_columns 同一范式：老库上 CREATE TABLE IF NOT EXISTS 不生效，
    必须 PRAGMA table_info 探测后按需 ALTER，否则新列查询报 "no such column"。
    存量岗位统一标记为 manual（它们确实都是手工新建的）。
    """
    async with db.execute("PRAGMA table_info(positions)") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    if not existing:      # 表尚不存在（极低概率），交给 CREATE TABLE 处理
        return
    if "source" not in existing:
        await db.execute(
            "ALTER TABLE positions ADD COLUMN source TEXT DEFAULT 'manual'")
        logger.info("[db] positions 迁移：新增 source 列")
    if "market_job_id" not in existing:
        await db.execute("ALTER TABLE positions ADD COLUMN market_job_id INTEGER")
        logger.info("[db] positions 迁移：新增 market_job_id 列")


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


async def get_question(question_id: int) -> Optional[dict]:
    """按主键查询单条题目；不存在返回 None（tags 反序列化为 list）。

    为什么必须有它：编辑/删除前的存在性校验只能按主键查。此前
    `question_bank._exists` 用 list_questions(limit=1, offset=question_id-1)，
    把自增主键当成行偏移量——id 在删除后不连续（出现空洞），偏移量与主键
    不再一一对应，于是出现"列表里看得见、却编辑/删除不了"的诡异现象。
    """
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM question_bank WHERE id = ?", (question_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["is_favorited"] = bool(d.get("is_favorited", 0))
        return d
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
    """幂等迁移：为 weakness_profile 补 resolved / updated_at / position_id 列。

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
    # v8.4: 岗位隔离——记录每条薄弱点快照关联的岗位
    if "position_id" not in existing:
        await db.execute("ALTER TABLE weakness_profile ADD COLUMN position_id TEXT")
        logger.info("[db] weakness_profile 迁移：新增 position_id 列")


async def _ensure_weakness_memory_position_column(db) -> None:
    """v8.4 幂等迁移：weakness_memory 从 dimension 单键改为 (dimension, position_id) 复合主键。

    SQLite 不支持直接 DROP PRIMARY KEY 或 ALTER 主键定义，迁移步骤：
      1. 新建临时表（含 position_id 列 + 复合主键）
      2. 迁移旧数据（position_id 填 NULL 表示全局/未知）
      3. 删旧表，重命名新表
    对新建库（已有复合主键）此函数无效果（检测到 position_id 列存在即跳过）。
    """
    async with db.execute("PRAGMA table_info(weakness_memory)") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    if "position_id" in existing:
        return  # 已是新结构，跳过

    logger.info("[db] weakness_memory 迁移：单键 → 复合主键 (dimension, position_id)")
    # 1. 建新结构表（先清理上次可能残留的临时表，保证幂等）
    await db.execute("DROP TABLE IF EXISTS weakness_memory_new")
    await db.execute("""
        CREATE TABLE weakness_memory_new (
            dimension TEXT NOT NULL,
            position_id TEXT NOT NULL DEFAULT '',
            weakness_score REAL NOT NULL DEFAULT 0,
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            last_score REAL,
            last_seen TEXT,
            expires_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (dimension, position_id)
        )
    """)
    # 2. 迁移数据（旧表无 position_id 列，旧数据统一以空字符串 '' 作为'全局'哨兵值）
    await db.execute("""
        INSERT INTO weakness_memory_new
            (dimension, position_id, weakness_score, occurrence_count,
             last_score, last_seen, expires_at, updated_at)
        SELECT dimension, '', weakness_score, occurrence_count,
               last_score, last_seen, expires_at, updated_at
        FROM weakness_memory
    """)
    # 3. 替换
    await db.execute("DROP TABLE weakness_memory")
    await db.execute("ALTER TABLE weakness_memory_new RENAME TO weakness_memory")
    logger.info("[db] weakness_memory 迁移完成")


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
