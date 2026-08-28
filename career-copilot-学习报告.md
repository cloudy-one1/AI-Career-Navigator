# career-copilot 深度学习报告

> 仓库：https://github.com/peeker-tao/career-copilot
> 定位：AI 职业陪练平台（模拟面试 + 简历诊断 + 职业规划 + 语音 + RAG）
> 技术栈：React + NestJS + Prisma/PostgreSQL + Redis
> 对比参照：本项目「AI模拟面试官」(原生前端 + FastAPI + SQLite + 多 AI 后端)

---

## 一、项目定位与核心能力

这是与本项目高度对标的竞品，功能重叠度很高：

| 能力 | career-copilot | 本项目 |
|---|---|---|
| 模拟面试 | 5-8 轮，WebSocket 实时 | WebSocket 实时 + 多模式切换(v5.0) |
| 评分诊断 | 多维度 JSON | STAR/量化/逻辑/相关性/深度(v3+) |
| 简历解析 | NER + AI 评估 | resume_parser + retriever(v5.0) |
| 职业规划 | 技能差距 + 路线图 | 时间轴多阶段路径(v3.2) |
| 市场数据 | 模板话术(未接实时) | Playwright 实时采集(v4.1) |
| 语音 | HTTP 模式 ASR/TTS(DashScope 兜底 OpenAI) | MiMo 云端语音(v4.2) |
| 流式输出 | Gateway 逐句"模拟"流式 | 真实流式 |

关键差异：对方大而全(还含岗位匹配、学习资源、管理后台、认证)，但市场数据是假的；本项目市场数据是真采集的，模块更聚焦。

---

## 二、架构设计（可借鉴点）

### 2.1 LLM Provider 抽象层（最值得借鉴）

统一"接口 + 工厂 + 注册表"模式，零侵入切换模型：

- 接口 `LLMProvider`：`chat()` 返回 `Promise<string>`；`chatStream()` 返回 `AsyncIterable<string>`。
- `PROVIDER_REGISTRY`：集中配置 OpenAI / 通义千问 DashScope / DeepSeek 的默认模型与 baseURL。
- 工厂 `createProvider` 优先级：显式 `LLM_PROVIDER` 环境变量 > 自动探测 `OPENAI_API_KEY`→`DASHSCOPE_API_KEY`→`DEEPSEEK_API_KEY` > 兜底 OpenAI + 告警。
- 关键技巧：无论选哪家，最终都实例化为 `OpenAICompatibleProvider`（通义千问、DeepSeek 均兼容 OpenAI 协议，仅换 baseURL+model）。
- `OpenAICompatibleProvider`：timeout 60s、maxRetries 2、支持 `AbortSignal` 中断、空响应抛 `[name] LLM 返回为空`。

对比本项目：`backend/llm_client.py` 已是多后端+优雅降级(v4.3 fallback)，方向一致。对方"注册表"式扩展写法更显式，可参考。

### 2.2 AI 服务统一编排（ai.service.ts）

`AiService` 是 LLM 调用的唯一收敛点，所有业务 `provider.chat()` 都经 `safeJsonParse`：

- 缓存：`@Optional() AiCacheService`，`callLLM` 接受 `cachePrefix`，读写均 try-catch 容错，失败仅告警。
- RAG 增强：`callLLM` 支持 `ragNamespace`，注入 `SimpleRagService` 时调用 `augmentCall` 改写 System Prompt（日志"RAG 增强已应用"）。
- JSON 容错四级降级（最值得抄）：直接解析 → 正则提取 `{...}` → `repairMalformedJson` 字符级修复(未转义引号/换行/截断补括号) → 宽松解析(去尾逗号/单引号转双引号/undefined转null)。
- 错误重试编排：`parseResume` 首次解析失败，构造"助手认错+用户指正"多轮消息重试(温度降到 0.2)。

### 2.3 WebSocket 面试状态机（interview.gateway.ts）

协议清晰，状态机完整：

