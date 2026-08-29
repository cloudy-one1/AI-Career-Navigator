# MockFlow AI 深度研读报告

> 来源：`https://github.com/yilun123456/mockflow-ai-interview`（2★，**仅 2 个 commit**，无 LICENSE 文件）
> 定位：**多模态演示型全栈 MVP** —— React 19 单文件前端 + 双运行模式（无 Key 确定性 Demo API / 可选 FastAPI+LangGraph Agent API）
> 研读范围：全部源码（前端 `app/page.tsx` 约 40KB + 2 个 route handler；后端 Python 合计约 14KB：`graph.py` / `retrieval.py` / `scoring.py` / `main.py` / `models.py` / `memory.py` + 2 个测试用例）
> 研读日期：2026-08-29　对照基线：本项目 v6.3

---

## 0. 一句话结论

这是一个**为求职作品集精心设计叙事、但引擎全部是确定性模板**的项目：README 里写的 LangGraph 编排、混合 RAG、滑动窗口 Memory、多模态信号**都有代码存在**，但逐行读完会发现——图是真的，节点是模板；检索是真的，语料只有 4 条；Memory 在写入，从没人读；关键帧在采集，从没被上传。

**对我们的价值分两层**：第一层是**「无 Key 可完整演示」的双运行模式**（同一协议、两套引擎），这是我们从 v4.3 到 v6.3 始终没有的能力——目前没配 LLM Key 时连测试收集都会失败；第二层是若干低成本借鉴（bigram 语义近似检索通道、出题依据实时透出）。而它的**报告页大面积造假**（假历史、假百分位、假趋势）恰好是我们「诚实披露」文化的反面教材。

---

## 1. 形态对比：同一个命题，两种解法

| 维度 | MockFlow AI | 本项目 v6.3 |
|---|---|---|
| 形态 | Next.js/React 19 前端 + 可选 FastAPI 后端，双运行模式 | FastAPI + WebSocket 单体，前后端分离 SPA |
| 核心引擎 | **零 LLM**：全部正则 / 模板 / 查表（Demo 模式与 Agent 模式均无 LLM 调用） | LLM 驱动（多 Provider），诊断/出题/改写全链路 |
| 编排 | LangGraph `StateGraph`（3 分支 + 1 条件边） | `session.py` 过程式状态机（轮次计数 + 收尾强控） |
| 持久化 | 无（Memory 是进程内 deque，且从未被读取） | SQLite（会话/题目/诊断/报告/薄弱点长期记忆） |
| 评分 | 正则 Rubric，**分数下限夹紧到 58** | 五维 LLM 评分 + 规则化加减分项（带 evidence）+ 封顶夹紧 |
| 追问 | 每题固定 1 次（`isFollowUp` 布尔），触发条件 `missing>=2 或长度<60` | 薄弱维度驱动 + 角色追问链 + `FOLLOW_UP_MAX_COUNT` + 恢复阈值 |
| 语音 | 浏览器原生 Web Speech（TTS 播报 + ASR 转写） | MiMo 云端 TTS/ASR + 浏览器原生降级（v4.2） |
| 视频 | 摄像头预览 + 能量表 + 关键帧计数（**帧不上传、不参与任何逻辑**） | 无视频（语音是输入/输出替代层，CHARTER 定位） |
| 出题 | 4 道固定题按 `round % 4` 轮转 | LLM 生成 + 锚点五分类 + JD gap 优先级 + 压力题库 + 去重 |
| 测试 | 2 个 unittest 用例 | 559+ 用例 pytest + import-linter 分层契约 |
| 报告 | **真实数据不足时用硬编码样例兜底**，历史页/百分位/趋势全部假数据 | 全量真实数据 + 逐题拆解 + HTML 导出 + assisted 披露 |
| 交付目标 | 求职作品集（README 自带「面试时怎么讲」「简历描述」章节） | 课程项目（答辩 + 诊断内核质量） |

**判定**：领域同构，工程深度全面弱于我们，但**「演示可用性」的产品思维强于我们**——它认真回答了「评委/面试官打开项目时，没有 Key、没有网络、没有数据，能不能 3 分钟看到完整闭环」这个问题。我们没有。

---

## 2. 架构解剖：双运行模式（最值得学的一件事）

### 2.1 目录结构

