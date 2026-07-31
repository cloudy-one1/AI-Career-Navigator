# Week2 需求文档：v2 迭代——借鉴 MockMate 亮点

> 从 v1 单轮诊断基础出发，吸纳 MockMate 项目的架构精髓，迭代为更有面试"过程感"与诊断深度的 v2。

---

## 一、迭代目标

| 维度 | v1 现状 | v2 目标 |
|------|--------|---------|
| 面试流程 | 生成题目 → 逐题作答 → 单题诊断 | **多轮次**：技术面 → 行为面 → 综合面，有"阶段推进"感 |
| 通信方式 | HTTP 请求-响应 | **WebSocket 流式**传输诊断过程，用户可见实时进度 |
| 追问 | 无 | **轻量追问**：回答过短/偏题时自动追问，CODEBUDDY 允许范围 |
| 前端架构 | 单体 index.html（~700行） | **模块化拆分**：CSS + 5-6 个 JS 模块 |
| 可视化 | 纯文字评分 + 进度条 | **Chart.js 雷达图** + 阶段评分对比 |
| 安全 | 无 | **基础防护**：注入检测 + Prompt 隔离 |
| 面试官 | 无角色概念 | **面试官角色配置**：不同风格（友好/严格/压力型） |
| 综合报告 | 无 | **综合仪表盘**：多轮汇总 + 四维度趋势 |

---

## 二、借鉴 MockMate 的具体设计

### 2.1 质量驱动的阶段推进（mock_state.py → interview_engine.py）

MockMate 的 `mock_state.py` 根据评分、回答长度、剩余时间动态决定是否进入下一阶段，而非固定题数。

**v2 实现**：
- 不固定每题诊断次数，回答过短（<30字）自动追问
- 单轮内至少覆盖 N 题后，综合分达到阈值才推进到下一轮
- 生成 `stage_advance_decision`：{advance, reason, next_stage}

### 2.2 面试官路由评分（interviewer_config.py → interviewer_profiles）

MockMate 为面试官定义 `aggressiveness`、`follow_up_depth` 等参数。

**v2 实现**：
- 预设 3 种面试官风格：友好型（默认）/ 严格型 / 压力型
- 不同阶段自动匹配风格：技术面→严格 / 行为面→友好 / 综合面→压力
- 风格通过 System Prompt 注入，不改变诊断维度

### 2.3 五层安全防护简化版（security.py）

MockMate 有 5 层安全 Pipeline。v2 取其精华做轻量版：

**v2 实现**：
- **输入守卫**：检测用户回答中的 Prompt 注入关键词（如"忽略之前"、"你是一个"等），标记为可疑
- **输出守卫**：扫描 AI 响应中是否包含 System Prompt 片段泄漏
- **不做的**：状态机校验、记忆污染——这些在单用户场景下 ROI 不足

### 2.4 WebSocket 流式诊断（stream_chat.py 思路）

MockMate 的 WebSocket 推送题目、评分、阶段变更通知。

**v2 实现**：
- 新增 `/ws/diagnose/{session_id}` WebSocket 端点
- 诊断过程分步推送：`{"type":"start"} → {"type":"diagnostician","content":"..."} → {"type":"rewriter","content":"..."} → {"type":"done","result":{...}}`
- 前端展示实时诊断进度（"正在分析 STAR 完整性..." → "正在生成改写建议..."）
- 追问也走 WebSocket 通道

### 2.5 前端模块化 + Chart.js 雷达图

MockMate 的前端有 12 个 JS 文件。v2 不做到那个程度，拆 5-6 个即可。

**v2 实现**：
```
frontend/
├── index.html              # 骨架 + 页面结构
├── css/style.css           # 所有样式
└── js/
    ├── app.js              # 主入口 + Tab切换 + 状态管理
    ├── api.js              # HTTP/WebSocket API 封装
    ├── interview.js        # 面试主流程（多轮次 + 追问）
    ├── report.js           # 诊断报告 + Chart.js 雷达图
    ├── history.js          # 历史记录
    └── utils.js            # 工具函数
```

