# AI模拟面试官 v3.1

> 本文档是 CodeBuddy 的项目记忆文件，每次新对话自动加载。请在接手本项目时严格遵循以下规范。

---

## 项目概览

**核心价值**：回答质量诊断，不是"像不像面试官"。**v2 新增**：多轮面试流程、WebSocket 流式诊断、面试官角色、追问机制。**v2.1 新增**：质量驱动推进、4 层安全防护、多 AI 后端可切换。**v2.2 新增**：6 阶段面试流程、题库管理系统。**v2.3 新增**：语音交互（TTS + STT）。**v2.4 新增**：双模式面试（拟真/传统）+ 7 种面试官角色自动切换。**v2.5 新增**：岗位画像研究 + 诊断反馈 👍/👎 + 引擎模块化拆分。**v2.6 新增（深化诊断核心）**：诊断维度权重按 JD 动态化 + 追问与诊断流式合并 + 雷达图实时更新 + 弱项自动追加针对性题。**v3.1 新增（生产级加固）**：Web 安全频率限制 + JD 权重 SHA256 缓存 + 数据预热 + 分层依赖约束 + 市场数据注入出题 + 跨岗位对比 + Gap 分析市场基准参照。

**技术栈**：Python 3.12 / FastAPI + WebSocket / SQLite (aiosqlite) / 多 AI 后端 (DeepSeek/Qwen/智谱/OpenAI) / 原生 ES Module 前端 + Chart.js / logging + RotatingFileHandler (5MB×3 旋转)

---

## 项目结构

```
AI模拟面试官/
├── CODEBUDDY.md              # 项目记忆文件
├── .env                      # 环境变量（不提交 Git）
├── .env.example              # 环境变量模板
├── .gitignore
├── requirements.txt          # Python 依赖
├── run.py                    # 一键启动脚本
├── backend/
│   ├── logger.py             # [v3.1 NEW] 集中日志配置：RotatingFileHandler + 控制台
│   ├── main.py               # FastAPI 入口 + HTTP/WebSocket 路由 (v3.1: slowapi 频率限制)
│   ├── llm_client.py         # 多 AI 后端客户端（含流式）
│   ├── db.py                 # SQLite 多表操作 (v3.1: jd_weights_cache 表)
│   ├── schemas.py            # Pydantic 请求/响应模型 (v3.1: 跨岗位对比模型)
│   ├── resume_parser.py      # 简历解析（PDF/DOCX/TXT）
│   ├── question_gen.py       # 问题生成 (v3.1: 市场数据注入)
│   ├── diagnosis_engine.py   # 双 Agent 诊断引擎 (v2.6: 权重注入 + 流式 + 追问合并)
│   ├── gap_analyzer.py        # [v3.1 NEW] 简历-岗位六维度 Gap 分析 + 市场基准参照
│   ├── dimension_weights.py  # [v2.6 NEW] 诊断维度动态权重 (v3.1: SHA256 缓存查重)
│   ├── interview_engine/     # [v2.5] 面试引擎子包（模块化拆分）
│   │   ├── __init__.py       # 导出 InterviewSession
│   │   ├── session.py        # InterviewSession 核心状态机 (v2.6: 补齐接口 + 权重/弱项/雷达)
│   │   └── report.py         # 综合报告生成 (v2.6: 加权总分 + 权重明细)
│   ├── question_bank.py      # 题库管理 CRUD
│   ├── web_research.py       # [v2.5 NEW] 岗位画像研究（DDG搜索+LLM分析）
│   ├── security.py           # 5 层安全防护 (v3.1: +频率限制)
│   ├── data_support.py       # 技能匹配
│   └── skills_data.json      # 岗位技能静态数据
├── frontend/
│   ├── index.html            # SPA 骨架（Tab 式布局）(v3.1 版本号)
│   ├── css/
│   │   └── style.css         # 全局样式 (v3.1: Gap分析横条)
│   └── js/
│       ├── app.js            # 主入口 + Tab 切换
│       ├── api.js            # HTTP API + WebSocket 封装 (v3.1: getGapAnalysis)
│       ├── interview.js      # 面试流程控制 (v2.6: 流式渲染 + 权重展示)
│       ├── voice.js          # [v2.3 NEW] 语音交互（TTS + STT）
│       ├── liveRadar.js      # [v2.6 NEW] 面试进行中的实时雷达图
│       ├── report.js         # 综合报告 + Chart.js 雷达图 (v3.1: Gap分析区块)
│       ├── history.js        # 历史记录查看
│       ├── questionBank.js   # 题库管理界面
│       └── utils.js          # 工具函数
├── tests/                    # [v3.1 NEW] 自动化测试 (50 用例)
│   ├── conftest.py           # 共享 fixtures
│   ├── test_schemas.py       # Schema 验证 (11 测试)
│   ├── test_gap_analyzer.py  # Gap 分析器 (21 测试)
│   └── test_api.py           # HTTP 路由 (18 测试，含安全测试)
├── data/
│   └── interview.db          # SQLite 数据库（v2 多表结构）
└── docs/                     # 需求文档与周报
```

