# agent-interview-coach 改进方案（对标落地）

> 依据：《agent-interview-coach-对标分析.md》第 5 节"可借鉴点排序"
> 范围：仅**规划**（本次不实现），给出落到具体模块/文件/函数级的可执行改动清单
> 原则：复用现有 `llm_client` / `logger` / `schemas` / `db`，不新造基础设施；遵守 `.importlinter` 分层契约（L2 不依赖 L3/L4）；不破坏现有 291 用例

---

## 0. 目标能力矩阵（对应对比表优先级）

| 优先级 | 能力 | 落地位置 |
|---|---|---|
| P0 | 证据包 + 证据硬规则 + 轻量本地 RAG | backend 新增 `resume_retriever.py`（L2）+ `diagnosis_engine.py` 注入 |
| P0 | 不会答恢复 | `interview_engine/session.py` + `diagnosis_engine.py` |
| P1 | 多模式协议完善（拷打/只面试 + 运行中切换） | `schemas.py` + `interview_engine/session.py` + `main.py` + 前端 |
| P1 | 薄弱点跨轮累计 + 复盘/标准答案沉淀修复 | `interview_engine/session.py` + `report.py` |
| P2 | 强制结构化输出模板 | `diagnosis_engine.py` Prompt 对齐 |
| P3 | 微信端 | 不实施（仅标注为可选扩展） |

---

## 一、backend 改进方案

### 1.1 新增 `backend/resume_retriever.py`（L2 领域层，镜像 interview_corpus.py）

**定位**：在现有 `resume_parser.py`（纯文本抽取）之上，增加分块、文件名优先级、关键词检索、上下文预算、证据包组装。无向量库，符合本地优先约束。

```python
# 建议接口签名（模块级常量对齐 GitHub 项目参数）
CHUNK_SIZE = 2000            # 字符
CHUNK_OVERLAP = 250          # 重叠
MAX_CHARS_PER_FILE = 120_000 # 单文件截断
MAX_CONTEXT_CHUNKS = 4       # 最多选入块数
MAX_CONTEXT_CHARS = 6_000    # 证据包总字符预算
MAX_CHUNKS_PER_SOURCE = 2    # 单源最多块数
NOISY_NAME_PATTERNS = ("backup", "副本", "~$", "证件照")  # 噪声文件过滤
FILE_PRIORITY = {"ai面试背景材料": 98, "终极": 95, ...}    # 文件名优先级启发式

class ResumeRetriever:
    def __init__(self, resume_text: str, source_name: str = "简历"): ...
    def chunk_text(self) -> list[TextChunk]: ...        # 分块（含 overlap）
    def build_index(self) -> None: ...                  # 建立轻量索引（chunk 列表即可）
    def query_terms(self, text: str) -> list[str]: ...  # 正则 [\w\u4e00-\u9fff]{2,} 提取查询词
    def score_chunk(self, chunk, terms) -> float: ...   # priority + len(matched)*8，仅标题+前800字符内匹配
    def select_context(self, user_text: str) -> str: ...# 组装【本轮证据包】，受预算硬限
    def trace_retrieval(self, user_text: str) -> list[RetrievalTraceItem]: ...  # 溯源诊断（可选）
```

**关键点**：
- 证据包输出格式（对齐 GitHub，便于诊断与调试）：`【本轮证据包】来源=xxx 片段=#2 证据等级=高 ...`；无匹配时返回固定提示"本轮未检索到简历证据，请基于用户亲述追问"。
- **不落库**（面试会话内即用即建），避免引入新表；如需跨会话复用可缓存为内存 dict（session_id → index），不强求持久化。
- 分层：`resume_retriever` 仅依赖 `config`/`logger`（L1），被 L3 的 `diagnosis_engine` 调用，符合契约。

### 1.2 `backend/schemas.py`：新增枚举 + 修复字段不一致

```python
class InterviewMode(str, Enum):
    COACH = "coach"            # 教练模式：先补基础再追问，不输出分数
    TECHNICAL = "technical"    # 技术面模式：标准面试官（对应现有 simulation）
    TRADITIONAL = "traditional"  # 传统轮次（保留现有）
    HARDCORE = "hardcore"      # 拷打模式：高压抓名词堆砌/真实性漏洞
    INTERVIEW_ONLY = "interview_only"  # 只面试模式：仅一句反馈+一个追问

class InterviewStage(str, Enum):
    PHONE_SCREEN = "phone_screen"   # 电话筛选面
    TECH_ROUND_1 = "tech_round_1"   # 技术一面
    TECH_ROUND_2 = "tech_round_2"   # 技术二面/主管面
    HR = "hr"                       # HR面
```

