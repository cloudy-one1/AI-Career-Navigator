# week8 · 面试流程状态显式化 需求文档

> 日期：2026-08-29
> 版本目标：v7.0 双端平台化改造 · D4
> 来源：Gua-AI-interview 深度研读（docs/Gua-AI-interview-深度研读.md §2.1-2.4、§6-P1-7/8/10）

---

## 1. 模块目标

### 1.1 要解决的本质问题

当前 `InterviewSession`（`backend/interview_engine/session.py`，1200 行）推进流程的方式是**命令式 + 隐式状态**：

```python
active_sessions: dict[str, InterviewSession] = {}   # 138:backend/main.py —— 纯内存
```

流程"走到哪一步"没有独立的表示，只能从业务数据**反推**：

- 最后一题有没有回答 → 推断是不是在等回答
- `current_question_idx` vs `rounds[i]["question_count"]` → 推断该不该进下一轮
- `is_closing_round()` → 推断是不是该收尾了
- `recovery_active` / `pending_follow_up` / `mode_changed` → 一堆布尔量拼出当前状态

研读 Gua 时，对方作者把这种反推的代价总结得很清楚（lesson-06 §"为什么旧链路开始吃力"）：

> 1. 一条业务流程被分散到了多个入口（首次进入 / 提交回答 / 重连 / 暂停…）
> 2. Handler 必须反推流程执行到了哪里
> 3. 分支不是简单增加，而是相互组合
> 4. 业务与流程跳转难以分开测试

逐条对照我们的 `session.py`：`handle_answer` / `stream_answer` / `handle_follow_up_answer` / `switch_mode` / `advance_round` 就是"分散的多个入口"；`check_round_quality` / `should_add_extra_question` / `should_follow_up` / `is_closing_round` 就是"组合的分支"。

**更直接的问题**：`active_sessions` 是纯内存字典，`1607:1609:backend/main.py` 在 WS 结束时还会 `pop` 掉。也就是说——**进程重启 / 连接断开，正在进行的面试就彻底没了，报告归零。**

### 1.2 目标

1. 给流程一个**显式的当前位置**（`flow_state`），不再反推
2. 把"下一步做什么"抽成**纯函数**（不依赖 DB / WebSocket / LLM），使分支可单测
3. 关键进度**落库**，保证进程重启后报告不归零

### 1.3 非目标（明确不做，这是本模块最重要的边界）

- **不做"从 DB 重建会话并续答"**。这需要把 `InterviewSession` 的全部字段（rounds / round_answers / round_diagnoses / all_diagnoses / interviewer_history / weakness_tags / long_term_memory / asked_questions / _injected_hashes …）完整序列化与反序列化，等价于给 1200 行的对象写一个 ORM。5 天工期内做扎实的风险太大，做成半成品比不做更糟。
- **不引入 LangGraph（Python 版）**。研读结论明确：我们要的是"显式程序计数器"，不是图框架。Gua 引入 LangGraph 的代价（双链路并存漂移、序列化类型登记表维护债、`GraphInput.resume` vs `invoke` 的框架语义坑）在 5 天工期下不可承受。
- 不改推进规则本身（阈值、轮次配置、收尾强控逻辑全部保持原样）——**本模块是重构，不是功能变更**

---

## 2. 技术方案

### 2.1 FlowState 枚举

```python
class FlowState(str, Enum):
    INIT                = "init"                  # 会话已建，尚未出首题
    GENERATING_QUESTION = "generating_question"   # 正在生成（或流式推送）题目
    WAITING_ANSWER      = "waiting_answer"        # 题目已出完，等待候选人回答
    DIAGNOSING          = "diagnosing"            # 收到回答，诊断中（含改写）
    DECIDING_FOLLOW_UP  = "deciding_follow_up"    # 判是否追问
    GENERATING_FOLLOW_UP= "generating_follow_up"  # 生成追问
    ADVANCING_ROUND     = "advancing_round"       # 判定/执行轮次推进
    CLOSING             = "closing"               # 收尾阶段（工程强控）
    FINISHED            = "finished"              # 已结束，报告可生成
```

对照现状，这 9 个态覆盖了 `handle_answer` / `stream_answer` / `handle_follow_up_answer` / `switch_mode` / `advance_round` 五个入口能到达的所有位置。

### 2.2 FlowSnapshot（纯数据，无 IO）

```python
@dataclass(frozen=True)
class FlowSnapshot:
    flow_state: FlowState
    current_round: int
    current_question_idx: int
    questions_in_round: int
    follow_up_count: int
    extra_added: int
    max_extra: int
    is_closing_round: bool
    recovery_active: bool
    pending_follow_up: bool
    user_ended: bool
```

**关键约束：`FlowSnapshot` 只能通过 `snapshot()` 方法从 `InterviewSession` 构造，且构造过程不得触发任何 IO**（不查 DB、不发 WS、不调 LLM）。这是它能被单测的前提。

### 2.3 decide_next 纯函数