```
mockflow-ai-interview/
├── app/                        # 前端 + Demo API（Next.js App Router）
│   ├── page.tsx                # 单文件 40KB：6 个视图 + 全部状态机 + 多模态采集
│   ├── api/analyze/route.ts    # 确定性 JD/简历分析（正则技能匹配）
│   └── api/evaluate/route.ts   # 确定性四维评分（正则 Rubric）
├── backend/                    # 可选 Agent API（FastAPI + LangGraph）
│   ├── app/
│   │   ├── agent/graph.py      # StateGraph：analyze / question / evaluate 三分支
│   │   ├── retrieval.py        # 无依赖混合召回（bigram 余弦 + 稀疏命中 + rerank）
│   │   ├── scoring.py          # 与 route.ts 逻辑几乎相同的评分（重复实现！）
│   │   ├── main.py             # 3 个端点：/v1/analyze /v1/evaluate /v1/interview/next
│   │   ├── models.py           # Pydantic Field 约束（min/max length、pattern 枚举）
│   │   └── memory.py           # 8 轮 deque 滑动窗口（写入了但从未读取）
│   └── tests/test_scoring.py   # 全项目唯一测试文件，2 个用例
└── .openai/hosting.json        # OpenAI Sites 部署配置
```

### 2.2 双模式的实现方式

前端只用一个环境变量切换引擎，**协议不变**：

```ts
const agentApiBase = process.env.NEXT_PUBLIC_AGENT_API_URL?.replace(/\/$/, "") ?? "";
const agentEndpoint = (name: "analyze" | "evaluate") =>
  agentApiBase ? `${agentApiBase}/v1/${name}` : `/api/${name}`;
```

- 留空 → 走 Next.js serverless route（确定性，无 Key 可跑）；
- 配置 → 走 FastAPI + LangGraph（同样确定性，但换上了「图」的架构）。

更关键的是**三级兜底**：API 失败 → 前端再兜一层。`analyzeJob()` fetch 失败时直接用本地硬编码的 `FALLBACK_ANALYSIS` 继续渲染；`submitAnswer()` 失败时用一组固定分数继续流程。**无论发生什么，演示都不会中断**——这对课程答辩场景极有参考价值。

### 2.3 对照我们的现状

我们的「优雅降级」（v4.3）是 **Provider 间降级**（DeepSeek 挂了换 Qwen），前提是至少有一个 Provider 的 Key。`llm_client.py` 模块级实例化意味着**零 Key 时整个后端 import 即失败**，连 pytest 全量收集都不行（CHARTER 测试策略已披露此局限）。

而我们其实**已经握有搭建确定性演示引擎的全部零件**：

| 演示链路环节 | 现成零件（均为确定性、零 LLM） |
|---|---|
| 出题 | `question_bank`（题库）+ `pressure_bank`（16 道压力题）+ `resume_anchors.classify()`（关键词分类）+ `jd_gaps`（可改规则计算） |
| 诊断 | `score_adjustments`（10 条正则规则，带 evidence）+ `resume_retriever`（证据命中） |
| 追问 | 角色卡 `followup_chain`（纯数据）+ 薄弱维度（规则分最低维度） |
| 报告 | 真实数据库数据 + `assistance_stats` |

> **P1 建议**：增加 `DEMO_MODE`（或「无 Key 自动进入」）运行档：`llm_client` 延迟实例化/可选实例化，演示模式下出题走「锚点分类 → 题库选取 → 压力题闸门」确定性管道，诊断走 `score_adjustments` 规则评分。协议（WebSocket 消息格式）与 LLM 模式完全一致。收益：① 答辩/演示不再依赖 Key 与网络；② 全量测试收集不再因无 Key 失败；③ 与 v4.3 降级链自然衔接（Provider 降级 → 演示模式降级为最后一级）。
>
> ⚠️ 这是新增功能模块，按 CHARTER 范围纪律**须用户批准后才实施**。工程量主要在 `llm_client` 的可选化与 `question_gen`/`diagnosis_engine` 的分支注入，量级中等偏大，建议作为 v6.4 首选议题评估。

---

## 3. LangGraph 图解剖：图是真的，节点是模板

### 3.1 图结构

```
START ──条件边──▶ retrieve_profile ──▶ build_profile ──▶ END      (analyze)
              ──▶ retrieve_answer ──▶ score_answer ──条件边──▶ write_follow_up ──▶ END   (evaluate)
              ──▶ retrieve_question ──▶ draft_question ──▶ END  (question)
```