---

## 三、技术方案

### 3.1 诊断引擎升级

v1 是 `run_diagnosis()` 一次性返回结果。v2 升级为：

```
async def run_streaming_diagnosis(ws, question, answer, resume, jd):
    yield {"type": "status", "phase": "diagnosing"}
    # Agent 1: Diagnostician（流式输出）
    diagnosis = await run_diagnostician(question, answer, resume, jd)
    yield {"type": "diagnosis_chunk", "data": diagnosis}
    
    yield {"type": "status", "phase": "rewriting"}
    # Agent 2: Rewriter
    rewrite = await run_rewriter(question, answer, diagnosis, resume, jd)
    yield {"type": "rewrite_chunk", "data": rewrite}
    
    yield {"type": "done", "result": {"diagnosis": diagnosis, "rewrite": rewrite}}
```

### 3.2 面试引擎（interview_engine.py，核心新模块）

职责：
1. 按轮次管理面试流程（技术面 → 行为面 → 综合面）
2. 每轮开始时调用 `question_gen` 生成该轮专属题目
3. 接收回答 → 调用诊断 → 决定追问或推进
4. 回答过短（<30字）自动触发追问
5. 汇总多轮结果生成综合报告

### 3.3 数据模型扩展

新增表：
- `session_rounds`：记录轮次信息（round, stage, created_at）
- 扩展 `questions`：增加 `round` 字段

---

## 四、不做的（范围纪律）

- 语音交互（TTS/ASR）— 需用户明确批准
- 多 AI 提供商切换 — 当前 DeepSeek 满足需求
- 用户认证系统 — 增加复杂度，ROI 不足
- LoRA 微调数据采集 — 需用户明确批准
- HTTPS/局域网访问 — 部署阶段再考虑
- 模拟 MockMate 的"9 阶段"流程 — 过度设计，v2 用 3 轮次足矣

---

---

## 修改记录 [2026-07-31 实施完成]

### 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/schemas.py` | 重写 | 新增 v2 模型：面试官风格、轮次配置、综合报告、WS 消息 |
| `backend/config.py` | 重写 | 新增：追问阈值、3 轮次定义、3 种面试官风格预设 |
| `backend/llm_client.py` | 升级 | 新增 `chat_stream()` 流式输出 |
| `backend/security.py` | **新建** | 输入守卫（40+ 注入模式）+ 输出守卫（泄漏检测） |
| `backend/interview_engine.py` | **新建** | 多轮面试引擎：状态机 + 追问 + 报告 |
| `backend/question_gen.py` | 升级 | 新增 `generate_round_questions()` 按轮次出题 |
| `backend/diagnosis_engine.py` | 升级 | 新增 `run_diagnosis_streaming()` 流式诊断 |
| `backend/db.py` | 升级 | 新增 5 张表：`diagnosis_v2`、`round_summaries`、`comprehensive_reports`等 |
| `backend/main.py` | 重写 | 新增 WebSocket 端点 `/ws/interview/{session_id}` |
| `frontend/index.html` | 重写 | SPA 骨架（Tab 布局） |
| `frontend/css/style.css` | **新建** | 全局样式 |
| `frontend/js/app.js` | **新建** | 主入口 |
| `frontend/js/api.js` | **新建** | HTTP + WebSocket API 封装 |
| `frontend/js/interview.js` | **新建** | 面试流程控制 |
| `frontend/js/report.js` | **新建** | 综合报告 + Chart.js 雷达图 |
| `frontend/js/history.js` | **新建** | 历史记录 |
| `frontend/js/utils.js` | **新建** | 工具函数 |
| `requirements.txt` | 升级 | 新增 `websockets>=12.0` |
| `run.py` | 更新 | 版本号更新 |
| `CODEBUDDY.md` | 更新 | 项目结构、v2 架构说明 |

