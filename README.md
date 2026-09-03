
<h1 align="center">🤖 AI 求职领航</h1>

<p align="center">
  <strong>从职业定位到拿 Offer 的全流程 AI 陪跑系统</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/fastapi-0.110+-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/docker-supported-blue.svg" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/status-active-success.svg" alt="Status">
</p>

<p align="center">
  市场洞察 · 简历岗位资产 · AI 多轮面试演练 · 五维诊断报告 · 长期记忆 · 职业规划
</p>

---

## 📑 目录

- [项目简介](#-项目简介)
- [核心特性](#-核心特性)
- [快速开始](#-快速开始)
  - [环境要求](#环境要求)
  - [安装与启动](#安装与启动)
  - [Docker 部署](#docker-部署标准化推荐)
  - [环境变量说明](#环境变量说明)
- [使用说明](#-使用说明)
- [项目结构](#-项目结构)
- [技术栈](#-技术栈)
- [API 参考](#-api-参考)
- [诊断体系](#-诊断体系)
- [面试模式](#-面试模式)
- [内容护栏](#-内容护栏启发式非安全边界)
- [测试策略](#-测试策略)
- [已知局限](#-已知局限)
- [贡献](#-贡献)
- [许可证](#-许可证)

---

## 📖 项目简介

AI 求职领航 是一个面向求职者的全流程陪跑系统，按五步主线组织：

**职业定位**（市场数据 + 岗位库）→ **简历准备**（简历库）→ **面试演练**（AI 多轮模拟面试：6 阶段拟真模式 / 5 轮次传统模式）→ **能力诊断**（围绕 **STAR 完整性、量化程度、逻辑连贯性、岗位相关性、专业深度** 五个维度实时诊断，生成改写建议与综合评分报告 + 长期记忆图谱）→ **发展路径**（时间轴职业路径）。

> 首屏为**能力档案**：以「求职档案」为领域核心，把三个能力模块从并列功能降级为档案的读写者，形成「目标 → 现状 → 差距 → 行动 → 复测」的陪跑闭环。

## ✨ 核心特性

- **求职档案领域核心**：以档案为中心聚合「当前简历 / 目标岗位 / 能力水平 / 待提升项」，用六条规则表产出**下一步建议**（纯函数、零延迟、可解释，不调 LLM），形成「目标 → 现状 → 差距 → 行动 → 复测」闭环。档案是**投影**而非新真相源，不新增宽表双写
- **五维诊断**：STAR 完整性 / 量化程度 / 逻辑连贯性 / 岗位相关性 / 专业深度，权重按 JD 动态调整；每个维度附**候选人原话引用**，把主观打分锚定到可复核证据
- **双 Agent 协作**：Diagnostician（诊断评分）与 Rewriter（改写示范）独立分步，避免同一模型为产出漂亮改写而调高自评分
- **拟真面试流程**：6 阶段拟真模式（破冰 → 技术广度 → 技术深度 → 项目拷问 → 行为面 → 反问）与 5 轮次传统模式，7 种面试官风格，会话中可随时切换模式与阶段
- **语音交互**：小米 MiMo 云端 TTS/ASR 优先，未配 Key 或失败自动降级浏览器原生语音；含 VAD 预滚噪声校准、电平可视化、免手模式
- **简历证据检索**：本地关键词 + 优先级加权检索，为追问与诊断实时产出证据包，硬约束模型只依据简历证据或亲述评价，杜绝编造经历
- **不会答恢复**：检测到候选人示弱（不会 / 不懂 / 没思路）自动切换辅导式引导，而非机械继续追问
- **长期记忆闭环**：薄弱点跨场累计并做 EMA 衰减与过期淘汰，回注入后续面试；2D 记忆图谱可视化 + 复习建议
- **市场数据**：内嵌 Playwright 实时采集（支持全国范围）+ 存量数据导入，含岗位检索、统计概览、图表 AI 解读、收藏落库
- **Gap 分析与跨岗位对比**：简历-岗位六维透明匹配（技能 / 城市 / 学历 / 经验 / 薪资 / 可信度）+ 一份简历对多个岗位的排名与择岗建议
- **职业规划**：以 Gap 快照为基线，LLM 推理多阶段时间轴路径（需补技能 / 里程碑 / 岗位跃迁），并注入薄弱点与技能缺口上下文
- **简历库 / 岗位库**：跨会话复用的输入资产，一次上传解析、反复选用，不必重复上传
- **题库**：题目 CRUD、收藏、从历史会话导入
- **多 AI 后端与优雅降级**：DeepSeek / 通义千问 / 智谱 GLM / OpenAI 可切换，`AI_PROVIDER=auto` 自动探测；主模型失败按回落链自动切换备用模型，调用方无感知
- **工程保障**：import-linter 强制 L1–L4 分层契约、1000+ pytest 用例（含黄金样本评测与 live-LLM 抽检）、前端 vitest、GitHub Actions CI

---

## 🚀 快速开始

### 环境要求

- Python 3.12+
- 至少一个 LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com/)）

### 安装与启动

```bash
# 1. 克隆仓库
git clone https://github.com/cloudy-one1/AI-simulated-interviewer.git
cd AI-simulated-interviewer

# 2. 创建虚拟环境（推荐）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 Playwright 浏览器（市场数据 Tab 实时采集需要；跳过则实时采集不可用，
#    岗位库检索 / Gap 分析 / 跨岗位对比不受影响）
python -m playwright install chromium

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key（至少配置一个 AI 后端）
# 可选：填入 MIMO_API_KEY 启用小米 MiMo 云端语音（更自然的朗读 + 跨浏览器语音识别）；
#       不配置则自动使用浏览器原生语音
# MiMo 端点：https://api.xiaomimimo.com/v1（sk- 开头 Key 走按量付费集群）
# 可选音色：MIMO_TTS_VOICE=冰糖（默认）/ 茉莉 / 苏打 / 白桦 / Mia / Chloe / Milo / Dean

# 6. 启动服务
python run.py
```

前端开发模式（可选，提供热更新）：

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173（自动代理 /api /ws /upload 到 :8000）
npm run build   # 产出 dist/，由 FastAPI 托管（http://localhost:8000）
npm run test    # 前端 vitest 套件
```

> ⚠️ **改完前端必须执行 `npm run build`**：`run.py` 托管的是 `frontend/dist`（不入库），只改 `src/` 不构建的话界面不会变化。

启动后访问：
- 🎯 **面试页面**：http://localhost:8000（生产构建）或 http://localhost:5173（开发热更新）
- 📚 **API 文档**：http://localhost:8000/docs

### Docker 部署（标准化，推荐）

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 2. 构建并启动
docker compose up -d

# 3. 查看日志
docker compose logs -f

# 4. 停止
docker compose down
```

**数据持久化**：`./data/` 目录挂载到容器内，面试记录、题库、上传文件均存储在宿主机，容器销毁后数据不丢失。

**更新部署**：

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

**多 Worker 部署**（高并发场景）：

```bash
# 编辑 .env，设置 worker 数量（建议 ≤ CPU 核数）
UVICORN_WORKERS=4
docker compose up -d
```

> 注意：多 Worker 模式下 WebSocket 需要 sticky session；单机自用场景单 Worker 即可。

### 环境变量说明

`.env` 支持四种 AI 后端，至少配置一种：

```bash
# 通用配置（优先使用）
AI_PROVIDER=deepseek        # deepseek / qwen / zhipu / openai / auto
                            # auto = 按注册顺序自动探测第一个 Key 有效的后端

# DeepSeek（推荐，性价比较高）
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 通义千问
QWEN_API_KEY=sk-xxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# 智谱 GLM
ZHIPU_API_KEY=xxx
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPU_MODEL=glm-4-flash

# OpenAI
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# 模型调用优雅降级（fallback，可选）
# 主模型失败（限流 / 超时 / 不可用）时按序自动切换备用模型，调用方无感知
# 格式: "provider:model,provider:model,..."；留空 = 不降级（单模型）
# LLM_FALLBACK_CHAIN=deepseek:deepseek-chat,qwen:qwen-plus
# LLM_FALLBACK_MAX_RETRIES=3
```

---

## 🧑‍💻 使用说明

系统**只服务求职者**，定位为**单用户本地工具**：数据全存本机、全站免登录、一个视图。

1. **看能力档案**（默认首屏）：一眼看到「当前简历 / 目标岗位 / 能力水平 / 待提升项」，并给出**下一步建议**（先有简历 → 再定目标 → 再测能力 → 补短板 / 排路径）；能力画像下方是**成长曲线**（完成第二场模拟面试后开始显示轨迹），左侧旅程时间线显示五步走到哪一步。
2. **建立素材库**：「简历库」上传一次简历（完整入库，不截断）；「岗位库」保存常练的岗位 JD。之后每次开练直接选用，不必重复上传与解析。
3. **开练**：面试面板选择「从简历库选择」（或上传本机简历文件）与「从岗位库选择」（或上传 JD 文件）→ 开始面试。支持文字或语音作答，会话中可随时切换模式与阶段。
4. **复盘**：报告页的每维度评分附**候选人原话引用**（quote），可逐条核对「这个分凭什么」；复盘成果支持 Markdown / HTML 导出自用。

---

## 🏗️ 项目结构

```
AI求职领航/
├── run.py                        # 一键启动入口 + lint 子命令（import-linter）
├── README.md                     # 面向用户的完整说明（本文件）
├── .importlinter                 # 分层依赖契约（L1-L4）
├── .gitattributes                # 换行符统一为 LF（跨平台协作）
├── .github/workflows/ci.yml      # CI：分层契约 + 后端全量测试 + 前端单测 + 构建
├── Dockerfile                    # 容器镜像
├── docker-compose.yml            # Docker Compose 部署
├── .dockerignore                 # 容器构建忽略清单
├── requirements.txt              # Python 依赖（含 dev 依赖 import-linter）
├── .env.example                  # 环境变量模板
│
├── backend/                      # Python 后端
│   ├── main.py                   # FastAPI 应用装配（中间件/限流/启动/静态挂载）
│   ├── routers/                  # HTTP/WS 路由域拆分（system / voice / sessions /
│   │                             #   assets / reports / question_bank / diagnostics /
│   │                             #   market / analytics / profile / interview_ws
│   │                             #   + state 单例 + deps 依赖）
│   ├── config.py                 # 配置 + 面试官风格 + 轮次定义
│   ├── logger.py                 # 集中日志配置（RotatingFileHandler）
│   ├── llm_client.py             # 多 AI 后端客户端（含流式）
│   ├── db.py                     # SQLite 多表操作（aiosqlite）+ JD 权重缓存表
│   ├── schemas.py                # Pydantic 数据模型（含跨岗位对比）
│   ├── security.py               # 启发式内容检查
│   ├── diagnosis_engine.py       # 双 Agent 诊断引擎
│   ├── dimension_weights.py      # JD 动态维度权重（含 SHA256 缓存）
│   ├── gap_analyzer.py           # 简历-岗位 Gap 分析 + 市场基准参照
│   ├── career_planner.py         # 职业路径规划（以 Gap 为基线做多阶段推理）
│   ├── profile_service.py        # 求职档案领域核心（四段聚合 + 建议规则表 +
│   │                             #   五步完成度 + 技能缺口，L3）
│   ├── question_gen.py           # 问题生成（含市场数据注入）
│   ├── question_bank.py          # 题库 CRUD 管理
│   ├── resume_parser.py          # 简历解析（PDF/DOCX/TXT）
│   ├── web_research.py           # 岗位画像研究（DuckDuckGo）
│   ├── data_support.py           # 技能匹配数据
│   ├── skills_data.json          # 岗位技能静态数据
│   ├── knowledge_store.py        # 命名空间知识库（rag:interview / career / resume）
│   ├── voice_service.py          # MiMo 云端语音代理（TTS 合成 + ASR 识别）
│   ├── resume_retriever.py       # 简历证据检索器（分块/加权/预算/证据包）
│   ├── output_sanitizer.py       # 面试话术输出净化（禁 Markdown/舞台提示/垫词）
│   ├── resume_anchors.py         # 简历锚点五分类（技术选型/量化/架构/业务/团队）
│   ├── score_adjustments.py      # 评分规则化加减分项（确定性正则 + evidence）
│   ├── pressure_bank.py          # 压力题库（与简历/JD 解耦）
│   ├── company_profiles.py       # 公司风格配置层（YAML 热加载/JD 匹配/片段生成）
│   ├── company_profiles/         # 公司风格 YAML（内置字节/腾讯/阿里，加文件即加公司）
│   ├── weakness_memory.py        # 长期薄弱点 EMA 衰减 + 过期淘汰
│   ├── difficulty.py             # 动态难度调度器（轮内自适应）
│   ├── interview_skills.py       # 面试技能状态机（有状态多轮）
│   ├── market/                   # 市场数据子包
│   │   ├── cleaner.py            # 数据清洗
│   │   ├── importer.py           # 外部数据导入
│   │   ├── service.py            # 导入编排 + 岗位快照检索
│   │   ├── store.py              # 数据持久化
│   │   ├── analytics.py          # 图表数据聚合（给人看，与 get_stats 刻意分离）
│   │   ├── insight.py            # 图表 AI 解读（section 注册表 + TTL 缓存）
│   │   └── crawler/              # 内嵌实时采集（Playwright）
│   │       ├── python_job_scraper.py   # 采集核心
│   │       ├── salary_parser.py        # 薪资解析
│   │       ├── adapters.py             # 采集记录 → 标准 job dict + JD 组装
│   │       └── tasks.py                # 后台任务表（互斥/进度/TTL 清理）
│   └── interview_engine/         # 面试引擎子包
│       ├── session.py            # 核心状态机
│       ├── flow.py               # 流程状态显式化（decide_next 纯函数）
│       └── report.py             # 综合报告生成
│
├── frontend/                     # 原生 ES Module 前端（Vite 工程化，双入口）
│   ├── index.html                # SPA 骨架（主功能，默认首屏 = 能力档案）
│   ├── landing.html              # 独立产品落地页（根路径 `/` 由后端返回）
│   ├── package.json / vite.config.js / eslint.config.js
│   └── src/
│       ├── main.js               # Vite 入口（注入全局 Chart + 装配 app.js）
│       ├── assets/
│       │   └── china-geo.json    # 中国地图 GeoJSON（动态 import 懒加载，不进主包）
│       ├── js/
│       │   ├── app.js            # 主入口 + Tab 注册表 + 哈希路由（#/home 等）
│       │   ├── navConfig.js      # 导航单一数据源（五步旅程，侧栏与底部导航同源于此）
│       │   ├── profileCard.js    # 能力档案首屏（建议卡 / 五维画像 / 成长曲线 / 待提升项）
│       │   ├── api.js            # HTTP + WebSocket 封装
│       │   ├── interview.js      # 面试流程控制（setup 视图 / 对话流 / 诊断面板）
│       │   ├── liveRadar.js      # 实时五维雷达图
│       │   ├── report.js         # 综合报告 + Gap 分析 + 跨岗位对比
│       │   ├── history.js        # 历史记录
│       │   ├── questionBank.js   # 题库管理界面
│       │   ├── resumeLibrary.js  # 简历库（跨会话复用的输入资产）
│       │   ├── positionLibrary.js  # 岗位库
│       │   ├── careerPlan.js     # 职业规划 Tab（时间轴 + 阶段卡片 + 技能曲线）
│       │   ├── marketData.js     # 市场数据 Tab（采集/岗位库/详情/分析）
│       │   ├── cityCoords.js     # 城市坐标表（支撑市场数据地理可视化）
│       │   ├── memoryGraph.js    # 长期记忆 Tab（2D SVG 薄弱点图谱 + 明细联动）
│       │   ├── voice.js          # 语音交互（TTS + STT，世代号守卫真打断）
│       │   ├── themeToggle.js    # 全局主题切换器（手动深浅）
│       │   ├── landing.js        # 落地页动效总编排（three.js WebGL 墨晕 Hero /
│       │   │                     #   逐字揭示 / 磁性按钮 / 3D 倾斜 / 时间线，仅 landing.html 使用）
│       │   └── utils.js          # 工具函数（confirm 弹窗 / emptyState / 动效入口）
│       └── css/
│           ├── tokens.css        # Design Tokens（纸墨印章色值 + RGB 三元组）
│           ├── theme.css         # 主题样式（html.theme-dark「墨夜纸墨」覆盖层）
│           ├── motion.css        # 动效基建层（面板过渡/stagger/骨架屏/盖章/countup）
│           ├── surface.css       # 质感层（环境光/壳层玻璃/三级景深/渐变描边）
│           ├── layout.css        # 壳层布局（侧栏/底部导航 + 旅程时间线 + 进度条）
│           ├── base.css          # reset + 排版
│           ├── components.css    # 组件层
│           └── pages/            # 领域样式（market / memory / profile / report /
│                                 #   history / interview / landing）
│   ├── vitest.config.js          # 前端测试配置（environment: node，运行时全部打桩）
│   └── tests/
│       ├── voice.test.js         # 语音模块单测（世代号守卫/熔断韧性/VAD）
│       ├── interview.test.js     # 面试主循环 WS 消息派发契约
│       └── landing.test.js       # 落地页动效纯函数（逐字拆分/磁性偏移/倾斜角）
│
├── tests/                        # 后端自动化测试（1000+ 用例 + live_llm 抽检）
│   ├── conftest.py               # 共享 fixtures
│   ├── test_schemas.py           # Schema 验证
│   ├── test_api.py               # HTTP 路由集成测试
│   ├── test_gap_analyzer.py      # Gap 分析器
│   ├── test_dimension_weights.py # 维度权重
│   ├── test_resume_parser.py     # 简历解析
│   ├── test_report.py            # 报告生成
│   ├── test_security.py          # 内容护栏
│   ├── test_web_research.py      # 岗位画像研究
│   ├── test_data_support.py      # 技能匹配
│   ├── test_market_*.py          # 市场数据（清洗/导入/持久化/图表聚合与解读/采集）
│   ├── test_career_planner.py    # 职业规划（schema + 路由 + 降级路径）
│   ├── test_voice_*.py           # MiMo 语音服务与 /api/voice/* 代理路由
│   ├── test_session.py           # 会话状态机（追问/权重/薄弱点/恢复/多模式）
│   ├── test_resume_retriever.py  # 简历证据检索（分块/命中/预算/溯源）
│   ├── test_interview_ws.py      # WebSocket 面试主循环集成测试
│   ├── test_profile_service.py   # 求职档案聚合（建议规则表 / 技能缺口 / 成长曲线）
│   ├── test_profile_api.py       # /api/profile 与 /api/profile/refresh（缓存失效）
│   ├── test_diagnosis_golden.py  # 黄金样本评测（确定性回归 + live-LLM 抽检）
│   ├── test_repo_hygiene.py      # 仓库卫生（根目录白名单 / 坏链检测）
│   └── fixtures/golden_answers.json  # 黄金样本与人工标注
│
├── data/                         # 运行时数据（自动创建，不提交 Git）
└── LICENSE                       # MIT 许可证
```

---

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI + WebSocket + slowapi（频率限制） |
| **数据库** | SQLite（aiosqlite 异步驱动） |
| **AI 后端** | DeepSeek / Qwen / 智谱 GLM / OpenAI（可运行时切换） |
| **前端** | 原生 HTML5 + CSS3 + ES Module（无框架依赖）；three.js 仅限 landing 落地页（动态 import 拆 async chunk，主应用包不受影响） |
| **图表** | Chart.js v4（雷达图） |
| **语音** | 小米 MiMo 云端（TTS/ASR，需 `MIMO_API_KEY`）+ 浏览器 Web Speech API 降级 |
| **简历解析** | pdfplumber + python-docx |
| **岗位研究** | DuckDuckGo 搜索 + LLM 分析 |
| **岗位采集** | Playwright + playwright-stealth（`playwright install chromium`，内嵌 `market/crawler/`） |
| **日志** | logging + RotatingFileHandler（5MB×3 旋转） |
| **部署** | Docker + Docker Compose |
| **分层校验** | import-linter 契约（L1-L4，`run.py lint` 强制） |
| **测试** | pytest（后端 1000+ 用例 + live_llm 抽检）+ vitest（前端） |
| **CI** | GitHub Actions：分层契约 + 后端全量测试 + 前端单测 + 前端构建冒烟 |

---

## 🔌 API 参考

共 **59 个 HTTP 端点 + 1 个 WebSocket 端点**。

面试主循环走 WebSocket（`/ws/interview/{session_id}`），HTTP 端点负责准备素材与取结果。服务启动后访问 **`/docs`（Swagger UI）**，可看到由 Pydantic Schema 自动生成的完整交互式接口文档——字段级结构以它为准。

> 全站免登录，所有端点均不含身份概念。

---

## 📊 诊断体系

### 诊断维度

| 维度 | 说明 | 权重 |
|------|------|------|
| **STAR 完整性** | 情境-任务-行动-结果 四要素是否齐全 | JD 动态调整 |
| **量化程度** | 是否有具体数据支撑（数字、百分比、时间） | JD 动态调整 |
| **逻辑连贯性** | 叙事逻辑是否清晰、因果关系是否合理 | JD 动态调整 |
| **岗位相关性** | 回答与岗位要求的匹配度 | JD 动态调整 |
| **专业深度** | 技术理解是否深入、方案选型是否有洞见 | JD 动态调整 |

> 权重由 LLM 根据 JD 自动分析确定，范围 0.10–0.40，归一化后用于加权评分。

### 双 Agent 流程

```
用户回答 → Diagnostician（诊断 + 追问） → Rewriter（改写建议） → 前端展示
                   ↓                              ↓
              五维评分 + 追问                优化后的参考答案
```

---

## 🎭 面试模式

### 拟真模式（6 阶段）

| 阶段 | 内容 |
|------|------|
| 破冰 | 自我介绍 + 背景了解 |
| 技术广度 | 多领域基础能力考察 |
| 技术深度 | 核心技术栈深入追问 |
| 项目拷问 | 简历项目深度挖掘 |
| 行为面 | 团队协作/冲突处理等 |
| 反问 | 候选人反问环节 |

### 传统模式（5 轮次）

笔试 → 技术一面 → 技术二面 → 综合面试 → 自定义环节

---

## 🔒 内容护栏（启发式，非安全边界）

系统包含一层**启发式内容护栏**，目的是拦截最幼稚的注入尝试、重复刷屏和明显的流程操控，**不是**一道能被认真对待的安全边界：

| 层级 | 内容 | 性质 |
|------|------|------|
| 频率限制 | slowapi 全局限流 + 高敏感端点独立限流 | 降低滥用 |
| 输入检查（硬） | 角色逃逸 / Prompt 盗取 / 越狱 / 特殊 token 等**高置信**模式 | 正则拦截，可被绕过 |
| 输入检查（软） | "从现在开始""你必须输出"等易误伤句式 | 仅告警，不阻断 |
| 输出检查 | System Prompt 片段泄漏 | 仅记录，不阻断 |
| 状态校验 | 重复回答检测（Jaccard）+ 内容质量校验 | 防刷屏 |
| 记忆防污染 | 检测篡改历史 / 替换简历意图 | 启发式 |
| HTTP 安全头 | x-content-type-options / x-frame-options / x-xss-protection | 纵深防御一角 |

**已知绕过方式**：换说法、错别字、同义词、中英混杂、Base64/拼音/编码变形均可绕过上述正则。生产环境必须依赖**服务端可信边界 + 模型侧指令隔离**，而非客户端关键词过滤。

**请求体限制**：简历上传 10MB，普通请求 1MB。

---

## 🧪 测试策略

测试不是「堆数量」，而是**分层保障 + 评测（eval）**两套机制配合：

| 层级 | 代表文件 | 守什么 | 为什么必要 |
|------|----------|--------|-----------|
| ① 确定性脚手架不变式 | test_schemas / test_dimension_weights / test_score_adjustments / test_flow / test_output_sanitizer | 纯函数逻辑（Schema、权重、评分加扣分项、状态机、话术净化）一旦被改坏，立刻红灯 | LLM 不可控，但脚手架必须可控——这是「改代码不引入回归」的底线 |
| ② 端到端链路 | test_api / test_session / test_interview_ws | 简历→出题→诊断→报告全链路（HTTP）+ 面试主循环 WS 路径（心跳 / 换模式 / 结束口令 / 断连收尾）；穷尽异常 / 降级 / fallback 路径 | 保证「系统真的跑得通」，而非单个函数对 |
| ③ 内容与边界 | test_security | 注入拦截、恢复红线 | 护栏的可验证证据 |
| ④ 黄金样本评测（eval） | test_diagnosis_golden | **诊断有效性**：最弱维度抓得对不对、加扣分命中没命中、证据引用是否原话 | AI 项目最该测、却最常被忽略——单测验证「工程正确性」，eval 验证「诊断准不准」 |

> 测试已从「锁死 prompt 文案」重构为「从配置取追问链 / 收尾指令做行为断言」，因此**频繁改写提示词不会误红**。

### 常用命令

```bash
# 全量测试（1000+ 用例；live_llm 抽检默认跳过，push/PR 由 GitHub Actions 自动执行）
pytest tests/ -q

# 仅跑黄金样本评测（确定性回归，默认运行）
pytest tests/test_diagnosis_golden.py -v

# 黄金样本 + 真实 LLM 抽检（需 GOLDEN_LIVE_LLM=1 + 真实 Key，烧 token，仅手动触发）
pytest tests/test_diagnosis_golden.py -v

# 覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing

# 分层依赖契约检查（新增/重构模块后必跑）
python run.py lint
```

> Windows 下无需额外操作：`run.py lint` 已内置 `PYTHONUTF8=1`，避免 grimp 按 GBK 解析 UTF-8 源码导致漏检。

---

## ⚠️ 已知局限

以下局限是已知的、刻意的取舍，**而非待修复的 bug**：

- **无认证 / 无身份校验**：定位为单用户本地工具，数据全存本机，全站免登录
- **内容护栏可被绕过**：正则过滤防不住认真攻击者，是启发式护栏，**不是安全边界**
- **诊断质量依赖 LLM**：单测验证的是工程正确性，诊断有效性靠黄金样本回归 + live-LLM 抽检做可观测
- **SQLite 单文件库 + 全局单例**：多 Worker 下 WebSocket 需 sticky session；LLM 客户端无按会话隔离
- **市场基准数据来源**：历史数据来自本人此前的采集项目导入
- **无断点续答**：流程位置已落库，但进程重启后不能从 DB 重建会话续答

> **诚实边界**：「1000+ 用例通过」不等于「核心功能被验证」——核心诊断质量最终依赖模型，测试套件验证的是工程正确性，模型质量仍需人工评审。

---

## 🤝 贡献

欢迎 Star ⭐ 与 Issue 反馈。提交 Pull Request 前请确保：

1. `python run.py lint` 分层契约通过；
2. `pytest tests/ -q` 全绿（改动前端时还需 `cd frontend && npm run test`）；
3. 前端改动已执行 `npm run build`（`dist/` 不入库，但需保证构建通过）。

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。