---

## 常用命令

```bash
# 启动开发服务器（端口 8000，热重载）
python run.py

# 或直接启动
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 安装依赖
pip install -r requirements.txt

# 访问 API 文档
# http://localhost:8000/docs
```

---

## 架构约束（必须遵守）

### 双 Agent 不可合并
Diagnostician + Rewriter 是两个独立 Agent，**禁止合并为单一 Agent**。诊断和改写必须分步进行，各自有独立的 prompt。

### 分层依赖约束（v3.1 新增）
目录不作为强制的物理分层，但导入方向必须遵守**逻辑分层**。下半层禁止 import 上半层：

| 层级 | 模块 | 允许依赖 |
|---|---|---|
| L1 基础设施 | `config.py` `logger.py` `llm_client.py` `db.py` | 仅标准库 / 三方库，**无项目内 import**（config 除外） |
| L2 领域模型 | `schemas.py` `security.py` `resume_parser.py` `dimension_weights.py` `gap_analyzer.py` | 仅 L1 (`from .config import ...` `from .db import ...`) |
| L3 业务逻辑 | `question_gen.py` `diagnosis_engine.py` `interview_engine/*` `web_research.py` `market/*` `question_bank.py` `data_support.py` | L1 + L2，禁止 import L4 |
| L4 应用入口 | `main.py` | 所有层 |

**反模式**（必须避免）：
- L2 模块 `from .main import ...` — 绝对禁止
- L3 模块 `from backend.config import ...` — 应改为相对 import `from .config import ...`
- 循环 import：`session.py` ↔ `main.py` 通过函数参数注入打破循环（v2.6 就是踩了这个坑）

**检查清单**：每次新增/重构模块后，随机抽查 2-3 条 import 确认未越层。

### 诊断维度
诊断始终围绕五个维度评分：
1. STAR 完整性
2. 量化程度
3. 逻辑连贯性
4. 岗位相关性
5. 专业深度

### v2 新增架构组件

### WebSocket 端点：`/ws/interview/{session_id}`
消息协议状态机由 `main.py` 的 handler 驱动，`interview_engine.py` 管理状态与运算。

### 面试引擎（interview_engine.py）
状态机管理 **双模式**面试流程（拟真6阶段 / 传统5轮次），含：
- 按阶段生成专属题目（6+5 套独立 Prompt）
- 流式双 Agent 诊断
- 轻量追问决策（回答<30字 或 评分<2.5 触发）
- **v2.1: 质量驱动推进** — 阶段平均分未达阈值自动追加题目（每阶段可配置 min_questions / advance_threshold / max_extra）
- **v2.2: 6 阶段流程** — 借鉴 MockMate 多阶段设计，破冰→技术广度→技术深度→项目拷问→行为面→反问收尾
- **v2.4: 双模式面试** — 新增传统5轮次模式（笔试→技术一面→技术二面→综合→自定义），前端可选
- **v2.4: 7 种面试官角色** — 友好/严格/压力/专业/好奇/质疑/鼓励，各配攻击性等级和打断概率，每轮自动切换
- 综合报告生成（各维度趋势 + 强项/弱项 + 建议 + 面试官历程）

