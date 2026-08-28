# GrillMind（智面）深度研读报告

> 来源：`https://github.com/1935417243/GrillMind`（MIT，9★，53 commits）
> 定位：Electron 跨平台桌面 App 的 AI 技术面试模拟器（上传简历 → 选岗位 → AI 面试官 → 文字/语音 → 评估报告）
> 研读范围：后端 6 大服务 + 3 套提示词 + SQLite schema + 语音全双工链路 + 前端面试间/语音组件

---

## 1. 技术栈与您项目（AI模拟面试官）对比

| 维度 | GrillMind | 您的项目 |
|---|---|---|
| 后端 | Node.js · Fastify 4 · better-sqlite3 | Python 3.12 · FastAPI · aiosqlite |
| 前端 | React 19 · Vite 8 · React Router 6 | 原生 ES Module SPA · Chart.js |
| 桌面端 | Electron · electron-builder · CI 自动构建 | 纯 Web（无桌面壳） |
| 语音 | 阿里百炼 ASR(Paraformer)+TTS(CosyVoice)，WebSocket 全双工 | 小米 MiMo 云端 TTS/ASR |
| 模型 | OpenAI 兼容协议，多供应商按任务绑定 | 多后端，AI_PROVIDER=auto 探测 |
| 评测 | 总评(10-100)·逐题拆解·风险点·建议 | STAR完整性/量化/逻辑/岗位相关/专业深度 + 职业规划 |

结论：领域同构，GrillMind 偏"产品化桌面 App"，您的偏"Web 服务平台"。其**面试状态机、Prompt 工程、语音全双工**最值得借鉴。

---

## 2. 后端架构（分层清晰）

```
backend/src/
├── index.js              # Fastify 入口，注册 routes + ws
├── ai/{client.js, prompts/}   # 多供应商封装 + 面试/报告/简历三套提示词
├── db/{schema.sql, init.js, index.js}
├── routes/               # interview/resume/jobPosition/report/model/voiceRoute
├── services/             # interviewEngine/modelManager/reportGenerator/resumeParser/voiceHandler
└── utils/                # crypto(AES)/fileUtils/time/interviewOutput
```

依赖方向：`routes → services → ai + db`，prompts 被 services 调用，无反向依赖。

---

## 3. 核心引擎：面试状态机（interviewEngine.js）—— 项目灵魂

### 3.1 阶段流转（配置驱动）
链路：`opening → intro → intro_followup → project_dive → basic_verify → closing`
按 `depth`（quick 10轮 / standard 20轮默认 / deep 30轮）配置每阶段 `minTurns/maxTurns/maxProjects`。

### 3.2 推进判定（三态逻辑）
- `turns < min` → 不推进（没聊够）
- 设了 `max` 且 `turns >= max` → 推进（聊够了）
- 达 `min` 且不限 `max` → 允许推进

### 3.3 项目深挖（project_dive 特殊态）
`advanceStage` 在 project_dive：若 `projectIndex < maxProjects-1` 则**只递增 projectIndex 并重置轮次**（同阶段换项目），否则流转下一阶段。`getCurrentProject()` 仅在该阶段返回 `parsed.projects[projectIndex]` 并注入 `deepDivePoints`。

### 3.4 工程化控制（值得抄）
- **持久化**：每次 `appendMessage` 后 `persist()` 写回 DB（messages/stage/project_index/stage_turns），断点可恢复。
- **收尾强控**：`closing` 阶段直接在用户消息末尾注入内部指令"严禁再提任何新问题…"，工程层强制收尾。
- **输出净化**：入库前 `sanitizeInterviewOutputText`；流式过程 `createInterviewOutputStreamSanitizer` 逐 token 过滤。

精髓：**阶段推进由轮次计数决定，而非 LLM 自决**——这是面试可控的关键。

---

## 4. Prompt 工程精华（三套提示词）

### 4.1 面试对话 buildInterviewSystemPrompt
按 `category`(tech/non-tech) 切角色。亮点规则（硬编码进 System Prompt 末尾）：
- 每次只问一个问题；回答太虚要举例子；有漏洞直接指出追问
- **禁止括号动作/心理活动**（如"（稍作等待）"）；**禁用 Markdown**（不加粗/列表/代码块）
- 禁止"好/好的/嗯/明白"垫词开头，直接追问；不向候选人暴露简历原文

三个可调旋钮：
- `difficulty`：normal（平和）/ pressure（快节奏不停追问）/ high（持续压迫）
- `focus`：mixed（综合）/ project（项目深挖为主）/ basic（基础原理为主）
- `stage`：精确约束该阶段意图（开场/自我介绍追问/项目深挖/基础验证/收尾）

### 4.2 简历解析 buildResumeParsePrompt
强制 JSON 输出（简体中文、禁 emoji、禁代码块）。关键字段：
- `yearsOfExperience / jobTendency / techStack`
- `projects[]`：含 `name/role/techUsed/responsibilities/**deepDivePoints**(追问点)/**vaguePoints**(模糊点)`
- `selfIntroHints`：自我介绍阶段面试官应重点关注的**具体内容方向**

