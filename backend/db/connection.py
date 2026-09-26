"""数据库连接：每次调用新开一条 aiosqlite 连接（本模块没有连接缓存）。"""

import asyncio
import logging
import os
import sqlite3

import aiosqlite

from ..config import config

logger = logging.getLogger(__name__)

_ITER_CHUNK_SIZE = 64  # 与 aiosqlite.connect 的默认值一致

# 确保 data 目录存在（:memory: 为 SQLite 内存模式，无须文件系统目录）
_db_dir = os.path.dirname(config.DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)


def _sync_shutdown(db: "_CancelSafeConnection") -> None:
    """不触碰事件循环地收掉一条连接。

    stop() 让 worker 线程关闭 sqlite 后自然退出；join() 确保循环关闭前，
    所有已入队 future（含在途操作）都在 loop 存活期间结算完毕——否则
    worker 向已关闭的 loop call_soon_threadsafe 会炸出线程未捕获异常。
    """
    db.stop()
    thread = getattr(db, "_thread", None)
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


class _CancelSafeConnection(aiosqlite.Connection):
    """close() 在取消路径上退化为同步 stop()，保证 worker 线程干净收尾。

    为什么需要：anyio 的 CancelScope 一旦取消，作用域内任务的**每个 await**
    都会被立即再次取消——`finally: await db.close()` 在取消路径上永远等不到
    worker 的回程（TestClient 拆除 WS 会话时 cs.cancel() 可能恰好落在某个
    db 调用半途）。连接于是带着在途 future 被遗留；事件循环一关，aiosqlite
    worker 线程处理队列项时向已关闭的 loop `call_soon_threadsafe` →
    RuntimeError → 线程未捕获异常 → pytest 偶发
    PytestUnhandledThreadExceptionWarning（v8.11 登记的 flaky，实测约 1/4）。

    仅当 Task.cancelling() > 0（正常路径恒为 0，Python 3.11+）时走该分支，
    正常路径与原生 close() 完全一致。
    """

    async def close(self) -> None:
        task = asyncio.current_task()
        cancelling = getattr(task, "cancelling", None)
        if cancelling is not None and cancelling() > 0:
            _sync_shutdown(self)
            return
        await super().close()


async def open_sqlite(
    path: str,
    *,
    enable_foreign_keys: bool = False,
    enable_wal: bool = True,
    **sqlite_connect_kwargs,
) -> aiosqlite.Connection:
    """interview / market / importer 共用的连接工厂。

    与 `aiosqlite.connect(path, **kwargs)` 等价，但返回的连接具备取消安全的
    close()。WAL 与外键按需开启（importer 的只读连接两个都不要）。

    打开半途（connect / PRAGMA 的任一 await）被取消时同样就地同步收干净：
    此时调用方永远拿不到这条连接，没人会对它调 close()——这正是
    "cancel 落在 db 调用半途"泄漏的另一半窗口。
    """

    def connector():
        return sqlite3.connect(path, **sqlite_connect_kwargs)

    db = _CancelSafeConnection(connector, _ITER_CHUNK_SIZE)
    try:
        db = await db
        db.row_factory = aiosqlite.Row
        if enable_wal:
            await db.execute("PRAGMA journal_mode=WAL")
        if enable_foreign_keys:
            await db.execute("PRAGMA foreign_keys=ON")
    except BaseException:
        _sync_shutdown(db)
        raise
    return db


async def get_db():
    return await open_sqlite(config.DB_PATH, enable_foreign_keys=True)