### 安全防护（security.py）
**v2.1: 4 层防护体系**：
1. **输入注入检测**：50+ 正则模式（角色逃逸/Prompt盗取/越狱/编码绕过/面试专用注入）
2. **输出泄露检测**：检测 System Prompt 片段泄漏
3. **状态异常校验**：重复回答检测（Jaccard 相似度）+ 内容质量校验
4. **记忆防污染**：检测试图改写历史/替换简历/撤回回答的行为

### 多 AI 后端（config.py + llm_client.py）
- **v2.1 新增**：支持 DeepSeek / 通义千问 / 智谱 GLM / OpenAI 四后端切换
- API: `GET /api/providers` 列出可用后端，`POST /api/switch-provider` 运行时切换
- 通过 `.env` 的 `AI_PROVIDER` 或运行时 API 切换

### 题库管理系统（question_bank.py + db.py）
**v2.2 新增**：完整的题库 CURD 管理
- DB 表 `question_bank`：含阶段类型、题目文本、考察意图、标签、难度、来源、收藏、使用次数
- API 端点：
  - `GET /api/question-bank` — 列出题目（支持过滤：阶段/难度/收藏/搜索/来源）
  - `POST /api/question-bank` — 创建题目
  - `PUT /api/question-bank/{id}` — 更新题目
  - `DELETE /api/question-bank/{id}` — 删除题目
  - `POST /api/question-bank/{id}/favorite` — 切换收藏
  - `POST /api/question-bank/import` — 从会话导入题目
- 前端：独立的"题库"Tab 页面，含过滤栏、题目列表、新建/编辑表单、导入功能

### 前端模块化
8 个 JS 模块（ES Module）+ 独立 CSS，使用 Chart.js 雷达图展示各维度趋势。

### 语音交互（voice.js）[v2.3 NEW]
基于浏览器内置 **Web Speech API**，无需后端支持：
- **TTS（文字转语音）**：面试官题目自动朗读，可点击 🔊 按钮重播
  - 优先选择中文女声，语速 0.9x
  - 朗读时按钮有脉冲动画
- **STT（语音转文字）**：点击 🎤 按钮语音输入回答
  - 实时转写（continuous + interimResults）
  - 追加模式：多次录音内容自动拼接
  - 录音时输入框边框变红 + 按钮脉冲动画
- 追问也支持语音输入
- 提交回答时自动停止所有语音

### 双模式面试 + 面试官切换 [v2.4 NEW]
**双模式**：
- **拟真模式**：原有 6 阶段大厂面试流程
- **传统模式**：笔试→技术一面→技术二面→综合面试→自定义环节（每轮独立面试官）

**7 种面试官角色**（含 attack_level 1-5 / interrupt_prob）：
1. 友好型 (attack:1) | 2. 严格型 (attack:3) | 3. 压力型 (attack:5)
4. 专业型 (attack:2) | 5. 好奇型 (attack:1) | 6. 质疑型 (attack:4) | 7. 鼓励型 (attack:1)

**自动切换机制**：
- 传统模式：每轮配有固定面试官风格，轮次切换时自动切换
- 拟真模式：可从配置指定每阶段面试官
- 切换时通过 WebSocket 发送 `interviewer_change` 事件
- 前端显示切换动画 + 面试官信息卡片（自动4秒淡出）

### 岗位画像研究（web_research.py）[v2.5 NEW]
- 创建会话时自动搜索岗位相关信息（DuckDuckGo API，免费无 Key）
- LLM 分析搜索结果，输出：丰富后的 JD、核心技能列表、热门面试话题
- 搜索结果自动注入 JD，使面试问题更贴合真实岗位需求
- 提供 `POST /api/research-position` 端点供手动触发

