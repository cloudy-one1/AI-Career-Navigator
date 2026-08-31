"""全局服务状态（L4 装配层单例）。

为什么单独一个模块：llm_client / diagnosis_engine 是被所有会话共享的模块级
单例（已知局限，README 有披露），switch_provider 会对它们**重赋值**。拆分前
重赋值发生在 main.py 内（`global` 声明），拆分后如果路由模块各自 `from main
import llm_client`，拿到的是绑定时的旧对象——重赋值后路由仍在用旧实例。
收敛到本模块后，所有读写都经 `state.xxx` 属性访问，单一事实源。

已知局限照旧：全局单例无按会话隔离，多后端高频切换/并发导入下存在理论竞态
（provider_lock 只保护重赋值本身），课程项目阶段仅文档披露不做隔离。
"""
import asyncio

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
session_lock = asyncio.Lock()    # 保护 active_sessions 的读写
provider_lock = asyncio.Lock()   # 保护 llm_client / diagnosis_engine 重赋值