洞察：简历解析不仅抽"是什么"，还预计算"该追问什么/哪里含糊"，把追问策略前置到解析阶段。

### 4.3 评估报告 buildReportPrompt
- 评分等级（10-100 整数）：卓越90 / 优秀80 / 良好70 / 合格60 / 不足40 / 较差20 / 极差10
- 强约束：完全无关内容给 10-15；极短敷衍给 10-20；**不得因"至少回答了"虚高**
- 报告 JSON 结构：`overallScore / summary / qaBreakdown[{question,answerSummary,issues[],suggestions[],realInterviewImpact}] / riskPoints[] / suggestions{nextPractice[],selfIntroImprovement,projectExpressionTips}`
- `extractQAPairs` 过滤 opening/closing 助手消息，计算 `thinkingSeconds`（用户作答时长，0-600s）。

---

## 5. 模型管理（modelManager.js + ai/client.js）

- **多供应商路由**：`provider::modelName` 格式（如 `deepseek::deepseek-v4-pro`），查 `model_providers` 表取加密 Key + base_url 动态实例化 OpenAI 客户端。超时 300s（适配长思考），`maxRetries:0`（重试上层管）。
- **任务-模型绑定**（单例表 `id='singleton'`）：parse/interview/report/base 各绑模型，外加 asr/tts/ttsVoice。`interview_thinking` 代码层**强制 0**（面试永远不开启深度思考，保证低延迟）。
- **供应商差异兼容**：原生 DeepSeek 才支持 `response_format: json_object`；DeepSeek v4-pro 用 `thinking{type,reasoning_effort}`，百炼用 `enable_thinking`；用 hostname 判定是否 `api.deepseek.com` 区分原生/百炼托管的 DeepSeek。
- **退避重试** `chatCompletionWithRetry`（默认 2 次）：401/403 不重试；429 按 `2000ms*(i+1)` 递增；5xx/网络错按 `1000ms*(i+1)`。
- **连接测试**：`client.models.list()` 拉模型列表并持久化 `is_connected`。

---

## 6. 语音全双工链路（voiceHandler.js + voiceRoute.js + VoiceCall.jsx）

### 6.1 后端流水线
`前端音频流 → 百炼 ASR(Paraformer) → InterviewEngine+LLM → 百炼 TTS(CosyVoice) → 前端播放`
- 复用文字面试引擎 `InterviewEngine`，WebSocket 全双工。
- ASR：`wss://dashscope.aliyuncs.com/...`，`run-task` 指令，`pcm/16k/max_sentence_silence:2000`（静默 2s 断句）。`sentence_end` 时整句入 `pendingSentences` 队列并触发 `processNext`。
- LLM：复用引擎，`isProcessing` 锁保证同刻只处理一轮；语音模式动态注入"回复≤80字、禁用书面格式、禁语气词开头"；流式过滤 `reasoning_content` 后通过 `ai_text` 实时发前端。
- TTS：`cosyvoice-v1` / `longxiaochun` 音色，MP3/22050；二进制流直接 `clientSocket.send(data)` 透传前端，30s 超时保护。
- 计时：`firstAsrTime` 与 TTS 结束时间戳分离，精准算"思考间隔"。

### 6.2 WebSocket 协议（voiceRoute.js）
- 握手：`/ws/voice?sessionId=`，查 `interview_sessions` 校验存在且 `in_progress`，否则发 error 并 close。
- 消息：文本/JSON 控制（`hangup` 挂断）；二进制音频直接 `forwardAudioToASR`。
- `socket` 与 sessionId 强绑定；`close`/`error` 均调 `destroy()` 清理。

### 6.3 前端 VoiceCall.jsx
- **采集**：`getUserMedia` 单声道 16k + 回声消除/降噪；`ScriptProcessorNode` 转 PCM16 `Int16Array`；VAD（`AnalyserNode` avg>15 驱动波形）；节流：muted/AI说话/已结束 时不发送。
- **播放**：二进制分片入 `audioQueue`，`ai_end` 时合并 `Blob(audio/mpeg)` 播放；结束则播完 2s 后自动切回文字模式。
- **字幕**：`asr_result` 驱动用户气泡（final 清空 ref）；`ai_start/ai_text/ai_end` 驱动面试官气泡；`TypingDots` 打字动画。

---

## 7. 数据模型（6 张表，全部 UTC+8）

`resumes`（简历+parsed JSON+parse_status）/ `model_providers`（AES 加密 Key）/ `task_model_binding`（单例任务绑定）/ `interview_sessions`（messages JSON + stage + project_index + stage_turns + status）/ `interview_reports`（overall_score + qa_breakdown JSON + status: generating/done/failed）/ `job_positions`（name/tags/category/scripts{mixed,project,basic}/enabled）。

设计要点：对话全程存为 `messages` JSON，阶段状态用标量字段冗余存储便于查询；报告生成是**异步状态机**（generating→done/failed）。

---

## 8. 安全与工程权衡点评

