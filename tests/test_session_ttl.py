"""state.active_sessions 的 TTL 治理（v8.12）。

泄漏路径：POST /api/sessions 创建的条目只有 WS 结束才会注销——若前端拿到
session_id 后从未建立 WS（页面刷新后重开一场、放弃连接），条目永久滞留内存。
register / unregister / sweep 三件套把"创建时刻"纳入跟踪，过期条目在下次
创建会话时被清出。

设计契约（逐条可证伪）：
- sweep 只清"登记过创建时刻且已过期"的条目——直接塞进 active_sessions 的
  外来条目（无 created_at 登记）绝不会被 sweep 误杀；
- unregister 对两张表同时清理，不留 created_at 悬挂项，且重复注销是安全 no-op；
- 未过期的条目在默认 TTL 下不被清。
"""
import time

import pytest

from backend.routers import state


class _FakeSession:
    """active_sessions 只存引用，最小对象即可。"""


@pytest.fixture(autouse=True)
def _isolate_state():
    """state 是模块级全局表，跨文件残留会让 sweep 的返回值断言失真。"""
    state.active_sessions.clear()
    state.session_created_at.clear()
    yield
    state.active_sessions.clear()
    state.session_created_at.clear()


@pytest.mark.asyncio
async def test_stale_entry_swept_after_ttl():
    await state.register_session("s1", _FakeSession())
    assert "s1" in state.active_sessions
    assert "s1" in state.session_created_at

    swept = await state.sweep_stale_sessions(ttl_seconds=0)
    assert swept == ["s1"]
    assert "s1" not in state.active_sessions
    assert "s1" not in state.session_created_at


@pytest.mark.asyncio
async def test_fresh_entry_survives_default_ttl():
    await state.register_session("s2", _FakeSession())
    assert await state.sweep_stale_sessions() == []
    assert "s2" in state.active_sessions
    await state.unregister_session("s2")


@pytest.mark.asyncio
async def test_unregister_cleans_both_tables():
    await state.register_session("s3", _FakeSession())
    await state.unregister_session("s3")
    assert "s3" not in state.active_sessions
    assert "s3" not in state.session_created_at
    # 重复注销是安全 no-op（WS 正常路径与异常路径共用同一个 finally）
    await state.unregister_session("s3")


@pytest.mark.asyncio
async def test_sweep_never_touches_foreign_entries():
    """无 created_at 登记的外来条目不属于 sweep 的管辖对象——它没有 TTL 依据。"""
    foreign = _FakeSession()
    state.active_sessions["foreign"] = foreign
    try:
        await state.sweep_stale_sessions(ttl_seconds=0)
        assert state.active_sessions.get("foreign") is foreign
    finally:
        state.active_sessions.pop("foreign", None)


@pytest.mark.asyncio
async def test_mixed_stale_and_fresh_sweeps_only_stale():
    await state.register_session("old", _FakeSession())
    await state.register_session("new", _FakeSession())
    # 人为把 old 的创建时刻拨回 TTL 之前
    state.session_created_at["old"] = time.monotonic() - 10_000

    swept = await state.sweep_stale_sessions(ttl_seconds=7200)
    assert swept == ["old"]
    assert "new" in state.active_sessions
    await state.unregister_session("new")