- **修复缺陷**：`DiagnosisResult` 模型缺 `professional_depth` 字段，与引擎五维不一致 → 补上。
- `SessionCreateRequest.mode: str` 改为 `mode: InterviewMode = InterviewMode.TECHNICAL`（向后兼容：`coach` 保留）。
- 新增 `ModeSwitchRequest`（`session_id`, `mode`）供运行中切换端点使用。

### 1.3 `backend/diagnosis_engine.py`：证据注入 + 证据硬规则 + 模式化提示

**改动点（均在 Prompt 组装层，不动双 Agent 管线与流式骨架）**：

1. **新增常量**（放模块顶部，对齐 GitHub 语义）：
   ```python
   EVIDENCE_USE_HARD_RULES = """证据使用硬规则：
   1. 你只能依据【本轮证据包】或候选人本轮亲述来生成/评价项目经历；
   2. 大模型常识仅用于解释概念，严禁编造候选人经历；
   3. 证据包不足以支撑某个追问点时，应显式追问澄清，不要顺着候选人口述编造细节。"""
   COACHING_RECOVERY_INSTRUCTION = """候选人表示不会/不懂/没思路时，进入恢复流程：
   1. 用通俗语言讲清概念核心；2. 给出项目表达骨架；3. 提醒简历未支撑处"不要硬说"；
   4. 只追一个降阶问题；5. 保留【薄弱点】记录。"""
   ```

2. **`run_diagnosis_streaming()` 增加两个可选入参**：`evidence_package: str = ""`、`mode: InterviewMode = TECHNICAL`、`recovery_requested: bool = False`：
   - `evidence_package` 非空时，追加到 `DIAGNOSTICIAN_USER_PROMPT` 的 `【本轮证据包】` 段，并追加 `EVIDENCE_USE_HARD_RULES`；
   - `mode == InterviewMode.HARDCORE` → 追加高压指令（优先抓名词堆砌、过度包装、项目真实性漏洞，语气更锐利）；
   - `mode == InterviewMode.INTERVIEW_ONLY` → 追加"只输出一句简短反馈 + 一个追问，不输出完整模板"；
   - `recovery_requested=True` → 追加 `COACHING_RECOVERY_INSTRUCTION`；
   - `mode == InterviewMode.COACH` → 沿用现有 coach 处理（先讲概念 + 不输出分数）。

3. **`normalize_result()` 扩展弱点标签输出**：从诊断结果中解析 `weakness_tags: list[str]`（对齐 GitHub 的 `WEAKNESS_KEYWORDS`：MCP / LangGraph / RAG / 向量数据库 / 项目真实性 / 量化缺失 等），供 session 跨轮累计。

4. **问题类型差异化评估保留**：`_QUESTION_TYPE_GUIDANCE` 与证据注入正交，不冲突。

### 1.4 `backend/interview_engine/session.py`：多模式状态 + 不会答恢复 + 薄弱点跨轮累计

1. **状态扩展**：
   - `self.mode: InterviewMode`（由字符串升级为枚举）；
   - `self.stage: InterviewStage`（默认 `PHONE_SCREEN`，配合现有 `current_round` 推进）；
   - `self.weakness_tags: list[str]`（跨轮累计，`round_weak_dimension()` 之外新增的标签聚合）；
   - `self.recovery_active: bool`。

2. **不会答恢复**：
   ```python
   UNCERTAIN_ANSWER_MARKERS = ("不会", "不懂", "没思路", "答不上来", "不知道", "不清楚", "没做过")
   def needs_recovery(self, answer: str) -> bool: ...
   ```
   在 `submit_answer()` / `generate_follow_up()` 中检测：命中 → 置 `recovery_active=True`，下一轮诊断传入 `recovery_requested=True`；同时可无声将 `mode` 保持（对齐 GitHub"卡住+求教自动切教练"语义，可提供 `auto_coach` 开关）。

3. **薄弱点跨轮累计**：
   ```python
   def accumulate_weaknesses(self, tags: list[str]) -> None:
       # 合并进 self.weakness_tags，去重 + 计数，供复盘与前端面板使用
   ```

### 1.5 `backend/interview_engine/report.py`：复盘/标准答案沉淀修复

**修复缺陷（审计发现）**：`generate_review_markdown()` 第三节"参考答案沉淀"遍历 `report.get("detailed_qa")` 但 `build_report` 未产出该字段 → **恒为空**。

**改动**：
1. `build_report()` 在每题诊断后，将 `rewritten_answer`（改写后的标准答案）+ `question_text` + `weakness_tags` 聚合进 `detailed_qa: list[dict]`；
2. `generate_review_markdown()` 保持读取逻辑不变即可自动填充；
3. 报告新增 `weakness_tag_summary: list[str]`（跨轮累计标签 top-N），对应前端薄弱点面板。