### 架构决策记录

1. **WebSocket 流程设计**：由 handler（main.py）驱动引擎（interview_engine.py）的交互流程。引擎只负责状态管理和运算，不做循环等待。这避免了 run() 方法内的阻塞问题。
2. **追问触发条件**：回答 < 30 字 或 综合分 < 2.5，单题最多追问 2 次。这些参数在 `config.py` 中可调。
3. **轮次推进策略**：当前轮所有题答完 → 进入下一轮。在 v1.1 中可引入"评分阈值推进"。
4. **前端模块粒度**：5 个 JS 模块（不含 CSS），比 MockMate 的 12 个精简。原因：我们只有 3 个 Page，不需要过度拆分。

### 已知限制 / 后续可优化

- 追问不是在流式诊断结束时自动推送，而是诊断完成后独立发送。可在后续版本合并。
- 雷达图按轮次展示，每轮一个 dataset，不支持实时更新。（Chart.js 重建可解决）
- 面试引擎的 `start_round()` 是 async 的，题目生成需要等待 LLM 响应，前端在此期间显示 loading 状态。
- 未做 HTTPS，局域网访问可使用 `--host 0.0.0.0`。

---

## 五、涉及的知识点

- FastAPI WebSocket 异步编程
- Chart.js 雷达图配置
- 流式 LLM 输出（SSE/WebSocket 推送）
- Prompt 注入检测（正则 + 关键字）
- 前端模块化（原生 ES Module）
- 多轮面试流程编排
- 轻量追问决策逻辑

---

## v2.1 修改记录 [2026-07-31]

### 迭代目标

| 功能 | 来源 | 说明 |
|------|------|------|
| 质量驱动推进 | MockMate mock_state.py | 轮次平均分达标才推进，不达标追加题目 |
| 安全层深化 | MockMate security.py | v2:2层 → v2.1:4层（注入/泄露/状态校验/记忆防污染） |
| 多AI后端切换 | MockMate 多后端架构 | 支持 DeepSeek/Qwen/智谱/OpenAI 运行时切换 |

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/config.py` | 升级 | 新增 `AI_PROVIDERS` 多后端定义；轮次配置新增 `min_questions`/`advance_threshold`/`max_extra_questions` |
| `backend/llm_client.py` | 升级 | 新增 `switch_provider()`、`get_provider_info()`、`list_providers()`；构造函数接受 provider 参数 |
| `backend/security.py` | 升级 | 注入模式 40→53 条；新增第3层状态校验（重复检测/Jaccard相似度/质量校验）；新增第4层记忆防污染 |
| `backend/interview_engine.py` | 升级 | 新增 `check_round_quality()` / `generate_extra_question()` / `_current_round_avg_score()` / `_total_questions_answered()` |
| `backend/main.py` | 升级 | 新增 `GET /api/providers` + `POST /api/switch-provider`；WebSocket handler 集成 `full_check()` 安全校验 + 质量驱动推进流程；新增 `security_block` / `round_quality_check` / `extra_question` 消息类型 |
| `frontend/js/interview.js` | 升级 | 新增 `showExtraQuestion()` / `showQualityCheck()` 函数；`showRoundSummary()` 显示质量检查结果；新增 `security_block` 消息处理 |
| `frontend/js/api.js` | 升级 | 新增 `getProviders()` / `switchProvider()` |
| `frontend/index.html` | 升级 | 版本号 v2 → v2.1 |
| `.env.example` | 升级 | 新增多后端配置（Qwen/智谱/OpenAI） |
| `CODEBUDDY.md` | 升级 | v2.1 架构说明 + 4 层安全说明 + 多后端说明 |

### 质量驱动推进设计

```
当前轮所有题答完
    ↓
has_more_questions()? → YES → 下一题
    ↓ NO
