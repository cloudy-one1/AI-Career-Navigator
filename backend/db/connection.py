"""数据库连接：每次调用新开一条 aiosqlite 连接（本模块没有连接缓存）。"""

import logging
import os

import aiosqlite

from ..config import config

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