条件边只有一个：`route_evaluation` 依据评分结果里的 `needsFollowUp` 决定是否进入 `write_follow_up` 节点。`InterviewState` 是 `TypedDict(total=False)`，三种模式共用一个状态类。

### 3.2 逐节点的真实面目

| 节点 | README 宣称 | 代码实际 |
|---|---|---|
| `build_profile` | 能力建模 | 9 条技能正则匹配 JD/简历 → coverage 算匹配分，能力权重**硬编码** 30/25/25/20 |
| `score_answer` | 四维评估 | `scoring.py` 正则 Rubric（见 §4） |
| `write_follow_up` | 定向追问 | 模板句拼接：`f"再追问一步：请只围绕{missing[:2]}，补充一个你亲自做出的取舍和可验证结果。"` |
| `draft_question` | 个性化出题 | **4 道写死的题按 `round_index % 4` 轮转**，与检索结果无关 |
| `retrieve_*` | RAG 证据召回 | 真实执行，但语料只有 4 条知识 + 简历切片 |

### 3.3 评价与立场

- **编排骨架值得肯定**：三分支入口 + 条件边 + 共享状态类，把「面试是带状态的循环」表达得很清楚，README 的答辩话术（"条件边比线性 Chain 更适合表达动态流程"）本身是对的。
- **但我们不抄**。理由：① 我们的状态机（轮次计数、收尾强控、恢复阈值、压力题闸门）控制流远比它复杂，迁到 LangGraph 是纯重写无收益；② 过程式控制流 + 559 用例的可测试性是我们的优势，引入图框架反而把强控逻辑藏进节点内部；③ 它的图之所以显得优雅，恰恰因为节点里什么都没有。
- **可取走的是叙事而非代码**：答辩时可借用「出题—评估—追问—结束是一个带条件边的循环，而非线性 Chain」这个表述框架来解释我们 `session.py` 的设计动机。

---

## 4. 评分层解剖：可解释 Rubric 的极简版 + 一个危险设计

### 4.1 Rubric 本体（`scoring.py`）

```python
has_decision  = re.search(r"判断|选择|取舍|因为|所以|决定|优先", answer)
has_action    = re.search(r"负责|推动|设计|验证|拆分|建立|上线|优化", answer)
has_result    = re.search(r"结果|提升|降低|增长|达到|完成|上线|指标", answer)
content   = clamp(62 + length_score + (7 if has_action else 0) + (7 if has_result else 0))
logic     = clamp(64 + (10 if has_decision else 0) + (7 if has_numbers else 0) + min(10, 分句数))
missing   = [维度 for 检测失败时]        # 驱动追问
needsFollowUp = len(missing) >= 2 or len(answer) < 60
```

**优点**：完全可解释、可测试（它唯一的测试文件测的就是"具体回答得分 > 笼统回答"）、`missing` 直接驱动追问形成闭环。这与我们 v6.3 的 `score_adjustments` 思路同源，但它是**正命脉**（规则即评分本体），我们是**辅助层**（规则修正 LLM 评分）——我们的结构信息量更大，不必动。

### 4.2 危险设计：`clamp` 的 58 分下限

```python
def clamp(value): return max(58, min(96, round(value)))
```

**任何回答都不可能低于 58 分**——哪怕一句空话也是 62~69。这是为演示观感服务的分数通胀：报告页永远体面，候选人得到的反馈永远"及格"。与之对照，我们的加减分项夹紧在 [1,5] 且 0 分表示未评分、`raw_dimensions` 与修正后分数并存可对照——**分数的诚实性是我们答辩的可辩护点，不要学它**。

### 4.3 重复实现问题（反面教材）

`route.ts` 与 `scoring.py` 是**同一套 Rubric 的两份手抄**，且已经漂移：TS 版 `relevance` 多一个 `role` 前两字命中 +3 的加分，Python 版没有。同一逻辑双写必然漂移——我们对照检查：`resume_anchors.classify()` 规则兜底与 `resume_parser` LLM 输出共享同一份分类定义，`pressure_bank` 的闸门参数全部收在 `config.py`，目前无此问题。**新增规则时保持"定义单点、多端引用"**即可。

---

## 5. 检索层解剖：零依赖混合召回（可直接借走的一段算法）

`HybridRetriever.search()` 三通道加权：

