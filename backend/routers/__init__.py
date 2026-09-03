"""
v7.2.2: HTTP 路由域拆分（原 main.py 单体 2100 行 / 66 条路由）。

拆分原则（ mechanical move，不改任何行为）：
  - 每个文件一个 FastAPI APIRouter，路由路径 / 方法 / 处理逻辑与拆分前逐字一致；
  - main.py 只保留「应用装配」：中间件、限流异常处理器、startup、
    include_router（保持与原文件相同的注册顺序）、WS、静态挂载；
  - 全局服务单例（llm_client / diagnosis_engine / active_sessions / 限流器）
    收敛到 state.py —— switch_provider 对它们重赋值，单一事实源，消除
    "main 模块属性 vs 路由模块闭包"两份引用漂移的可能；
  - 路由层共用常量与「资源不存在」断言放在 deps.py（认证下线后，
    原认证依赖与归属断言一并删除）。

分层契约：本包属 L4（与 backend.main 同层），见 .importlinter。
"""
