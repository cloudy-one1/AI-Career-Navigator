# 变更日志（CHANGELOG）

> 记录 v2 → v5.0 的版本迭代叙事（新增/推翻/修复/范围）。不变的架构约束与决策记录见 [CHARTER.md](CHARTER.md)，日常协作入口见 [CODEBUDDY.md](CODEBUDDY.md)。

---

## v5.0 简历证据检索 + 不会答恢复 + 薄弱点累计 + 会话中多模式切换（2026-08-28）

> 对标 [agent-interview-coach](https://github.com/xiaodeng-lp/agent-interview-coach) 的 interview_corpus / coaching recovery 思路，补齐三块硬短板：(1) **简历证据检索**——新增 `resume_retriever.py` 轻量检索器，为追问与诊断实时产出「本轮证据包」，并用证据硬规则约束诊断模型**只依据简历证据或候选人亲述评价**、严禁编造经历，从机制上杜绝"AI 凭空捏造候选人做过的事"；(2) **不会答恢复（coaching recovery）**——检测到候选人示弱（不会/不懂/没思路…）时切换辅导式引导，而非机械继续拷打；(3) **薄弱点跨轮累计**——把各轮诊断的薄弱标签跨轮聚合，实时面板 + 报告沉淀「今日弱点」。另支持会话中动态切换模式/阶段（simulation / traditional / coach / hardcore / interview_only × phone_screen / tech_round_1 / tech_round_2 / hr）。新增/重写测试 61 例（session 状态机 + resume_retriever），分层 lint 通过。

### 新增（功能线）
- **简历证据检索器（`resume_retriever.py`，L2）**：本地关键词 + 文件名优先级加权（`FILE_PRIORITY`，`score = priority + 命中词数×8`），无向量库/无托管依赖；`_chunk_text` 按 `CHUNK_SIZE=2000` 分块、`CHUNK_OVERLAP=250` 保相邻块语义；`_score_chunks` 仅在前 `SEARCH_HEAD_CHARS=800` 字符内匹配，且**只选命中≥1 关键词的块**（修复"无命中块也当选证据"缺陷）；`select_context` 施加单源 `MAX_CHUNKS_PER_SOURCE=2` / 总块数 `MAX_CONTEXT_CHUNKS=4` / 总字符 `MAX_CONTEXT_CHARS=6000` 三重硬预算防 token 膨胀；单文档纳入 `MAX_CHARS_PER_FILE=120_000`；无证据返回 `_NO_EVIDENCE_MESSAGE` 兜底；`trace_retrieval()` 逐块溯源（chunk_id/source/matched_terms/score/selected/reason）。
- **诊断注入证据包 + 证据硬规则**：`diagnosis_engine` 的 `diagnose()/stream()/run_diagnosis*()` 新增 `evidence_package` / `mode` / `recovery_requested` 参数；新增 `EVIDENCE_USE_HARD_RULES`（只能依据证据或亲述评价、严禁编造、证据不足需明确澄清式追问、与简历矛盾需指出）、`COACHING_RECOVERY_INSTRUCTION`（不会答恢复）、`_MODE_INSTRUCTIONS`（五模式指令）、`WEAKNESS_KEYWORDS + _extract_weakness_tags`（薄弱点标签提取，限 6 个）；`normalize_result()` 新增返回 `weakness_tags`。
- **会话状态机（`interview_engine/session.py`）**：`UNCERTAIN_ANSWER_MARKERS + needs_recovery()` 检测不会答信号；`_evidence_for()` 惰性构建 `ResumeRetriever` 生成证据包；`accumulate_weaknesses()/weakness_payload()` 跨轮累计薄弱点（返回 `tags/counts/recovery_active`）；`switch_mode(mode, stage)` 会话中切模式/阶段（切 `traditional` 于下一轮重建轮次结构）；`advance_round()` 在 `mode_changed` 时按新模式重建轮次；`stream_answer()/handle_answer()` 注入证据/模式/恢复信号。
- **多模式/多阶段协议**：`schemas.py` 新增 `InterviewMode`（simulation/traditional/coach/hardcore/interview_only）与 `InterviewStage`（phone_screen/tech_round_1/tech_round_2/hr）枚举；`SessionCreateRequest` 新增 `mode`/`stage`；新增 `ModeSwitchRequest/ModeSwitchResponse` 响应模型；`DiagnosisResult` 新增 `weakness_tags`。
- **后端端点**：HTTP `POST /api/interview/{session_id}/mode`（`switch_interview_mode`）；WS `/ws/interview/{session_id}` 新增 `switch_mode` 消息、`mode_change` 事件、`weakness_update` 事件（每题诊断后推送）、`interviewer_info` 含 `stage`。
- **报告沉淀**：`report.py` 新增 `detailed_qa`（逐题标准答案，含 rewritten_answer/key_changes/weakness_tags，修复"参考答案恒为空"缺陷）与 `weakness_tag_summary`（跨轮薄弱点标签）；`generate_review_markdown()` 新增「薄弱点标签（跨轮累计）」章节。
- **前端**：`interview.js` 新增 🔥拷打/🤐只面试两个模式卡片、会话中模式下拉切换、`weakness_update` →「⚠️ 薄弱点（跨轮累计）」面板 + `recovery-banner`「🛟 已进入不会答恢复辅导」、`mode_change` 徽章刷新、侧栏模式+阶段徽章；`report.js` 新增「🏷 薄弱点标签（跨轮累计）」标签云。

### 修复
- `resume_retriever.py` 初始化顺序：`_chunk_id` 在 `add_document()` 之后才赋值导致分块抛 `AttributeError`（改为先初始化）。
- `resume_retriever.py` 命中过滤：无关键词命中的块也会凭 priority 入选，与"无匹配返回兜底提示"语义冲突（改为仅选命中块）。
- `tests/test_session.py` 重写：旧草稿按臆测接口断言（`market_keyword`/`current_round_index`/四维 technical_depth），与 v5.0 实际实现完全脱节、必挂；重写为对齐真实接口（含五维 `professional_depth`、`config` 单例常量、`switch_mode` 事件、证据/恢复/薄弱点等 v5.0 能力）的可用测试。
- `llm_client.py` 模块级全局单例导入即崩溃：`.env` 的 `LLM_FALLBACK_CHAIN` 含未配置 key 的备用 provider（如 `qwen:qwen-plus` 但 `QWEN_API_KEY` 为空）时，`_init_client` 在构建 fallback 候选 `OpenAI(api_key="")` 直接抛 `OpenAIError`，导致所有 import 它的测试在 collection 阶段失败（4 个 LLM/环境类测试无法收集）。修复：fallback 候选构建时对 key 做 `_api_key_issue` 校验，**无效 key 的候选直接跳过**（符合 fallback「备用缺失应降级而非致命」语义），主候选不受影响。修复后整套测试（含 LLM 类）438 例全绿。

### 工程化
- **测试**：新增 `tests/test_resume_retriever.py`（分块/命中/预算/溯源/证据包共 12 例）+ 重写 `tests/test_session.py`（状态机/追问/权重/轮次/薄弱点/恢复/多模式共 49 例），共 61 例；完整套件约 438 例（含依赖 API Key 的 `test_career_planner`/`test_gap_analyzer`/`test_llm_client`/`test_llm_fallback`），本机缺 Key 时其中 4 个 LLM/环境类测试无法收集、其余通过。

### 范围与约束
- 检索为**本地关键词启发式**，非语义向量检索：中文分词粒度受限，同义/模糊表述可能漏命中；仅作证据提示，不替代向量库。可调参数目前为代码级常量（`resume_retriever.py`），未下沉 `.env`。
- 证据硬规则依赖 `evidence_package` 注入，仅约束诊断/追问阶段；**前端参考答案沉淀面板（`detailed_qa`）尚未渲染**，报告已产出字段，属前后端待对齐项。
- 会话中切换 `traditional` 需下一轮生效；模拟模式内部（simulation/coach/hardcore/interview_only）可即时切换。

## v4.3 模型调用优雅降级（fallback）（2026-08-28）

> 在 L1 基础设施 `LLMClient` 新增配置驱动的模型 fallback 降级链：主模型调用失败（异常/限流/超时/返回不可用内容）时按 `LLM_FALLBACK_CHAIN` 自动切换备用 provider:model，覆盖非流式与流式（WebSocket 主流程）；调用方零改动，全局单例语义不变。新增 11 例 fallback 单测，分层 lint 通过。

### 新增（功能线）
- **fallback 候选池**：`llm_client.py._init_client` 按 `LLM_FALLBACK_CHAIN` 预构建有序候选（各自独立 api_key/base_url/model），主候选（当前 provider/model）始终在首位；`LLM_FALLBACK_MAX_RETRIES` 限制最大尝试数。
- **降级包装器**：新增 `_call_with_fallback`（非流式，含 `success_pred` 软失败判定，JSON 解析失败自动重试下一候选）与 `_stream_with_fallback`（异步流式：`yield` 前失败无缝切换、已产出半截则停止并报错不拼接）。
- **调用方零改动**：`chat / chat_json / chat_stream / chat_stream_async` 签名不变、内部自动 fallback；`question_gen / diagnosis_engine / career_planner / gap_analyzer / dimension_weights / web_research` 等全部汇聚到 `LLMClient` 的模块自动获得降级（不含 v4.2 MiMo 语音，其走独立降级通道）。
- **配置**：`config.py` 新增 `LLM_FALLBACK_CHAIN` / `LLM_FALLBACK_MAX_RETRIES`；`.env.example` 新增 fallback 配置块。

### 工程化
- **测试**：新增 `tests/test_llm_fallback.py`（非流式/流式/配置解析共 11 例）；LLM 相关测试 18 例通过。
- **可观测**：`get_provider_info` 暴露 `fallback_count`；fallback 命中与软失败均有日志标注。

### 范围与约束
- 单候选（未配置 `LLM_FALLBACK_CHAIN`）行为完全退化为现状，向后兼容。
- fallback 不改变双 Agent 诊断客观性（评分与改写仍按既定顺序/prompt 隔离），仅解决单点 provider 故障；需为备用 provider 配置独立密钥方可生效。

## v4.2 小米 MiMo 云端语音接入（2026-08-28）

> 将面试语音交互从"浏览器原生 Web Speech API"升级为"**MiMo 云端语音优先 + 浏览器原生降级**"双引擎：TTS 朗读用 mimo-v2.5-tts，语音输入用 mimo-v2.5-asr（MediaRecorder 录音上传）。**诊断内核零变更**，语音仍是输入/输出替代层；320 测试全绿（新增 29 例）、分层 lint 通过。

### 新增（功能线）
- **后端语音代理**：`backend/voice_service.py`（L2/L3）封装 MiMo 官方 `chat/completions` 协议（认证头 `api-key`）；`config.py` 新增 `MIMO_API_KEY / MIMO_BASE_URL / MIMO_TTS_MODEL / MIMO_ASR_MODEL / MIMO_TTS_VOICE / MIMO_TTS_STYLE / MIMO_ASR_LANGUAGE / MIMO_TIMEOUT / RATE_LIMIT_VOICE`；新增路由 `POST /api/voice/tts`（文本→合成音频 Base64）与 `POST /api/voice/asr`（上传音频→转写文本），密钥仅存后端 .env。
- **前端双引擎**（`frontend/src/js/voice.js`）：`voiceSupport.mimo` 能力检测 + `probeMimo()` 后台探测；`speak()` 改为 MiMo 优先、失败自动降级 `speechSynthesis`；新增 MediaRecorder 录音采集（`startRecording/stopRecording`）与 `transcribeRecording()` 上传 ASR；新增 `voiceFillWithASR()`（录音→识别→填入回答）。
- **语音对话链路**（`interview.js`）：主回答区与追问区麦克风改用 MiMo ASR 优先；按钮显示条件放宽为"STT 或录音都可用"；新增 `processing` 状态与语音引擎角标（MiMo / 浏览器降级）。
- **api.js**：新增 `requestVoiceTTS / requestVoiceASR` 接口。

### 工程化
- **依赖**：`httpx` 从测试段移入生产依赖（运行时语音代理所需）。
- **环境变量**：`.env.example` 新增 MiMo 配置块（不配置则自动降级浏览器原生语音，功能不中断）。
- **测试**：新增 `test_voice_service.py`（key 校验/音色映射/错误处理/超时/mock 调用）与 `test_voice_api.py`（路由降级/400/成功/失败路径），共 29 例；全量 320 用例通过。

### 范围与约束
- **MiMo-Audio 7B 开源模型不采用**：需 NVIDIA GPU≥24G + Linux，当前 Windows 环境不可行；选用云端 API（MiMo-V2.5-TTS 限时免费，ASR 0.5 元/小时）。
- 语音仍作为输入/输出替代层，**不参与诊断内核**（与 CHARTER.md v2.3 定位一致）。
- 未配 Key / 网络失败 / 超时 / 限流均自动降级浏览器原生语音，功能不中断。

### 修复（v4.2 协议对齐，真实 Key 实测）
- **问题**：首版按 OpenAI `/audio/speech`、`/audio/transcriptions` 协议编写，域名误用 `api.mimo.ai`，与 MiMo 官方协议不符，配置 Key 后调用失败（SSL/404）。
- **修正**（以 mimo.mi.com 官方文档与开源实现 ppy-web/tts-mimo 核实为准）：
  - 端点统一为 `POST {base}/chat/completions`（TTS/ASR 均如此）；认证头 `api-key`（非 Bearer）。
  - 域名改为 `https://api.xiaomimimo.com/v1`（sk- 按量付费集群）；模型名统一小写 `mimo-v2.5-tts` / `mimo-v2.5-asr`。
  - TTS 请求体 `messages[user=风格提示, assistant=待朗读文本] + audio{format:wav, voice}`；响应解析 `choices[0].message.audio.data`（Base64 WAV，兼容 data URL 前缀）。
  - ASR 请求体 `messages[user.content[0].input_audio.data=音频 data URL] + asr_options{language}`；响应解析 `choices[0].message.content`（兼容字符串与 `[{"text":...}]` 列表）。
  - 新增 `MIMO_TTS_VOICE`（默认冰糖）/ `MIMO_TTS_STYLE` / `MIMO_ASR_LANGUAGE`；非法音色名自动映射默认音色。
- **端到端实测（真实 Key）**：TTS 合成成功，返回 WAV 校验头 `RIFF/WAVE/fmt` 正确；ASR 协议链路正确（服务器返回 402 余额不足，属账户计费问题而非协议错误，充值后可用；前端失败自动降级浏览器 STT，不阻塞）。

---

## v4.1 市场数据 Tab：B 档内嵌实时采集（2026-08-27）

> 按用户定案 B 档（子模块内嵌），将开源项目 job-crawler 的 Playwright 采集核心整合进本系统，新增第 6 个"市场数据"Tab，复刻其纸墨印章设计语言（米色纸张 + 衬线 + 印章红）。**后端其余契约零变更**；291 测试全绿、分层 lint 通过。

### 新增（功能线）
- **实时采集**：关键词 + 省份→城市级联多选（≤5 城市）+ 排序（相关性/最新发布）+ 页数 1~5；后台线程执行 `scrape_jobs()`，前端 1.5s 轮询进度（当前城市/页数/累计条数/进度条）；采集结果经 `adapters.to_standard_job()` 直通 `store.upsert_jobs()` 回灌 `market.db`。
- **岗位库**：统计概览（岗位总量/平均薪资/热门技能 TOP5/样本城市）+ 筛选（关键词/城市/学历/薪资区间）+ 纸感表格（编号角标/悬停浮起/行勾选）+ 分页。
- **岗位详情**：全屏独立视图（还原 job-crawler job_detail 结构），展示完整描述/标签/薪资/经验/学历/发布时间，**支持跳转 51job 原文**，可一键用本岗位做 Gap 分析。
- **岗位分析**：单选 Gap 分析（复用 `/api/gap-analysis`，含市场基准注入）；多选 2~5 个跨岗位对比（复用 `/api/cross-job-compare`，排名卡 + 风险等级）；简历文本可一键复用面试 Tab 内容。
- **两套 UI 风格自由切换**：浅色公文风（米纸墨印）↔ 深色 SaaS 风（深墨底），顶部语义色切换器（青/粉/金/紫），localStorage 记忆；作用域严格限定 `#market-panel`，不影响其余 Tab 的 Indigo 设计体系。

### 工程化
- **crawler 子包**（`backend/market/crawler/`，随 `backend.market` 同属 L2，不越层）：`python_job_scraper.py`（相对导入改造、删 `__main__`、日志改名）+ `salary_parser.py` + `adapters.py`（字段映射/JD 组装）+ `tasks.py`（线程安全任务表、单实例互斥、TTL 10 分钟惰性清理）。
- **新路由**：`POST /api/market/crawl`（Form 校验 + `3/minute` 限流）、`GET /api/market/crawl/status/{task_id}`、`GET /api/market/city-map`（省份→城市级联数据源，复用 scraper 的 388 城市表）、`GET /api/market/jobs/{job_id}`（岗位详情 + 组装 JD 文本供 Gap 分析）。
- **依赖**：新增 `playwright>=1.40`、`playwright-stealth`；README 补充 `playwright install chromium` 安装步骤；未安装 playwright 时路由返回明确错误与安装指引。

### 治理
- **决策记录卡 DC-04**（CHARTER.md）：推翻 DC-02"不再用 Playwright 采集"决策，改以 B 档内嵌方式整合采集核心，以真实采集工作量补足"数据资产≠代码复现"缺陷；`data.db` 导入管道保留兜底，两者并存。
- **测试**：新增 `test_market_crawler_adapters.py`（字段映射/薪资解析/描述截断/JD 组装）与 `test_market_crawler_tasks.py`（参数校验/单实例互斥/状态机/TTL 清理），共 23 个用例；全量 291 用例通过，`python run.py lint` 分层契约通过。

---

## v4.0 前端 UIUX 重构落地（2026-08-27）

> 按 v3.3 方案（`docs/前端设计方案_UIUX重构.md`）分 5 阶段实施完毕。**后端契约除历史详情端点外零变更**；268 测试全绿。

### 工程化（阶段 1-2）
- **Vite 5 构建**：`npm run dev`（:5173 代理 `/api` `/ws` `/upload` → :8000）开发 / `npm run build` 产出 `dist/` 由 FastAPI 托管；Chart.js 转 npm 依赖。
- **Design Tokens 四层拆分**：`tokens.css`（语义 Token + 深色预留）/ `base.css`（reset+排版）/ `components.css`（框架组件）/ `pages/*.css`（领域样式）。新视觉系统：Indigo 品牌主色 + Slate 中性 + 琥珀点缀（仅鼓励/里程碑/成长）。
- **导航三态自适应**：桌面左垂直导航 / 平板图标栏 / 移动端底部 Tab。

### 核心体验重构（阶段 3）
- **Setup 三步引导**：简历与岗位 → 面试偏好（模式/自我介绍）→ 题型与风格；右侧实时配置摘要卡，含步骤切换即时校验、一键均衡题型。
- **Session 双栏工作台**：左侧对话流 + 右侧固定诊断面板（阶段进度/维度权重/实时雷达）；回答输入条 sticky 浮起，始终可见。
- **Diagnosis 复盘态**：ScoreRing 环形总分 Hero + 五维条形图 + 最弱维度高亮徽章 + 原文/示范改写对照 + 回答风险点列表。
- **动效**：对话流卡片 fade-up 进场（消息逐条天然 stagger）、弱项脉冲、环形填充过渡、tag 呼吸动画。

### 其余模块重构（阶段 4）
- **报告 Dashboard**：环形总分 Hero + 关键指标条（轮数/已答/强项/待提升）+ 雷达图与轮次时间线双栏。
- **历史**：列表项增强（风格/状态/JD 徽章 + 评分跳转）；新增**详情抽屉**（问答记录逐题评分 + 综合评分 + 轮次汇总）。修复 `GET /api/sessions/{id}` 仅返回 session 导致详情实际不可用的缺陷（现附带 `qas` + `report`）。
- **题库**：新建/编辑由行内表单改为**居中 Modal**，删除遗留的 `editingId` 行内编辑状态机。
- **职业规划**：沿用 v3.2 时间轴/技能曲线，纳入新布局。

### 打磨（阶段 5）
- **深色主题**：跟随系统 `prefers-color-scheme`，变量层覆盖 + `pages/dark.css` 组件级微调（Hero 渐变/徽章/时间线/表单焦点环等）。
- **无障碍**：`focus-visible` 焦点环、`prefers-reduced-motion` 动效降级、ScoreRing/Drawer/Modal `role/aria` 语义。
- **验证**：前端构建零错误、lint 零告警、268 测试全绿（含新增详情端点断言）。

---

## v3.3 前端设计方案评审稿（2026-08-27）

> 详见 `docs/前端设计方案_UIUX重构.md`。本轮为**方案评审稿**：只产出设计文档，不修改代码；评审确认后按文档第 10 章分阶段实施。

- **设计定调**：现代专业·简洁留白（Indigo 品牌延续）+ 教练式温暖（暖琥珀点缀）+ 克制 AI 反馈（流式/光晕仅用于状态表达）。依据：高压求职场景需要专业可信与焦虑安抚并存。
- **信息架构**：5 功能模块按"准备→实战→复盘→规划"用户旅程重组；导航从顶部 Tab 改为左垂直导航，桌面 220px / 平板图标栏 / 移动底部 Tab 三态自适应。
- **视觉系统**：Design Tokens 四层拆分（tokens / base / components / pages），替代单文件 style.css（1061 行）；新增 Indigo/Slate/琥珀阶梯与三级卡片层次（白卡/浅底卡/描边卡）。
- **组件体系**：基础 / 数据 / 领域 / 状态四类组件规范 + 四态设计（空/载/成/错），核心领域组件（ScoreRing / StreamBox / DiagnosisCard / RadarCard 等）给出交互规格。
- **工程化**：引入 Vite 5（用户批准）+ Chart.js 转 npm 依赖；开发态 `dev-front`（:5173 代理 `/api` `/ws` `/upload` → :8000），生产态 `dist/` 由 FastAPI 托管；迁移阶段零 UI 变更、逐阶段验收。
- **实施路线**：5 阶段（Vite 迁移 → Token 与全局框架 → 核心体验重构 → 其余模块 → 动效/响应式/无障碍打磨），每阶段含交付物与验收标准，后端契约全程零变更。
- **范围边界**：深色模式、用户认证、云端语音、PDF 导出本期不做（Token 预留 `data-theme` 扩展位）。

---

## v3.2 宪章治理 + 职业规划补全（2026-08-13）

> 详见 `docs/week7_诚实披露与代码整改_需求.md` 及其后续决议。本轮两条主线：

### 宪章治理
- **CODEBUDDY.md 拆分为三份**：CHARTER.md（不变硬约束）+ CHANGELOG.md（版本叙事）+ CODEBUDDY.md（索引入口）。解决"宪章与变更日志混写导致硬约束淹没在版本叙事中"的问题。
- **import-linter 工具强制分层**：新增 `.importlinter` 契约文件（L1-L4），以 `python run.py lint`（= `PYTHONUTF8=1 python -m importlinter.cli lint`）确定性检查所有 import 越层，取代"随机抽查 2-3 条"的文字纪律。踩坑记录：裸 `python -m importlinter` 只打印帮助不执行检查（假阳性 RC=0）；Windows 下不设 PYTHONUTF8 时 grimp 按 GBK 读 UTF-8 源码崩溃漏检。
- **分层契约按代码现状校准**：`market/*` 从 L3 调整为 L2（`gap_analyzer` 已依赖它做市场基准注入，否则构成 L2→L3 越层）。
- **决策记录卡机制**：CHARTER.md 新增强制决策记录卡模板，并补写 3 张决策卡：DC-01 双 Agent 不可合并（补录论证依据）、DC-02 推翻不复用约束（v3.0 决策复盘）、DC-03 补建职业规划功能线（v3.2）。取代"事后从对话提炼批判性思维信号"的注水机制。

### 职业规划功能线（补齐产品命题）
- **修复缺口**：产品全名"AI 模拟面试官**与职业规划**"后半段长期未落地（全文搜索仅命中出题提示词两处）。本轮补建真正的时间轴路径规划模块，而非横截面打分。
- **`backend/career_planner.py`（L3 新增）**：`plan_career()` 以 `gap_analyzer.analyze_gap()` 六维快照为现状基线，调用 LLM 做多步路径推理，输出结构化 `CareerPlanResponse`（多阶段时间轴：阶段/需补技能/里程碑/岗位跃迁/顺序理由）。
- **`backend/schemas.py`**：新增 `CareerStage` / `CareerPlanRequest` / `CareerPlanResponse` Pydantic 模型。
- **`backend/main.py`**：新增 `POST /api/career-plan`（限流 `RATE_LIMIT_CAREER`，默认 10/分钟），错误统一转 `HTTPException(500)`。
- **前端**：新增"职业规划"Tab（`careerPlan.js`），竖向时间轴 + 阶段卡片 + 现状基线六维横条 + 技能进度 Chart.js 图 + 总结/风险徽章。
- **测试**：`test_schemas.py` 新增 CareerPlan 模型约束校验；`test_api.py` 新增 `/api/career-plan` 集成测试（mock LLM）。
- **已知局限新增**：职业规划路径推理稳定性未经 A/B 验证（见 CHARTER.md 已知局限）。

---

## v3.1 工程加固（2026-08）

> 缺陷修复 (#5)：此前无文件持久化，出问题无法追溯历史。详见 `docs/week6_*_需求.md`。

### 集中日志配置（logger.py）
- `RotatingFileHandler`：单文件 5MB，保留 3 个备份 → `data/app.log`
- 控制台同格式输出（开发时可实时查看）
- 抑制第三方库噪讯（httpx/httpcore/websockets/asyncio urllib3）
- `main.py` 入口处调用 `setup_logging()`，其余模块沿用 `logging.getLogger(__name__)`
- `run.py` 的 `print()` 替换为 `logging.info/warning`
- `.env.example` 新增 `LOG_LEVEL`/`LOG_FILE`/`LOG_MAX_BYTES`/`LOG_BACKUP_COUNT`

### Gap 分析（gap_analyzer.py）[v3.1 NEW]
简历-岗位六维度透明匹配评分（缺陷修复 #2）：
1. **技能匹配** (35%) — 技能栈 vs JD 需求
2. **城市/地点** (15%) — 期望城市 vs 岗位所在地
3. **学历匹配** (15%) — 学历层次 vs 岗位要求
4. **经验年限** (15%) — 工作经历 vs 岗位年限
5. **薪资预期** (10%) — 期望 vs 市场范围
6. **可信度** (10%) — 简历信息一致性

**市场基准交叉参考**：当 market.db 有对应岗位数据时，自动注入薪资分位、学历分布、热门技能作为"你在这个市场中的位置"参照。

- API: `POST /api/gap-analysis`（免 session）、`GET /api/gap-analysis/{session_id}`
- 面试报告页自动展示，六维度横条 + 风险等级 + 补强建议
- DB: `sessions` 表新增 `resume_text` 列（迁移兼容旧库）

### 自动化测试（tests/）[v3.1 NEW]
缺陷修复 #4：50 个测试用例覆盖核心路径。

```bash
pytest tests/ -v
pytest tests/ --cov=backend --cov-report=term-missing  # 覆盖率报告
```

测试结构：
- `tests/conftest.py` — 共享 fixtures（App/DB/测试数据）
- `tests/test_schemas.py` — Pydantic 模型字段约束验证（11 测试，含跨岗位对比）
- `tests/test_gap_analyzer.py` — 维度规范化 / 加权计分 / 降级 / 关键词提取（21 测试）
- `tests/test_api.py` — HTTP 路由集成测试（18 测试）：基础/会话/Gap/市场/题库/反馈/安全限流/预热

**修复的既有缺陷**：
- `resume_parser.py`：内联文本（str）传参时原代码仍调用 `.decode()` 导致崩溃 → 加 `isinstance(file_bytes, str)` 短路返回
- `db.py`：`:memory:` 模式下 `os.makedirs("")` 在 Windows 报错 → 加空目录跳过

### Web 层加固（#6）[v3.1 NEW]
基于 job-crawler 项目的安全实践补充：
- **slowapi 频率限制**：全局 100/分钟，上传 10/分钟，Gap 分析 20/分钟，岗位研究 10/分钟，市场导入 5/分钟，预热 1/分钟
- **安全响应头**：x-content-type-options / x-frame-options / x-xss-protection / referrer-policy
- **请求体限制**：上传 10MB，普通请求 1MB，防止大包攻击
- 新增 6 个安全测试用例（`TestSecurityMeasures`）

### JD 权重缓存（#7）[v3.1 NEW]
- 新增 `jd_weights_cache` 表，以 JD 文本的 SHA256 作为主键
- `analyze_jd_weights()` 流程：查缓存 → 命中则直接返回（source="cache"）→ 未命中才调 LLM → 写入缓存
- 避免同一 JD 重复调用 LLM 分析权重，减少 token 消耗和响应延迟

### 数据预热（#8）[v3.1 NEW]
- `POST /api/warmup`（1/分钟限流）：收集历史会话中所有不重复的 JD 文本
- 对未缓存的 JD 逐一调用 `analyze_jd_weights()` 预计算维度权重
- 返回 `{precomputed, skipped, total_jds}` 统计信息

### 分层依赖约束（#9）[v3.1 NEW]
在架构约束章节中明确 L1-L4 逻辑分层及导入方向规则（v3.2 起升级为 import-linter 工具强制，见上）。

### 市场数据注入出题（#10）[v3.1 NEW]
- `question_gen.py` 新增 `_extract_keyword_from_text()` + `_build_market_context_block()`
- 查 market.db 获取该岗位的市场数据（热门技能、常见公司、学历分布、薪资范围）
- 作为 `market_block` 注入各阶段/轮次出题的 user prompt，使题目更贴近真实市场

### 跨岗位对比（#11）[v3.1 NEW]
- 新增 `POST /api/cross-job-compare`（5/分钟限流）：一份简历同时对比多个 JD
- 并行 Gap 分析每个 JD，按 overall_score 排名，自动生成择岗建议
- 前端：报告页动态表单 + 柱状图 + 排名列表 + 各岗位补强建议

### Gap 分析市场基准参照（#12）[v3.1 NEW]
- `schemas.py` 新增 `MarketReference` 模型：keyword / 样本数 / 平均薪资 / 热门技能 / 城市分布 / 学历分布
- `gap_analyzer.py` 新增 `_build_market_reference()`，当 market.db 有匹配数据时自动注入
- 前端报告页渲染"市场参照"卡片，展示"你在这个市场中的位置"

---

## v3.0 市场数据层深度改造（2026-08）

> 详见 `docs/week5_v3数据层_需求.md`

### 推翻"不复用约束"
原决策"不能复用 job-crawler data.db"被推翻：导入数据资产不等于复现代码，Playwright 重复采集纯粹浪费。（决策复盘见 CHARTER.md DC-02）

### 数据管道：job-crawler → market.db
```
job-crawler data.db → importer.py (字段映射) → store.upsert_jobs() → market.db
```
- `importer.py`：读取 job-crawler `data.db`，字段映射后批量写入 `market.db`
- `service.py`：简化，只保留 `import_and_store()` + `find_relevant_snapshot()`
- `config.py`：`IMPORT_TOKEN/RATE/MAX_PAGES` → `JOB_CRAWLER_DB_PATH`
- `main.py`：`POST /api/market/import` 简化为同步端点
- `requirements.txt`：移除 `playwright>=1.44.0`、`playwright-stealth>=1.0.6` (~200MB)
- 删除 `collector.py`

---

## v2.6 深化诊断核心（2026-07）

> 详见 `docs/week4_深化诊断核心_需求.md`。本次不新增功能面，而是纵向加深核心诊断能力。

### 诊断维度权重按 JD 动态化（dimension_weights.py）
- **维度数量由架构约束定义**（见 CHARTER.md），此模块只调整各维度的**权重**
- `analyze_jd_weights()` 用 LLM 分析 JD → 输出五维权重 + 理由
- 权重裁剪到 `[0.10, 0.40]` 并归一化到和为 1.0；任何失败路径退化等权
- 贯穿全链路：注入 Diagnostician/Rewriter Prompt → 加权 `overall_score` → 轮次推进判定 → 报告总分 → 前端权重条
- WebSocket 建立后推送 `dimension_weights` 事件

### 追问与诊断流式合并
- WebSocket 主流程改用 `run_diagnosis_streaming()`（此前已实现但从未接入）
- Diagnostician 输出 JSON 新增 `follow_up_question` + `weakest_dimension`，
  追问随诊断一次产出 → **省掉一次 LLM 调用**
- `_astream()` 把同步 `chat_stream` 经 `asyncio.Queue` 桥接为异步生成器，避免阻塞事件循环
- 新增消息：`diagnosis_status` / `diagnosis_chunk` / `rewrite_chunk` / `follow_up_received`
- **双 Agent 仍是两次独立调用，未合并**（遵守架构约束，见 CHARTER.md DC-01）
- 追问补充**并入上一题**，不计为新题（避免扭曲轮次进度与均分）
- 后端显式支持 `skip_follow_up`，修复此前跳过追问导致流程卡死

### 雷达图实时更新（liveRadar.js）
- 面试进行区实时雷达卡片，每题诊断后由 `radar_update` 事件驱动
- 双数据集：累计平均（实线）+ 本题得分（虚线）
- `chart.update()` **原地更新**，不销毁重建（避免闪烁）

### 弱项自动追加针对性题
- `round_weak_dimension()` 按**加权失分** `(5 - 均分) × 权重` 定位薄弱维度
- `generate_round_questions(focus_dimension=..., weak_evidence=...)` 定向出题
- 各个维度各有专属出题策略，并注入该维度的**具体失分评语**
- 追加题携带 `focus_dimension`，前端显示"🎯 补强"标记

### v2.6 同步修复的既有缺陷
1. `main.py` ↔ `session.py` **6 处接口断裂**（v2.5 拆分遗留，WebSocket 流程运行即崩）
2. `security.full_check()` / `check_output()` 返回 `(bool, str)` 元组被当 dict 用
3. `session.py` 误用 `from .. import config`（应为 `from ..config import config`）
4. 前端 API 路径错误（`/api/upload-resume`、`/api/report/{id}`）
5. WS 消息体结构不一致（前端展开到顶层，后端读 `msg.data`）
6. 诊断结果字段不匹配（`dimension_details` / `rewritten_answer`）
7. `question_gen.py` 同步 `chat_json` 阻塞事件循环 → 改 `asyncio.to_thread`

---

## v2.5 岗位画像研究 + 引擎模块化（2026-07）

> 详见 `docs/week3_三个模块差距分析与阶段结论_需求.md`

### 岗位画像研究（web_research.py）
- 创建会话时自动搜索岗位相关信息（DuckDuckGo API，免费无 Key）
- LLM 分析搜索结果，输出：丰富后的 JD、核心技能列表、热门面试话题
- 搜索结果自动注入 JD，使面试问题更贴合真实岗位需求
- 提供 `POST /api/research-position` 端点供手动触发

### 诊断反馈 👍/👎
- 每轮诊断面板底部新增 👍/👎 反馈按钮
- 提交反馈写入 `diagnosis_feedback` 表，追踪会话级反馈
- API: `POST /api/feedback`、`GET /api/feedback/{session_id}`
- 反馈按钮提交后显示 ✓ 确认，2秒恢复

### 引擎模块化
`interview_engine.py` 拆分为子包：
```
interview_engine/
├── __init__.py    # 导出 InterviewSession + build_report
├── session.py     # 核心状态机（Init/轮次控制/题目生成/追问/报告委托）
└── report.py      # 报告生成（各维度趋势/强项弱项/建议）
```
向后兼容：`from .interview_engine import InterviewSession` 保持不变。

---

## v2.4 双模式面试 + 面试官切换（2026-07）

### 双模式
- **拟真模式**：原有 6 阶段大厂面试流程
- **传统模式**：笔试→技术一面→技术二面→综合面试→自定义环节（每轮独立面试官）

### 7 种面试官角色（含 attack_level 1-5 / interrupt_prob）
1. 友好型 (attack:1) | 2. 严格型 (attack:3) | 3. 压力型 (attack:5)
4. 专业型 (attack:2) | 5. 好奇型 (attack:1) | 6. 质疑型 (attack:4) | 7. 鼓励型 (attack:1)

### 自动切换机制
- 传统模式：每轮配有固定面试官风格，轮次切换时自动切换
- 拟真模式：可从配置指定每阶段面试官
- 切换时通过 WebSocket 发送 `interviewer_change` 事件
- 前端显示切换动画 + 面试官信息卡片（自动4秒淡出）

---

## v2.3 语音交互（2026-07）

基于浏览器内置 **Web Speech API**，无需后端支持：
- **TTS（文字转语音）**：面试官题目自动朗读，可点击 🔊 按钮重播（优先中文女声，语速 0.9x，朗读时脉冲动画）
- **STT（语音转文字）**：点击 🎤 按钮语音输入回答（实时转写 continuous + interimResults，追加模式自动拼接，录音时输入框边框变红 + 脉冲动画）
- 追问也支持语音输入；提交回答时自动停止所有语音

---

## v2.2 题库管理系统（2026-07）

- DB 表 `question_bank`：含阶段类型、题目文本、考察意图、标签、难度、来源、收藏、使用次数
- API 端点：
  - `GET /api/question-bank` — 列出题目（支持过滤：阶段/难度/收藏/搜索/来源）
  - `POST /api/question-bank` — 创建题目
  - `PUT /api/question-bank/{id}` — 更新题目
  - `DELETE /api/question-bank/{id}` — 删除题目
  - `POST /api/question-bank/{id}/favorite` — 切换收藏
  - `POST /api/question-bank/import` — 从会话导入题目
- 前端：独立的"题库"Tab 页面，含过滤栏、题目列表、新建/编辑表单、导入功能

---

## v2.1 质量驱动推进 + 安全层深化（2026-07）

### 质量驱动推进
阶段平均分未达阈值自动追加题目（每阶段可配置 min_questions / advance_threshold / max_extra）

### 安全防护（security.py）
**4 类启发式内容检查（课程项目级，非安全边界）**：
1. **输入检查（硬）**：高置信注入模式（角色逃逸/Prompt盗取/越狱/特殊token）正则拦截；可被换说法/编码绕过
2. **输入检查（软）**："从现在开始""你必须输出"等易误伤句式仅告警、不阻断
3. **输出检查**：检测 System Prompt 片段泄漏（仅记录，不阻断）
4. **状态/记忆校验**：重复回答（Jaccard）+ 质量校验 + 记忆污染检测（启发式）

> 诚实定性：以上是"内容护栏"而非安全边界。系统无认证/授权，session_id 仅防猜测、不是访问控制。

### 多 AI 后端（config.py + llm_client.py）
- 支持 DeepSeek / 通义千问 / 智谱 GLM / OpenAI 四后端切换
- API: `GET /api/providers` 列出可用后端，`POST /api/switch-provider` 运行时切换
- 通过 `.env` 的 `AI_PROVIDER` 或运行时 API 切换

---

## v2 多轮面试流程（2026-06）

### WebSocket 端点：`/ws/interview/{session_id}`
消息协议状态机由 `main.py` 的 handler 驱动，`interview_engine.py` 管理状态与运算。

### 面试引擎（interview_engine.py）
状态机管理 **双模式**面试流程（拟真6阶段 / 传统5轮次），含：
- 按阶段生成专属题目（6+5 套独立 Prompt）
- 流式双 Agent 诊断
- 轻量追问决策（回答<30字 或 评分<2.5 触发）
- 综合报告生成（各维度趋势 + 强项/弱项 + 建议 + 面试官历程）

### 前端模块化
8 个 JS 模块（ES Module）+ 独立 CSS，使用 Chart.js 雷达图展示各维度趋势。