```
score = bigram余弦相似度 × 0.65        # 语义近似信号（中文按字符 bigram，英文按词）
      + min(1, 稀疏词命中数/3) × 0.27   # 关键词命中（查询侧预置领域词表）
      + 0.08（文档 source 出现在查询里时） # 轻量 rerank
```

中文处理：去非汉字取相邻双字（bigram），ASCII 词单独提取。切片：按 `[\n。；]` 切、≥12 字符保留。**全部零依赖**（只用 `math`/`re`/`collections`），README 明说"生产版可替换为 Embedding+BM25 而不改图节点"。

**对照我们**：`knowledge_store.retrieve()` 目前只有 `extract_terms` 关键词命中单通道（`_score_chunks`）。同义词/换说法召回是短板——比如知识块写"检索增强"，query 说"RAG 召回差"，词命中为 0。bigram 余弦能在零依赖前提下补一条近似通道（"检索增强"与"检索增强生成"共享大量 bigram）。

> **P2 建议**：在 `resume_retriever._score_chunks` / `knowledge_store` 评分中叠加第二通道：`score = 0.6×词命中 + 0.3×bigram余弦 + rerank 项`（权重与阈值进 `config.py`）。两处均属 L2（禁止依赖 L3/L4），纯算法改动，可各配 3-4 个单测（同义改写命中、无关块不命中）。注意与 `MAX_CONTEXT_CHARS` 预算逻辑解耦——bigram 只改**排序**，不改入选资格。

---

## 6. 多模态层解剖：真实采集、装饰性消费

### 6.1 它做了什么（前端工程本身是认真的）

- `getUserMedia` 摄像头+麦克风（1280×720 ideal、回声消除/降噪参数）、`track.enabled` 开关设备；
- Web Audio `AnalyserNode` 测能量，`frame % 5 === 0` 节流 setState（与我们 v6.2 的 VAD 节流同思路）；
- `SpeechRecognition`（zh-CN、continuous + interim）实时转写进 textarea，`speechSynthesis` 播报题干；
- Canvas 捕获 640×360 关键帧，带快门闪烁动画 + 帧计数 UI；
- 面试页常驻「MULTIMODAL SIGNALS」面板：麦克风能量 %、视频连接状态、上下文帧数。

### 6.2 逐项验证后的真相

| 宣称 | 真相 |
|---|---|
| "关键上下文帧" | `captureFrame()` 只 `setSnapshotCount(+1)` + 闪烁动画，**帧数据从未离开浏览器**，不参与评分、不上传、不存 |
| "实时音频能量"参与评估 | 能量值只渲染进度条，**不进任何请求** |
| "RAG memory" 徽章 | `memory.add()` 每次评估都在写，**全仓库没有任何一处 `memory.get()`** |
| "结合实时语音信号生成报告" | 报告只平均四维分数，多模态信号零参与 |

结论：**多模态是 UI 叙事，不是数据链路**。README 的「诚实边界」披露了 LLM/向量库/登录未实现，却没有披露"视觉/音频信号不参与任何下游逻辑"——在最重要的一条产品卖点上不诚实。

### 6.3 对照我们

- 我们的语音是**真链路**：MiMo ASR 转写文本 → 进入诊断内核；TTS 播报由后端代理。链路完整性优于它。
- 它有一样我们没有的东西：**视频维度的"在场感"设计**（摄像头预览 + 设备开关 + 能量表）。若未来要补"Omni 视频面试"，应记住它的教训：**采集的每一模态都必须有下游消费方**（至少进诊断 prompt 或落库），否则就是假的。这可以写进 CHARTER 作为未来的设计约束候选（仅建议，不实施）。
- 它的 ASR 实现有个可取细节：`onresult` 里用**启动时快照** `originalAnswer` 拼接，避免转写与手动输入互相覆盖；我们 `voice.js` 走 MediaRecorder 上传 MiMo，无此问题。

---

## 7. 报告与数据诚实性批判（本章是反面教材集）

| 行为 | 代码证据 | 为什么危险 |
|---|---|---|
| 报告数据兜底造假 | `reportTranscript = transcript.length ? transcript : SAMPLE_TRANSCRIPT` | 没做过题也能看到一份"示例报告"，演示与真实数据混流 |
| 假百分位 | 硬编码"超过 MockFlow 中 **76%** 的同岗位候选人" | 无任何统计基础，写在报告正里 |
| 假趋势 | 硬编码"↗ 较上次 **+6**" | 历史根本不持久化，"上次"不存在 |
| 假历史页 | 12 场、平均 81 分、累计 4.6 小时全部硬编码 | 侧边栏"本周目标 1/3 场"同样写死 |
| 假结论 | AI Verdict、Strong Yes、优劣势清单全部硬编码，与实际回答无关 | 报告的"结论部分"与"数据部分"脱钩 |
| 分数下限 | `clamp` 下限 58 | 负反馈被系统性抹除 |