check_round_quality()
    ├─ answered < min_questions → 不检查，继续（但不加题）
    ├─ avg >= threshold → 通过 → round_summary → 下一轮
    ├─ avg < threshold & extra < max_extra → 追加题 → generate_extra_question()
    └─ avg < threshold & extra >= max_extra → 强制推进 → round_summary → 下一轮
```

参数按轮次配置：
- 技术轮: min_questions=2, threshold=2.5, max_extra=2
- 行为轮: min_questions=2, threshold=2.5, max_extra=2  
- 综合轮: min_questions=1, threshold=0 (始终通过), max_extra=0

### 安全 4 层体系

| 层 | 负责模块 | 功能 |
|----|---------|------|
| 1 | `check_input()` | 53 条注入正则：角色逃逸/Prompt盗取/越狱/编码绕过/面试专用注入 |
| 2 | `check_output()` | 13 条泄露检测：System Prompt/角色/维度关键词泄漏 |
| 3 | `check_repeated_answer()` + `check_answer_quality()` | Jaccard 相似度重复检测 + 空/垃圾/乱码过滤 |
| 4 | `check_memory_pollution()` | 10 条模式：检测改写历史/替换简历/撤回回答行为 |

`full_check()` 统一入口，WebSocket 收到 answer 消息时自动执行全部 4 层。

---

## v2.2 修改记录 [2026-07-31]

### 迭代目标

| 功能 | 来源 | 说明 |
|------|------|------|
| 6 阶段面试流程 | MockMate 多阶段设计 | 3 轮 → 6 阶段：破冰→技术广度→技术深度→项目拷问→行为面→反问收尾 |
| 题库管理系统 | MockMate 题库管理 | 完整 CRUD + 收藏 + 从会话导入 + 前端 Tab 页 |

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/config.py` | 升级 | INTERVIEW_ROUNDS 3→6 阶段；每阶段含独立 question_count/min_questions/advance_threshold/max_extra |
| `backend/question_gen.py` | 升级 | ROUND_PROMPTS 3→6 套，每阶段独立考察焦点 Prompt |
| `backend/interview_engine.py` | 升级 | 适配 6 阶段；`_get_weakest_dimensions()` 辅助追加题生成 |
| `backend/diagnosis_engine.py` | 升级 | 新增 `DiagnosisEngine` 类封装，为 InterviewSession 提供统一接口 |
| `backend/db.py` | 升级 | 新增 `question_bank` 表 + `add_question/update_question/delete_question/toggle_favorite/list_questions/import_questions_from_session` |
| `backend/question_bank.py` | **新建** | 题库 CRUD 业务逻辑（含阶段类型校验、从会话导入） |
| `backend/main.py` | 升级 | 新增 6 个题库 API 端点；WebSocket 适配 6 阶段；修复 DiagnosisEngine 导入 |
| `backend/schemas.py` | 升级 | 新增题库相关模型 + SessionCreateResponse + ProviderInfo/ProviderListResponse/ProviderSwitchRequest |
| `frontend/js/questionBank.js` | **新建** | 题库管理前端模块（列表/新建/编辑/删除/收藏/导入） |
| `frontend/js/api.js` | 升级 | 新增 6 个题库 API 函数 |
| `frontend/js/app.js` | 升级 | 新增 question-bank Tab 路由 |
| `frontend/index.html` | 升级 | 新增"题库"Tab + question-bank-panel |
| `frontend/css/style.css` | 升级 | 新增题库表格/标签/编辑表单样式 |
| `CODEBUDDY.md` | 升级 | v2.2 架构说明 + 题库系统说明 + 范围更新 |

### 6 阶段面试流程

```
破冰环节 (1题, threshold=0)
  → 技术广度 (3题, threshold=2.5, max_extra=2)
    → 技术深度 (3题, threshold=2.5, max_extra=2)
      → 项目拷问 (2题, threshold=2.5, max_extra=1)
        → 行为面试 (2题, threshold=2.5, max_extra=1)
          → 反问收尾 (1题, threshold=0)
```