- **密钥加密** `crypto.js`：AES-256-GCM，随机 12 字节 IV，结构 `iv:tag:ciphertext`(hex)。
  - ⚠️ 风险：默认硬编码密钥 `'grillmind-default-encryption-key!!'`，忘配 `GRILLMIND_ENC_KEY` 则全库可反推。
  - ⚠️ 无真正密钥派生：`getKey()` 仅 `Buffer.alloc(32)` 截断/填充，未用 scrypt/PBKDF2。建议用 `crypto.scrypt`。
- **脱敏展示**：`getAllProviders` 只返回 `hasApiKey` 布尔，不返明文/密文。
- **SQL 阻塞风险**：`better-sqlite3` 同步 API 在异步任务中直接调用，高并发可能阻塞事件循环（建议任务队列）。
- **简历敏感数据**：`raw_text`/`parsed` 明文存储，需确认 DB 加密与调用第三方 AI 时的脱敏合规。
- **AI 输出校验**：仅校验 `jobTendency` 一个字段，建议引入 zod/ajv 做完整 JSON Schema 校验。

---

## 9. 对您项目的可借鉴点（落地建议）

1. **面试状态机**：引入"阶段+轮次计数"推进模型，替代纯 LLM 自决。`closing` 阶段注入内部收尾指令的"工程强控"手法可直接迁移。
2. **简历解析前置追问点**：在简历解析阶段就产出 `deepDivePoints`/`vaguePoints`，让面试官追问有数据支撑——比单纯 STAR 评分更"会挖"。
3. **Prompt 输出约束**：明确"禁 Markdown / 禁括号动作 / 禁垫词开头"，显著提升语音 TTS 自然度与前端渲染安全性。
4. **任务级模型绑定 + 面试禁思考**：按任务独立绑定模型，且面试永远关深度思考保低延迟——多供应商 fallback 思路与您的 auto 探测可互补。
5. **报告结构**：`qaBreakdown` 逐题 + `realInterviewImpact`（对真实面试的影响）+ `thinkingSeconds` 思考时长，比纯维度评分更有指导价值。
6. **语音全双工**：VAD 节流 + 二进制音频直透 + TTS 结束自动切回文字的链路设计，可对照您 MiMo 语音方案优化。

---

## 10. 落地状态（v6.2，2026-08-28 全部完成）

> 实现细节与范围边界见 [CHANGELOG.md v6.2](../CHANGELOG.md)。测试：`tests/test_grillmind_borrowings.py`（50 例）。

| # | 借鉴点 | 状态 | 落地位置 | 与原设计的偏差 |
|---|---|---|---|---|
| 1 | 面试状态机 closing 强控 | ✅ 已落地 | `config.CLOSING_INSTRUCTION/CLOSING_MESSAGE`、`session.is_closing_round()`、`question_gen(closing_instruction)`、`main` 推 `interview_closing` | 收束语改为工程层确定性文案（省一次 LLM 调用且不会生成失败），非模型生成 |
| 2 | 简历前置追问点 | ✅ 已落地 | `resume_parser.extract_interview_points()`、`question_gen.build_resume_points_block()`、`session._evidence_for()` | 追问点在**会话创建时**提取（本项目简历解析是纯离线文本提取，无独立解析态可挂），其余链路一致 |
| 3 | Prompt 输出约束 | ✅ 已落地（约束 + 净化双保险） | `output_sanitizer.OUTPUT_CONSTRAINTS/sanitize_spoken_text()`，注入出题/诊断/改写/追问四处 | 除 Prompt 约束外增加**工程兜底净化**，且调整为"先去舞台提示再去 Markdown"（否则 `*停顿*` 剥掉标记后只剩"停顿"留在正文） |
| 4 | 任务级模型绑定 + 面试禁思考 | ✅ 已落地 | `config.LLM_TASK_MODELS/REALTIME_TASKS/INTERVIEW_DISABLE_REASONING`、`llm_client.task_candidates()/is_reasoning_model()` | 绑定为 opt-in（不配即沿用 `LLM_MODEL`，向后兼容）；剔除推理模型后若无候选可用则**保留原池并告警**，避免调用直接失败 |
| 5 | 报告结构 qaBreakdown | ✅ 已落地 | `report.qa_breakdown/thinking_stats/resume_points`、诊断 prompt `real_interview_impact`、前端「逐题拆解」卡片 | `realInterviewImpact` 模型未产出时按"分数 × 思考时长"规则兜底（措辞明确为规则结论，不伪装成面试官原话）；`thinkingSeconds` 由前端计时上报，仅用于复盘不参与评分 |
| 6 | 语音全双工 | ⚠️ 部分落地 | `voice.js` VAD 节流（静音 2.5s 自动停录、2min 上限）、`autoReadQuestion(onEnd)` + `refocusAnswerInput()` | **未做全双工**：MiMo ASR 为请求-响应协议，边说边识别需自研流式网关；二进制音频直透已天然满足（TTS 音频 Blob 直放、ASR 直传 Blob，不经文本中转）。VAD 只判断"何时停止录音"，不裁剪已录音频 |

> 研读完成。如需下钻任意模块（如 `ai/client.js` 完整重试逻辑、`interviewOutput.js` 净化规则、Electron 主进程打包），可继续指定。
