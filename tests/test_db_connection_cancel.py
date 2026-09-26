"""取消路径上的 db.close() 契约（v8.12，修复 WS 断连泄漏 SQLite 连接的 flaky）。

背景机制：anyio 的 CancelScope 取消后，作用域内任务的每个 await 都会被立即
再次取消——`finally: await db.close()` 在取消路径上永远完不成，连接带着在途
future 被遗留；循环关闭后 aiosqlite worker 线程向已关闭的 loop
call_soon_threadsafe → RuntimeError → PytestUnhandledThreadExceptionWarning
（v8.11 登记的 flaky）。`_CancelSafeConnection.close()` 在
`Task.cancelling() > 0` 时退化为同步 stop()+join，全程无 await、无检查点，
取消无法打断它。

本文件的用例对旧行为可证伪：raw aiosqlite 的 close() 首行就是 await 检查点，
任务带取消请求调用它时必然收到 CancelledError，连接收尾被半途打断。
"""
import asyncio

import pytest

from backend.db.connection import open_sqlite


@pytest.mark.asyncio
async def test_close_completes_on_cancelled_task(tmp_path):
    """任务已带取消请求时 close() 必须同步完成，不被取消打断。"""
    db = await open_sqlite(str(tmp_path / "cancel.db"))
    await db.execute("CREATE TABLE t(x)")

    asyncio.current_task().cancel()  # 模拟 anyio CancelScope 已取消、尚未消化

    interrupted = False
    try:
        await db.close()
    except asyncio.CancelledError:
        interrupted = True  # 旧实现（raw close 首行即检查点）必然走到这里

    # 消化掉待处理的取消，让测试任务正常收尾（新实现下 close 没有消耗它）
    try:
        await asyncio.sleep(0)
    except asyncio.CancelledError:
        pass

    assert not interrupted, (
        "取消路径上的 close() 必须同步完成而不被再次取消打断——"
        "打断意味着连接带着在途 future 被遗留，循环关闭后 worker 线程必炸"
    )
    assert db._connection is None, "取消路径上的 close 必须真正关闭 sqlite 连接"
    assert not db._thread.is_alive(), "worker 线程必须在循环关闭前退出（join 完成）"


@pytest.mark.asyncio
async def test_normal_close_still_cleans_connection(tmp_path):
    """无取消请求（cancelling()==0）的常规路径与原生 close 语义一致。"""
    db = await open_sqlite(str(tmp_path / "normal.db"), enable_foreign_keys=True)
    await db.execute("CREATE TABLE t(x)")
    await db.execute("INSERT INTO t VALUES (1)")
    await db.commit()

    await db.close()
    assert db._connection is None
