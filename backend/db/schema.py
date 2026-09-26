"""建表与列迁移。init_db 串起全部 _ensure_*/_drop_* 步骤，幂等可重跑。"""

import logging
import sqlite3

from .connection import get_db

logger = logging.getLogger(__name__)


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