**对照我们**：v6.0 起我们就把"不再使用夸大定性"写进 CHARTER，报告全部来自 SQLite 真实数据，`assisted` 标记、`raw_dimensions` 透明披露。**这一章的价值是确认我们的方向**：它的报告页演示效果好，但每一个假数字在答辩追问"这个 76% 怎么来的"时都会变成负分。诚实披露是我们对这类作品集项目的**结构性优势**，答辩时值得主动对比。

---

## 8. 差距矩阵总览

| 能力 | MockFlow | 本项目 v6.3 | 判定 |
|---|---|---|---|
| 无 Key 完整演示 | 双运行模式 + 前端三级兜底 | 无（零 Key 后端不可用，测试收集失败） | **差距：演示可用性** |
| 出题 | 4 题轮转模板 | LLM + 锚点五分类 + JD gap 优先级 + 压力题 + 去重 | 我们远强 |
| 诊断评分 | 正则 Rubric（下限 58） | LLM 五维 + 规则加减分（evidence）+ 封顶 | 我们远强 |
| 追问 | 每题固定 1 次 | 角色范式 × 薄弱维度 + 恢复阈值 + 收尾强控 | 我们远强 |
| 检索 | bigram 余弦 + 稀疏 + rerank（零依赖） | 词命中单通道 + 命名空间 + 指纹去重 | **它多一条语义近似通道，可借** |
| 编排 | LangGraph 图（节点为模板） | 过程式状态机（控制流复杂且全被测试覆盖） | 我们强，叙事可借 |
| 语音 | 浏览器原生 | MiMo 云端 + 原生降级 | 我们强 |
| 视频在场感 | 摄像头/设备开关/能量/帧（不参与逻辑） | 无 | 形态差距，暂不追（真做须接下游） |
| Memory | 写入不读取（装饰） | 薄弱点跨轮累计（v5.0）+ 知识注入指纹去重 | 我们远强 |
| 报告 | 真数据不足即假数据兜底 | 全真 + assisted 披露 + 逐题拆解 | 我们强 |
| 输入校验 | Pydantic Field 约束齐全 | `schemas.py` 同等能力 | 持平 |
| 持久化 | 无 | SQLite | 我们强 |
| 测试 | 2 例 | 559+ 例 + 分层契约 | 我们碾压 |
| 出题依据实时透出 | 面试中"本题依据"chip | 仅报告页有前置追问点，**面试中无** | **可借（小改动）** |

---

## 9. 不应照抄的部分（批判性审视）

| 点 | 问题 | 我们的处理 |
|---|---|---|
| 假数据兜底报告/历史 | 演示与真实混流，追问即穿帮 | 保持真实数据；演示场景用"演示模式"明示身份，而非伪造数据 |
| `clamp` 58 分下限 | 负反馈系统性消失 | 保持 [1,5] 夹紧 + raw/adjusted 并存 |
| TS/Py 双写评分逻辑 | 已漂移（role 加分只在 TS 版） | 定义单点、多端引用 |
| 单文件 40KB `page.tsx` | 6 个视图 + 全部采集逻辑塞一个组件，不可测不可维护 | 保持模块化 SPA |
| Memory 只写不读 | "滑动窗口"名存实亡 | 我们的记忆必须被下游消费（薄弱点记忆已闭环） |
| 帧采集无消费方 | 多模态叙事无数据链路 | 未来做视频必须先定义下游（prompt 注入或落库） |
| 2 commits / 无 LICENSE | 一次性生成上传，无迭代史 | 不影响我们，但"2 个 commit 的 2★ 仓库"本身提示其成熟度 |

---

## 10. 落地建议（v6.4 候选清单，按性价比排序）

