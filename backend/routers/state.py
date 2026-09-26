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
session_lock = asyncio.Lock()    # 保护 active_sessions 的读写
provider_lock = asyncio.Lock()   # 保护 llm_client / diagnosis_engine 重赋值


async def register_session(session_id: str, session: InterviewSession) -> None:
    """WS 尚未接管的会话条目登记（含创建时刻）。调用方无需自己持锁。"""
    async with session_lock:
        active_sessions[session_id] = session
        session_created_at[session_id] = time.monotonic()


async def unregister_session(session_id: str) -> None:
    """WS 结束（正常/断开/异常）时的对称注销。调用方无需自己持锁。"""
    async with session_lock:
        active_sessions.pop(session_id, None)
        session_created_at.pop(session_id, None)


async def sweep_stale_sessions(ttl_seconds: int | None = None) -> list[str]:
    """清掉创建后超过 TTL 的会话条目，返回被清的 session_id 列表。

    唯一的泄漏窗口是"创建后 WS 从未接管"（页面刷新后重开一场、拿到 session_id
    后放弃连接）——WS 正常接管后由其 finally 对称注销，不依赖本函数。
    若某条目仍在被活跃的 WS 主循环使用，清出只影响同 id 的第二次握手
    （会得到 4000），对进行中的面试无影响（handler 持有的是局部引用）。
    """
    ttl = config.SESSION_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    now = time.monotonic()
    async with session_lock:
        stale = [sid for sid, ts in session_created_at.items() if now - ts > ttl]
        for sid in stale:
            active_sessions.pop(sid, None)
            session_created_at.pop(sid, None)
    return stale