每阶段独立 Prompt，聚焦不同考察角度：
- 破冰：氛围建立 + 简历确认
- 技术广度：知识面覆盖
- 技术深度：原理理解
- 项目拷问：STAR 真实性验证
- 行为面试：软技能
- 反问收尾：候选人提问

### 题库管理系统架构

```
DB: question_bank 表
  ├─ round_type (阶段类型)
  ├─ question_text (题目正文)
  ├─ intent (考察意图)
  ├─ tags (标签 JSON)
  ├─ difficulty (1-5)
  ├─ source (manual / ai_generated)
  ├─ is_favorited (收藏)
  └─ usage_count (使用次数)

API:
  GET    /api/question-bank              列表（支持 round_type/difficulty/favorited/search/source 过滤）
  POST   /api/question-bank              新建
  PUT    /api/question-bank/{id}         更新
  DELETE /api/question-bank/{id}         删除
  POST   /api/question-bank/{id}/favorite 切换收藏
  POST   /api/question-bank/import       从会话导入

前端 Tab "📚 题库":
  - 过滤栏（阶段下拉/搜索输入/收藏切换）
  - 题目列表（表格显示：收藏/阶段/题目/意图/难度/使用/操作）
  - 新建/编辑表单（阶段选择、难度滑块、文本输入）
  - 导入表单（输入 Session ID 导入）
```

---

## v2.3 修改记录 [2026-07-31]

### 迭代目标

| 功能 | 说明 |
|------|------|
| TTS 朗读题目 | 面试官提问后自动朗读，可点击 🔊 重播 |
| STT 语音输入 | 点击 🎤 用语音输入回答，实时转写 |

### 技术方案

基于浏览器内置 **Web Speech API**，完全前端实现，无需后端改动：

- **SpeechSynthesis** → TTS：优先选中中文女声，语速 0.9x
- **SpeechRecognition** → STT：continuous + interimResults，追加模式拼接多次录音

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/js/voice.js` | **新建** | 语音交互模块：TTS 朗读、STT 语音转文字、状态管理 |
| `frontend/js/interview.js` | 升级 | 集成语音：自动读题、回答区麦克风按钮、追问语音输入、状态联动 |
| `frontend/css/style.css` | 升级 | 语音按钮样式：圆形按钮、朗读脉冲动画、录音脉冲动画、输入框录音态 |
| `frontend/index.html` | — | 无需改动（动态生成） |
| `CODEBUDDY.md` | 升级 | v2.3 版本号 + 语音交互说明 + 范围更新 |

### 语音交互流程

```
问题到达 → autoReadQuestion() → TTS 朗读（🔊 按钮变活跃态）
    ↓
用户可点击 🔊 重播/停止朗读
    ↓
用户点击 🎤 → startListening() → 实时转写填入 textarea
    ↓                               ↓
textarea 边框变红 + 脉冲动画      中间结果显示在 placeholder
    ↓
用户再次点击 🎤 停止录音（或说"结束"等自然语言信号）
    ↓
用户编辑/确认文字 → 提交
    ↓