```python
@dataclass(frozen=True)
class NextAction:
    kind: str          # ASK_QUESTION | ASK_FOLLOW_UP | ADVANCE_ROUND | CLOSE | FINISH | WAIT
    reason: str        # 人类可读的决策理由，用于日志与排查
    payload: dict      # 附带参数（如追问类型、下一轮 index）

def decide_next(s: FlowSnapshot) -> NextAction:
    """纯函数：不依赖 DB / WebSocket / LLM，可完整单测。"""
```

**收敛哪些现有逻辑**（把分散的判定集中到一个地方，但**规则本身一字不改**）：

| 现有方法 | 在 decide_next 中的角色 |
|---|---|
| `should_follow_up()` | `DECIDING_FOLLOW_UP` 态下的分支判定输入 |
| `should_add_extra_question()` | `ADVANCING_ROUND` 态下"补题还是推进" |
| `check_round_quality()` | 同上（质量阈值来自 `Config.INTERVIEW_ROUNDS`） |
| `is_closing_round()` | 路由到 `CLOSE` 的依据 |
| `is_finished` / `user_ended` | 路由到 `FINISH` 的依据 |

**重要**：`decide_next` **不改变任何判定规则**。它是一个收纳盒，不是新逻辑。这样 D4 的风险被限制在"重构正确性"范围内，不引入行为变更。

### 2.4 状态持久化（只做进度，不做续答）

`sessions` 表扩展（D2 的 `_ensure_owner_columns` 一并处理）：

```
flow_state          TEXT     -- 当前流程位置
flow_updated_at     TEXT
answered_count      INTEGER  -- 已回答题数
```

落库时机（每轮一次，不在流式过程中写，避免写放大）：

- 出完一道题 → `flow_state='waiting_answer'`
- 收到回答并完成诊断 → `flow_state='diagnosing'` → 决策后 → 新态
- 轮次推进 → `flow_state='advancing_round'` → 新轮首题
- 结束 → `flow_state='finished'`

**恢复能力的边界（务必如实写进 README）**：
- ✅ 进程重启后，报告页能显示"已完成到第 N 题"与已有诊断结果
- ❌ 不能接着上次那道题继续答——会话对象在内存，重启即失效

### 2.5 与 D1 的衔接

`flow_state` 落库后可被招聘端/分享页用于展示"面试完成度"，但目前分享页（D3）不展示该字段——保持解耦，避免过度设计。

---

## 3. 涉及的知识点

1. **显式状态机**：为什么"从数据反推状态"会随分支数指数级变脆；`flow_state` 本质是程序计数器（Program Counter）在业务层的对应物
2. **纯函数与副作用分离**：`decide_next(snapshot) -> action` 无 IO，因此可用一张表穷举所有分支组合来测试——这直接补上 CHARTER 已披露的"测试偏纯函数、不覆盖流程决策"缺口
3. **重构与功能变更的分离**：本模块**零功能变更**（规则一字不改），风险因此被限制在"等价性"上，验证方式是"改造前后同一输入产生同一决策"
4. **持久化粒度的取舍**：为什么只落"进度"不落"完整会话"——序列化的成本、字段演进的兼容负担、以及"半成品恢复"比"不恢复"更糟的风险
5. **Branch by Abstraction 的另一种形态**：先加新结构（FlowState），让新旧并存运行一段时间，确认无回归后再让新结构接管

---

## 4. 验证方式

1. `pytest tests/test_flow.py tests/test_session.py tests/test_report.py -q` 全绿
2. `tests/test_flow.py` 必须**穷举分支**：用参数化把 `FlowSnapshot` 的组合铺满，断言每个组合的 `decide_next` 输出与改造前的旧逻辑一致（等价性验证）
3. 冒烟：完整走一场面试，观察日志中 `flow_state` 的迁移序列是否符合预期；中途重启进程，确认报告页仍能显示已完成部分
4. `python run.py lint` 通过

---

## 修改记录

### 修改记录 2026-08-29（恢复能力边界的划定）

- **原方案**：研读报告 §6-P1-7 只写了"引入流程位置的显式持久化"，没有界定"持久化到什么程度"，容易被理解成"支持断点续答"。
- **问题本质**：`InterviewSession` 有 30+ 个可变字段（含 LLM 解析产物、注入历史、EMA 记忆、面试官切换历史），要支持"从 DB 重建并续答"，等价于给这个 1200 行对象写完整序列化层，且要处理字段演进的向后兼容。5 天工期内，做完这一个模块会挤掉 D1-D3，或者做出一个"能恢复但恢复出来状态不对"的半成品——后者的危害远大于不做（用户会信任一个错误的恢复结果）。
- **用户判断点**：用户要的是"更丰富饱满"，不是"用核心链路质量换功能数量"。一个能跑通的面试 + 准确的报告，比一个能断点续答但状态可能错乱的面试更重要。
- **修改后的方案**：明确只做"进度落库 + 状态可观测"，把"断点续答"写进 §1.3 非目标，并在 README 已知局限中披露。判断依据是 Gua 的正反两面经验：它做了完整 checkpoint，但也因此背上了序列化类型登记表与双链路漂移的维护债。