### 诊断反馈 👍/👎 [v2.5 NEW]
- 每轮诊断面板底部新增 👍/👎 反馈按钮
- 提交反馈写入 `diagnosis_feedback` 表，追踪会话级反馈
- API: `POST /api/feedback`、`GET /api/feedback/{session_id}`
- 反馈按钮提交后显示 ✓ 确认，2秒恢复

### 引擎模块化 [v2.5 NEW]
`interview_engine.py` 拆分为子包：
```
interview_engine/
├── __init__.py    # 导出 InterviewSession + build_report
├── session.py     # 核心状态机（Init/轮次控制/题目生成/追问/报告委托）
└── report.py      # 报告生成（各维度趋势/强项弱项/建议）
```
向后兼容：`from .interview_engine import InterviewSession` 保持不变。

---

## v2.6 深化诊断核心

> 详见 `docs/week4_深化诊断核心_需求.md`。本次不新增功能面，而是纵向加深核心诊断能力。

### 诊断维度权重按 JD 动态化（dimension_weights.py）
- **维度数量由架构约束定义**，此模块只调整各维度的**权重**
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
- **双 Agent 仍是两次独立调用，未合并**（遵守架构约束）
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

## v3.0 市场数据层深度改造

> 详见 `docs/week5_v3数据层_需求.md`

### 推翻"不复用约束"
原决策"不能复用 job-crawler data.db"被推翻：导入数据资产不等于复现代码，Playwright 重复采集纯粹浪费。

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

## v3.1 生产级加固（缺陷 #5-#12）