- C→S：`user_answer { interviewId, content }`
- S→C：`ai_message_chunk { messageId, chunk }` → `ai_message_done { messageId, fullContent, feedback, isFollowUp, nextAction, score, ... }` → `error { code, message }`
- 流程：收答案 → `evaluateAndContinue` → 存库(assistant 题/追问文本+questionType+referenceAnswer) → 按 `isFollowUp`/`nextAction` 决定追问或下一题 → 若 `complete` 置 `completed` 并写总分 → 逐句正则切割 `/[。！？.!?]/` 加 50ms 延迟"模拟流式" → 下发 `ai_message_done`。
- 评分双写：逐题反馈写 `interviewMessage`；总分写 `interview`。

对比本项目：你们有真实流式(v4.2 语音也走流式)。对方一个可借鉴点是"追问/下一题/结束"三态 `nextAction` 由 LLM 同一次调用产出（与评分一起），减少往返。

### 2.4 面试 Prompt 设计（interview.system.ts / interview.feedback.ts）

系统提示词工程质量高，可直接参考优化本项目出题/评分：

出题 System Prompt 规则：
1. 角色：资深 `{position}` 面试官，只出题评估不替答。
2. 轮次：5-8 轮；每轮 出题→回答→评分并决定 追问/下一题/结束。
3. 自适应：答好深入追问，答差换方向。
4. 追问限制：避免连续追问超过 2 次。
5. 难度适配：easy/mid/hard 对应基础题/综合题/原理+系统设计题。
6. 简历上下文可选注入。
7. 强制纯 JSON 输出(无 markdown 块)，两种结构：`question` / `evaluation`。

评估 JSON 结构：`score(0-100)`、`feedback`、`strengths`(≤2)、`weaknesses`(≤2)、`isFollowUp`、`nextAction`(followUp/nextQuestion/complete)、`followUpContent`、`nextQuestion`、`nextQuestionReferenceAnswer`、`summary`。题型 `technical|behavioral|project`。

反馈报告(面试结束)：5 维度评分(专业技能/项目经验/沟通表达/逻辑思维/学习能力 各 0-100)、逐题 1-5 分、S/A/B/C/D 等级(≥90/80/70/60)、100-200 字综合评语、带优先级(high/medium/low)的学习建议。

对比本项目：你们的 `dimension_weights` + `diagnosis_engine` 是规则化多维度诊断，更强可调；但对方"追问≤2次、5-8轮、难度映射表"这些 Prompt 约束很值得补进本项目出题 Prompt。

### 2.5 RAG（simple-rag.service.ts + local-embedder.service.ts）

轻量方案：本地 Embedding(BGE-Small-ZH via Python Worker) + Redis 存储 + 应用层计算。

- 命名空间隔离：`rag:interview` / `rag:career` / `rag:resume`。
- 检索：查询向量 → 从 Redis 取命名空间下所有 `vec:*` → 应用层 `cosineSimilarity` 排序 → Top-K(默认3)。
- 增强：`augmentCall` 把检索结果拼成 `【参考知识库相关内容】` 块注入 System Prompt（仅返回增强后字符串，不在此发 LLM）。
- 存储：JSON `{content, metadata, vector}` 存 Redis，TTL 7 天，ZSet 维护键名。

对比本项目：`resume_retriever`(v5.0) 是简历证据检索。对方可借鉴其"命名空间隔离+应用层余弦相似度"的极简 RAG 实现（适合小规模原型）。

### 2.6 语音服务（voice.service.ts）

HTTP 请求-响应模式（非 WebSocket 实时流）：

- ASR：优先 DashScope Paraformer v2 异步文件识别(取 OSS 凭证→上传→提交任务→轮询≤60次/2s→提取文本)；兜底 OpenAI Whisper-1(lang=zh)。
- TTS：优先 DashScope CosyVoice(`cosyvoice-v3-flash`)，`DASHSCOPE_VOICE_MAP` 把 OpenAI 音色(alloy/echo)映射为阿里云音色；兜底 OpenAI tts-1 写本地 `uploads/audio`。
- 依赖：`DASHSCOPE_API_KEY/BASE_URL/WORKSPACE_ID` 优先，OpenAI 兜底。