| 优先级 | 改动 | 涉及文件 | 改动量 | 预期收益 |
|---|---|---|---|---|
| **P1-1** | 演示模式（无 Key 全链路确定性降级）：`llm_client` 可选化 + 出题走"锚点→题库→压力闸门"管道 + 诊断走规则评分，协议不变 | `config.py`、`llm_client.py`、`question_gen.py`、`diagnosis_engine.py`（或新增 `demo_engine.py`） | **大** | 答辩/演示不依赖 Key 与网络；全量测试无 Key 可收集。**须用户批准（范围纪律）** |
| **P2-1** | 检索叠加 bigram 余弦近似通道（词命中 + bigram 双通道加权） | `resume_retriever.py`、`knowledge_store.py`、`config.py` | 小 | 同义/改写召回提升，零依赖 |
| **P2-2** | 出题依据实时透出：题目 payload 带来源标签（JD gap / 锚点类 / 压力题），前端面试页渲染"本题依据"chip | `interview_engine/session.py`、`main.py`、`frontend/src/js/interview.js` | 小 | 顺带解决 v6.3 遗留项"压力题前端未渲染标签"；呼应它 README 里"把检索依据展示给用户，减少凭空追问" |
| **P3-1** | 回答引导小 UX：建议字数提示、Ctrl/Cmd+Enter 提交（视前端现状择需） | `frontend/src/js/interview.js` | 极小 | 交互细节 |
| **不做** | LangGraph 迁移、视频面试、假数据兜底、分数下限 | — | — | 见 §8/§9 |

**分层约束提醒**：P2-1 改动均在 L2 内部，改后跑 `python run.py lint`；P2-2 涉及 L4→前端协议字段新增，向后兼容（旧会话无标签字段时前端不渲染）。

---

## 11. 三句话总结

1. **它最值钱的不是代码，是「无 Key 可完整演示」的产品思维** —— 三级兜底（确定性 API → 前端本地兜底 → 永不中断流程）保证任何人任何时刻打开都能看到完整闭环；我们的引擎质量远高于它，但演示可用性是空白，且我们已握有搭建确定性演示引擎的全部零件。
2. **它的多模态与报告是精心包装的空转** —— 帧、能量、Memory 都有真实采集/写入，但零下游消费；报告用假百分位、假趋势、假历史撑场面。逐行验证后，README 的叙事与代码现实的差距本身就是最好的批判性思维素材。
3. **今天就值得动手的两件小事**：给检索补一条零依赖的 bigram 语义近似通道（弥补同义改写召回短板），以及把出题依据实时透出到面试页（顺带清掉压力题标签这个遗留项）。演示模式是大事，值得单独立项评估。

---

## 12. 落地状态（2026-08-29 更新）

P2 两项已落地；P1-1（演示模式）完成方案评估待批准，详见 [演示模式方案评估.md](演示模式方案评估.md)。

| 项 | 落地位置 | 与本文档建议的偏差 |
|---|---|---|
| P2-1 bigram 语义近似通道 | `resume_retriever.bigram_tokens/bigram_cosine`（L2 单点）+ `_score_chunks` 双通道；`knowledge_store.retrieve` 同步受益；`config.RETRIEVAL_SEMANTIC_*` 三个参数 | **偏差**：入选门槛从"固定阈值 0.35"改为"绝对下限 0.12 + 相对最高相似度 0.8 比例"双闸——我们的块头最长 800 字、回答数百字，余弦相似度被长度稀释（相关文本实测仅 0.1~0.3），固定阈值永不触发。这是 MockFlow 语料（一行式短文档）与我们语料（长文档块）的量级差异倒逼的设计修正 |
| P2-2 出题依据实时透出 | `session.question_basis()` 确定性拼装（特殊题>薄弱维度>JD 缺口>锚点）；`main.py` WS payload 带 `basis` 字段；`interview.js` 渲染"📌 本题依据"chip + `style.css` 样式 | **发现**：v6.3 遗留项"压力题前端未渲染标签"实际已在 `interview.js` 解决（`pressure-badge` 徽章已存在），CHANGELOG 记录过时；本轮仅补 `basis` chip。**刻意不用 LLM 自报依据**——压力/破冰/补强/缺口都是工程侧已知事实，确定性拼装才不会编造 |
| P1-1 演示模式 | 未实施；三方案对比 + 分期建议（B 先行解除测试 Key 依赖，A 立项 v6.5）见评估文档 | 按 CHARTER 范围纪律，待用户批准 |

**新增测试**：`tests/test_semantic_retrieval.py`（16 例）+ `tests/test_question_basis.py`（15 例），受影响既有测试（borrowings/retriever/knowledge_store）83 例全绿，`run.py lint` 分层契约通过。