> 缺陷修复 (#5)：此前无文件持久化，出问题无法追溯历史

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

### Web 安全加固（#6）[v3.1 NEW]
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
在架构约束章节中明确 L1-L4 逻辑分层及导入方向规则（见上方"架构约束 > 分层依赖约束"）。

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

## 范围纪律
- **禁止**在未经用户明确批准的情况下新增功能模块
- 如认为某功能确有必要，只能以建议形式提出并等待用户批准，不得直接实现
- v2 已批准范围：多轮面试流程、WebSocket 流式诊断、面试官角色、追问、综合报告、前端模块化、Chart.js 雷达图、安全防护
- v2.1 已批准范围：质量驱动推进、安全层深化（4 层）、多 AI 后端切换
- v2.2 已批准范围：6 阶段面试流程、题库管理系统
- v2.3 已批准范围：语音交互（TTS 朗读题目 + STT 语音输入回答）
- v2.4 已批准范围：双模式面试（拟真/传统）+ 7 种面试官角色 + 自动切换
- v2.5 已批准范围：岗位画像研究 + 诊断反馈 👍/👎 + 引擎模块化拆分
- v2.6 已批准范围（用户主动提出）：诊断维度权重按 JD 动态化、追问与诊断流式合并、雷达图实时更新、弱项自动追加针对性题
- v3.0 已批准范围：市场数据层从"Playwright 自行采集"切换为"从 job-crawler 导入"，移除 playwright 依赖
- v3.1 已批准范围（缺陷修复 #5-#12）：集中日志配置（RotatingFileHandler）+ Web 安全频率限制 + JD 权重 SHA256 缓存 + 数据预热 + 分层依赖约束 + 市场数据注入出题 + 跨岗位对比 + Gap 分析市场基准参照
- **未来优化方向（课程项目阶段不做）**：用户认证系统、语音升级（云端 TTS/STT）、HTTPS / 局域网安全访问。三者经第一性原理评估均不提升诊断内核质量，属产品化 / 上云阶段事项，详见 `docs/week3_三个模块差距分析与阶段结论.md`。

---

## 开发纪律

### 模块开发前
每个功能模块开始前，先输出需求理解文档，存入：
```
docs/weekN_模块名_需求.md
```
内容包含：模块目标、技术方案、涉及的知识点。

### 修改迭代时
用户提出修改意见后，在对应需求文档里追加一段：
```
## 修改记录 [日期]
- 原方案：...
- 用户指出的问题：...
- 修改后的方案：...
```
这是评分中"批判性思维"分项的核心证据，必须真实、具体，不能用"优化了逻辑"这种空泛表述。
写入时必须显式写出**原方案的问题本质**与**用户批判性判断点**（依据/工程原则/取舍理由），而不只是复述指令。

### 批判性思维归纳（用户 2026-08-01 明确规则）
"批判性思维"作为**独立归纳维度**单列，不混在普通对话记录里。AI 在归档时须主动捕捉并标注用户的批判性思维信号：
- 指出某实现"不行/有漏洞/被绕过"（含主动要求做审计、复盘、对照标准核查）
- 对设计取舍提出质疑或推翻重来
- 在范围纪律上的克制判断（如"课程项目阶段不做"的取舍）
- 纠正 AI 的方向偏离

落点方式：
1. **周对话归档**（`docs/AI对话存档/weekN_AI对话归档.md`）：将此类 Session 的"用户提出"标注为 `[批判性思维]` 段，解析背后的判断依据与工程原则。
2. **修改记录段**（见上条）：必须写出问题本质 + 用户批判性判断点。
3. **项目收尾**（`docs/AI协作过程记录_完整版.md`）：单独开一章 **"批判性思维轨迹"**，按时间线汇总用户的关键质疑与决策反转。

### 每日整理文档（用户 2026-08-03 明确规则）
用户说"整理文档"时，表示当天任务收尾，须对当天对话进行结构化整理，内容包括：
1. **当天对话摘要**：按主题归纳本轮所有讨论内容（做了什么、改了什么、原因是什么）
2. **批判性思维摘录**：提取当天的用户质疑/审计/决策反转/方向纠正，标注为 `[批判性思维]` 并解析判断依据
3. **迭代记录追认**：检查当天是否有修改迭代，若对应的需求文档或周对话归档尚未写入修改记录段，在此补齐
4. **写入项目宪章**：将上述内容写入 CODEBUDDY.md 对应章节（如当日产生新的规则/纪律/约束，同步更新宪章），并写入当日日期的周对话归档 `docs/AI对话存档/weekN_AI对话归档.md`

执行时无需再次确认，直接整理后写入。若当天无实质性开发对话，简要记录"当日无新内容"即可。

### 推送前必做（用户 2026-08-01 明确规则）
用户说"推送更改"时，**默认**按以下顺序执行，无需再次确认：
1. **更新 README.md**：同步本轮改动（新增功能、修复记录、项目结构变化、安全加固等），确保文档与代码一致。
2. **更新 CODEBUDDY.md 相关部分**：若改动涉及架构约束、范围纪律、开发纪律、诊断维度等，同步更新本文件对应章节。
3. **推送到远端**：完成上述文档更新后再 `git push`。

> 例外：若用户当次明确说"只推代码/不要动文档"，则跳过文档更新步骤。

### Commit Message 规范
禁止使用"fix bug"、"优化代码"等空泛描述，必须写清楚：
```
改了什么: ...
为什么改: ...
```

### 变更前复述
用户指出问题后，须先复述问题本质，确认理解无误后再给出修改方案，不得跳过复述直接改代码。

### 周报
每周五（或用户指定的开发节点）自动生成周报，存入：
```
docs/weekN_周报.md
```

### 项目收尾
项目开发结束前，自动汇总所有需求文档和周报，按时间线整理成一份完整的《AI协作过程记录》：
```
docs/AI协作过程记录_完整版.md
```
汇总内容须包含独立章节 **"批判性思维轨迹"**（见上条"批判性思维归纳"规则），按时间线梳理用户的关键质疑、审计动作与决策反转。

---

## 边界声明

以下事项由用户本人负责，AI 只记录决策结果：
- 诊断维度的设计取舍
- 是否开发数据支撑模块
- 项目范围的增减
- 答辩叙事逻辑

---

## 开工自查清单

在新对话/会话中接手本项目时，开始工作前请确认：
1. 是否已阅读 `docs/` 目录下已有的需求文档和周报
2. 是否清楚当前处于第几周、上一次的修改记录是什么
3. 是否遵循本文件的记录规范