### 1.6 `backend/main.py`：运行中模式/阶段切换端点 + 恢复信号透传

1. 新增 `POST /api/interview/{session_id}/mode`（body: `ModeSwitchRequest`）→ 更新 session.mode，返回新模式说明（复用现有 `config.INTERVIEW_MODES` 文案扩展）；
2. 可选 `POST /api/interview/{session_id}/stage` → 切换阶段（清空当前轮历史，对齐 GitHub `开始[阶段]` 语义）；
3. WebSocket `ws_interview`：`answer` 消息处理时调用 `session.needs_recovery()` 并把 `recovery_requested` 传入 `run_diagnosis_streaming()`；`mode` 透传到流式调用。

### 1.7 测试与契约

- `tests/` 新增：`test_resume_retriever.py`（分块边界、预算截断、噪声过滤、优先级评分、无匹配回落）；
- `tests/test_diagnosis_engine.py` 补：证据包注入后 prompt 含硬规则、recovery 分支、INTERVIEW_ONLY 输出约束；
- `.importlinter` 契约检查：`resume_retriever` 仅依赖 L1，被 L3 调用；`python run.py lint` 必须通过；
- 全量 `python -m pytest tests/ -q` 保持 291+ 用例全绿。

---

## 二、frontend 改进方案

### 2.1 模式切换 UI（interview.js / index.html / app.js）

- 现有 `mode-selector` 三档（simulation/traditional/coach）扩展为五档：`simulation`(拟真)/`traditional`(传统)/`coach`(教练)/`hardcore`(拷打)/`interview_only`(只面试)；
- 会话中支持切换：新增"模式"下拉或快捷按钮，调用 `api.js` 新增的 `switchMode(sessionId, mode)` → `POST /api/interview/{id}/mode`；
- 会话状态区展示 `stage / mode` 组合态（如"技术一面 · 拷打"），复用现有会话信息渲染位置。

### 2.2 薄弱点面板（report.js / interview.js）

- 面试进行中：每轮诊断完成后，把返回的 `weakness_tags` 追加渲染到侧边"薄弱点"面板（累计、去重、计数、标签化展示）；
- 综合报告：`report.weakness_tag_summary` 展示跨轮累计薄弱点（现有 `report.weaknesses` 列表保留，两者合并展示）。

### 2.3 复盘导出（report.js 修复）

- 现有"📥 导出复盘文件"按钮已存在（`exportReview()` → `GET /api/reports/{id}/review`），**后端修复 `detailed_qa` 后该按钮输出的"参考答案沉淀"节自动补全**；
- 可选：增加"标准答案"一键复制（每题的 rewritten_answer），对齐 GitHub `/标准答案` 语义。

### 2.4 样式

- 新增模式徽章/薄弱点标签样式沿用 `frontend/src/css/` 现有设计语言（不引入新框架）。

---

## 三、实施顺序建议（按依赖排布）

| 步骤 | 内容 | 依赖 |
|---|---|---|
| 1 | `resume_retriever.py` + 单测（P0 基础） | 无 |
| 2 | `schemas.py` 枚举 + `DiagnosisResult` 补字段 | 无 |
| 3 | `diagnosis_engine` 证据/硬规则/恢复/模式注入（P0+P1 核心） | 1、2 |
| 4 | `session.py` 多模式状态 + 恢复 + 薄弱点累计 | 2、3 |
| 5 | `report.py` detailed_qa 聚合 + 标签汇总（P1 修复） | 3 |
| 6 | `main.py` 模式切换端点 + ws 透传 | 3、4 |
| 7 | frontend 五档模式 + 薄弱点面板 + 导出（复用按钮） | 6 |
| 8 | 回归：`run.py lint` + 全量 pytest | 全部 |

工作量粗估：P0（步骤 1-3）约为主体；P1（4-6）次之；P2（7）为 UI 层。

---

## 四、明确不做 / 边界

- **微信端集成不实施**（对标报告 6.1）：Web 架构下需新引入 wechat-clawbot 桥接，有账号封禁风险，且与现有前端生态割裂。仅保留为未来可选扩展项。
- **不引入向量库 / embedding 服务**：遵守"本地优先、零托管依赖"约束，轻量 RAG（关键词+优先级）作为第一版；若后续召回精度不足，再评估本地 embedding 方案。
- **不动双 Agent 流式管线**：证据/模式/恢复均为 Prompt 层正交注入，避免重构既有稳定逻辑。
- **不新增数据库表**：薄弱点累计为 session 内存态（对齐 GitHub 的 sessions.json 语义），落库仍走现有 `weakness_profile` 表。
