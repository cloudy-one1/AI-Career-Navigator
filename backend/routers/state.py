"""全局服务状态（L4 装配层单例）。

为什么单独一个模块：llm_client / diagnosis_engine 是被所有会话共享的模块级
单例（已知局限，README 有披露），switch_provider 会对它们**重赋值**。拆分前
重赋值发生在 main.py 内（`global` 声明），拆分后如果路由模块各自 `from main
import llm_client`，拿到的是绑定时的旧对象——重赋值后路由仍在用旧实例。
收敛到本模块后，所有读写都经 `state.xxx` 属性访问，单一事实源。

已知局限照旧：全局单例无按会话隔离，多后端高频切换/并发导入下存在理论竞态
（provider_lock 只保护重赋值本身），当前仅文档披露不做隔离。
"""
import asyncio
import time

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import config
from ..llm_client import LLMClient
from ..diagnosis_engine import DiagnosisEngine
from ..interview_engine import InterviewSession

# ─── 限流器（main.py 挂到 app.state，slowapi 异常处理器依赖它）───
limiter = Limiter(key_func=get_remote_address, default_limits=[config.RATE_LIMIT_GLOBAL])

# ─── 全局 LLM 单例（switch_provider 重赋值，provider_lock 保护）───
llm_client = LLMClient(provider=config.AI_PROVIDER)
diagnosis_engine = DiagnosisEngine(llm_client=llm_client)

# ─── 活跃面试会话表（内存态；进程重启即失，进行中的那道题会丢——已知局限）───
active_sessions: dict[str, InterviewSession] = {}
session_created_at: dict[str, float] = {}   # session_id → time.monotonic()，TTL 依据
ws_active: set[str] = set()      # 正被 WS 主循环驱动的会话（单连接守卫 + sweep 豁免）
session_lock = asyncio.Lock()    # 保护 active_sessions / ws_active 的读写
provider_lock = asyncio.Lock()   # 保护 llm_client / diagnosis_engine 重赋值


async def register_session(session_id: str, session: InterviewSession) -> None:
    """WS 尚未接管的会话条目登记（含创建时刻）。调用方无需自己持锁。

    v8.21: 已有同名条目时保留先到者——并发快照复活场景下，两个握手可能各自
    重建了会话对象，后注册者覆盖会让先认领成功的主循环驱动一个脱离注册表的
    孤儿对象。
    """
    async with session_lock:
        if session_id in active_sessions:
            return
        active_sessions[session_id] = session
        session_created_at[session_id] = time.monotonic()


async def unregister_session(session_id: str) -> None:
    """WS 结束（正常/断开/异常）时的对称注销。调用方无需自己持锁。"""
    async with session_lock:
        active_sessions.pop(session_id, None)
        session_created_at.pop(session_id, None)
        ws_active.discard(session_id)


async def acquire_ws_session(session_id: str) -> tuple[InterviewSession | None, str | None]:
    """原子完成「查会话 + 单连接认领」，返回 (session, err)；err 为 None 即认领成功。

    - session_not_found：active_sessions 无此条目（未创建 / 已注销 / 被误清）。
    - session_already_active：该会话已有一条 WS 主循环在驱动——没有这道守卫时，
      第二次握手会拿到同一 session 对象，两个主循环并发出题/推进，状态互踩。
    认领成功即加入 ws_active，此后 sweep 豁免该条目（进行中的面试不再被 TTL 误杀，
    此前超过 SESSION_TTL_SECONDS 的长面试会被 sweep 清出注册表，HTTP 侧 404）。
    """
    async with session_lock:
        session = active_sessions.get(session_id)
        if session is None:
            return None, "session_not_found"
        if session_id in ws_active:
            return None, "session_already_active"
        ws_active.add(session_id)
        return session, None


async def release_ws_session(session_id: str) -> None:
    """WS 主循环结束（正常/断开/异常）时释放认领。与 unregister_session 配套调用。"""
    async with session_lock:
        ws_active.discard(session_id)


async def sweep_stale_sessions(ttl_seconds: int | None = None) -> list[str]:
    """清掉创建后超过 TTL 且**从未被 WS 接管**的会话条目，返回被清的 session_id 列表。

    唯一的清理对象是"创建后 WS 从未接管"（页面刷新后重开一场、拿到 session_id
    后放弃连接）——被 WS 接管过的条目在 ws_active 里，sweep 一律豁免；
    WS 结束时由 finally 对称注销（unregister + release），不依赖本函数。
    """
    ttl = config.SESSION_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    now = time.monotonic()
    async with session_lock:
        stale = [sid for sid, ts in session_created_at.items()
                 if now - ts > ttl and sid not in ws_active]
        for sid in stale:
            active_sessions.pop(sid, None)
            session_created_at.pop(sid, None)
    return stale