提交时自动 stopSpeaking() + stopListening()
```

---

## v2.4 修改记录 [2026-07-31]

### 迭代目标

对比 GitHub MockMate 仓库后，补齐 P0 差距：

| 功能 | 说明 |
|------|------|
| 双模式面试 | 拟真模式（6阶段）+ 传统模式（5轮次：笔试→技术一→技术二→综合→自定义） |
| 7 种面试官角色 | 友好/严格/压力/专业/好奇/质疑/鼓励，各有 attack_level 和 interrupt_prob |
| 自动切换面试官 | 传统模式每轮自动切换，切换时 WS 推送 interviewer_change 事件 |

### 技术方案

- **双模式**：InterviewSession 新增 `mode` 参数，根据模式选择 rounds 和 prompts
- **面试官配置**：7 种 `INTERVIEWER_STYLES`，每种包含 `attack_level`(1-5) 和 `interrupt_prob`
- **自动切换**：每轮 `round_start` 后调用 `get_interviewer_change_event()`，风格变化时推送事件

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/config.py` | 升级 | +TRADITIONAL_ROUNDS(5轮) + 扩展 INTERVIEWER_STYLES(3→7) + INTERVIEW_MODES |
| `backend/question_gen.py` | 升级 | +TRADITIONAL_ROUND_PROMPTS(5套) + mode参数支持 |
| `backend/interview_engine.py` | 升级 | +mode参数 + interviewer_change + interviewer_history |
| `backend/schemas.py` | 升级 | SessionCreateRequest + mode字段；SessionCreateResponse + mode字段 |
| `backend/main.py` | 升级 | 传递mode；WS推送interviewer_change事件；版本号更新 |
| `frontend/js/api.js` | 修复 | generateQuestions 调用 POST /api/sessions (原/api/generate不存在) |
| `frontend/js/interview.js` | 升级 | +模式选择器 + 面试官切换动画 + interviewer_change处理 |
| `frontend/css/style.css` | 升级 | +模式选择器样式 + 面试官卡片样式 + 切换动画 |
| `frontend/index.html` | 升级 | v2.4 版本号 |
| `CODEBUDDY.md` | 升级 | v2.4 版本号 + 双模式/面试官说明 + 范围更新 |

---

## v2.5 修改记录 [2026-07-31]

### 迭代目标

继续对齐 GitHub MockMate 项目差距（P1/P2 级别）：

| 功能 | 优先级 | 说明 |
|------|:---:|------|
| 岗位画像研究 | P1 | DuckDuckGo 搜索 + LLM 分析岗位需求，自动丰富 JD |
| 诊断反馈 👍/👎 | P1 | 每轮诊断提供点踩/点赞，记录反馈数据 |
| 引擎模块化 | P2 | interview_engine.py 拆分为 interview_engine/ 子包 |

### 技术方案

**岗位画像研究**：
- 使用 DuckDuckGo Instant Answer API（免费无 Key）
- 创建会话时自动搜索职位信息 → LLM 提炼核心技能+热门话题
- 丰富后的 JD 注入面试流程

**诊断反馈**：
- 新增 `diagnosis_feedback` 表（session_id/round_idx/question_idx/feedback_type）
- `POST /api/feedback` + `GET /api/feedback/{session_id}`
- 前端诊断面板底部 👍/👎 按钮，异步提交，静默失败

**引擎模块化**：
- `interview_engine.py` → `interview_engine/__init__.py` + `session.py` + `report.py`
- 向后兼容，main.py 导入路径不变

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/web_research.py` | **新建** | DDG 搜索 + LLM 岗位分析 |
| `backend/interview_engine/__init__.py` | **新建** | 子包入口，导出 InterviewSession |
| `backend/interview_engine/session.py` | **新建** | 从旧文件提取的核心状态机 |
| `backend/interview_engine/report.py` | **新建** | 从旧文件提取的报告生成模块 |
| `backend/interview_engine.py` | **删除** | 替换为子包 |
| `backend/db.py` | 升级 | +diagnosis_feedback 表 + 3个反馈操作函数 |
| `backend/schemas.py` | 升级 | +DiagnosisFeedbackRequest + FeedbackStatsResponse |
| `backend/main.py` | 升级 | +反馈端点 + 岗位研究端点 + JD自动丰富 + v2.5版本号 |
| `frontend/js/api.js` | 升级 | 导出 request 函数 |
| `frontend/js/interview.js` | 升级 | +反馈按钮 + submitFeedback + currentSessionId |
| `frontend/css/style.css` | 升级 | +反馈按钮样式 + 岗位研究提示样式 |
| `frontend/index.html` | 升级 | v2.5 版本号 |
| `CODEBUDDY.md` | 升级 | v2.5 文档完整更新 |