对比本项目：你们 v4.2 用小米 MiMo 云端语音(按官方 chat/completions 协议，域名 api.xiaomimimo.com)。对方"多厂商兜底"思路一致，但"语音音色映射表"是可借鉴的小技巧。

### 2.7 职业规划引擎（career.planner.ts）

`CareerPlanner` 是 AI 结果格式化中间件：

- 技能差距：`raw.gapAnalysis` 的 `missingSkills`+`recommendedSkills` 用 `Set` 去重合并为 `gapSkills`。
- 路线图：映射为 `RoadmapPhase[]`（phase/title/goal/skills/estimatedWeeks/resources）；`parseWeeks` 正则提取数字，"月"×4、"周"直取、默认4周；milestones 拼成时间线。
- 市场洞察：`estimateMarketDemand` 仅是岗位名模板话术（未接实时数据）。

对比本项目：你们 v3.2 时间轴多阶段路径更结构化；对方 `parseWeeks` 周期解析可参考。

### 2.8 数据模型（Prisma / PostgreSQL）

以 User 为中心辐射：`User 1—N Resume/Interview/CareerPlan/JobMatch/...`，`Resume 1—N Interview(resumeId 可空, onDelete SetNull)`，`Interview 1—N InterviewMessage(Cascade)`。广泛用 `Json` 存非结构化(AI评估/路线图/反馈)，`@map("snake_case")` 映射，高频字段建 `@@index`。还有 `PasswordResetToken`/`ResumeBookmark`/`ScreeningBenchmark`/`QuestionBank`/`LearningResource` 等。

对比本项目：你们用 SQLite(aiosqlite)，JSON 存诊断结果。对方关系建模更完整(级联删除策略、唯一约束防重复收藏)。

---

## 三、可借鉴清单（落到本项目）

1. **Prompt 约束补强**：出题 Prompt 增加"5-8 轮 / 追问≤2 次 / easy-mid-hard 难度映射 / 题型 technical|behavioral|project"等硬约束 → 提升本项目 `question_gen`/`diagnosis_engine` 稳定性。
2. **评分同轮决策**：把"追问/下一题/结束 nextAction"与逐题评分合并为一次 LLM 调用（对方 `evaluateAndContinue`），减少 WebSocket 往返。
3. **JSON 容错四级降级**：移植 `safeJsonParse` 思路到本项目 JSON 解析（当前 backend 解析 LLM 输出偶有脆弱）。
4. **Provider 注册表**：把多后端配置改为"注册表+工厂+自动探测 Key"模式，比散落的 if/else 更易扩展。
5. **命名空间 RAG**：若要做通用知识库，参考其 `rag:interview/career/resume` 命名空间隔离 + 应用层余弦相似度极简实现。
6. **语音音色映射表**：多厂商 TTS 切换时统一音色参数。

## 四、对方不足（本项目相对优势）

- 市场数据纯模板话术，无实时采集（本项目 v4.1 Playwright 实时采集是硬优势）。
- `ai.service.ts` 无真实流式（仅在 Gateway 模拟）；本项目真实流式更优。
- 语音是 HTTP 模式，无 WebSocket 实时对话流（本项目 MiMo 云端支持实时交互）。
- 职业规划市场洞察未接数据、RAG 相似度在应用层计算（大规模性能弱）。

---

## 五、总结

career-copilot 是一份高质量的对标参考：其 LLM Provider 抽象、Prompt 工程、JSON 容错、WebSocket 面试状态机、极简 RAG 都值得本项目借鉴；但在市场数据实时性、真实流式、语音实时性上本项目已领先。建议优先落地第三节的 1/2/3 项（低成本、高收益）。
