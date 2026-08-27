# 变更日志（CHANGELOG）

> 记录 v2 → v4.0 的版本迭代叙事（新增/推翻/修复/范围）。不变的架构约束与决策记录见 [CHARTER.md](CHARTER.md)，日常协作入口见 [CODEBUDDY.md](CODEBUDDY.md)。

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
