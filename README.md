
<h1 align="center">🤖 AI 求职领航（原 AI 求职陪跑平台）</h1>

<p align="center">
  <strong>v8.7 — 全流程求职陪跑平台（v8.0 引入求职档案领域核心；v8.2 市场数据分析 + AI 解读 + 产品落地页；v8.3 砍掉登录认证、术语统一、面试入口收敛；v8.3.2 仓库整理、文档标准化与公开范围收敛；v8.5 全站视觉质感层；v8.6 模拟面试模块改进；v8.7 落地页 three.js 秀场动效改版）</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/fastapi-0.110+-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/docker-supported-blue.svg" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/status-active-success.svg" alt="Status">
</p>

<p align="center">
  从职业定位到拿 Offer 的全流程 AI 求职陪跑<br>
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
- [测试策略与工程保障](#-测试策略与工程保障答辩看点)
- [已知局限](#-已知局限与架构取舍)
- [开发文档](#-开发文档)
- [贡献](#-贡献)
- [许可证](#-许可证)

---

## 📖 项目简介

AI 求职领航（原 AI 求职陪跑平台）是一个面向求职者的全流程 AI 陪跑系统，按五步主线组织（v7.3 定位延伸，功能零增删；v7.5 范围收缩取消"连机会"；**v8.1 术语统一为专业评测语系，步骤改名、结构不变**，决策记录见 CHARTER **DC-09**）：

**职业定位**（市场数据 + 岗位库）→ **简历准备**（简历库）→ **面试演练**（AI 多轮模拟面试：6 阶段拟真模式 / 5 轮次传统模式）→ **能力诊断**（围绕 **STAR 完整性、量化程度、逻辑连贯性、岗位相关性、专业深度** 五个维度实时诊断，生成改写建议与综合评分报告 + 长期记忆图谱）→ **发展路径**（时间轴职业路径）。

> v8.0 起，首屏为**能力档案**：以「求职档案」为领域核心，把三个能力模块从并列功能降级为档案的读写者，形成「目标 → 现状 → 差距 → 行动 → 复测」的陪跑闭环。

## ✨ 核心特性

- **求职档案领域核心**：以档案为中心聚合「当前简历 / 目标岗位 / 能力水平 / 待提升项」，用六条规则表产出**下一步建议**（纯函数、零延迟、可解释，不调 LLM），形成「目标 → 现状 → 差距 → 行动 → 复测」闭环。档案是**投影**而非新真相源，不新增宽表双写
- **五维诊断**：STAR 完整性 / 量化程度 / 逻辑连贯性 / 岗位相关性 / 专业深度，权重按 JD 动态调整；每个维度附**候选人原话引用**，把主观打分锚定到可复核证据
- **双 Agent 协作**：Diagnostician（诊断评分）与 Rewriter（改写示范）独立分步，避免同一模型为产出漂亮改写而调高自评分（CHARTER DC-01）
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
- **工程保障**：import-linter 强制 L1–L4 分层契约、1079 个 pytest 用例（含黄金样本评测与 live-LLM 抽检）、前端 vitest、GitHub Actions CI

> 各特性的落地版本与取舍理由见 [CHANGELOG.md](CHANGELOG.md)；产品命题与决策记录见 [CHARTER.md](CHARTER.md)。

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

# 4. 安装 Playwright 浏览器（v4.1 市场数据 Tab 实时采集需要；跳过则实时采集不可用，岗位库检索/Gap 分析/跨岗位对比不受影响）
python -m playwright install chromium

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key（至少配置一个 AI 后端）
# 可选：填入 MIMO_API_KEY 启用小米 MiMo 云端语音（更自然的朗读 + 跨浏览器语音识别）；不配置则自动使用浏览器原生语音
# MiMo 端点：https://api.xiaomimimo.com/v1（sk- 开头 Key 走按量付费集群）；TTS/ASR 均按官方 chat/completions 协议调用
# 可选音色：MIMO_TTS_VOICE=冰糖（默认）/ 茉莉 / 苏打 / 白桦 / Mia / Chloe / Milo / Dean

# 6. 启动服务
python run.py
```

前端开发模式（v4.0，可选，提供热更新）：
```bash
cd frontend
npm install
npm run dev     # http://localhost:5173（自动代理 /api /ws /upload 到 :8000）
npm run build   # 产出 dist/，由 FastAPI 托管（http://localhost:8000）
npm run test    # [v7.4] 前端 vitest 套件（voice.js 竞态 / VAD / 熔断）
```

> ⚠️ **改完前端必须执行 `npm run build`**：`run.py` 托管的是 `frontend/dist`（不入库），只改 `src/` 不构建的话界面不会变化。

启动后访问：
- 🎯 **面试页面**：http://localhost:8000（生产构建）或 http://localhost:5173（开发热更新）
- 📚 **API 文档**：http://localhost:8000/docs

### Docker 部署（标准化，推荐）

项目支持 Docker Compose 一键部署，无需安装 Python 环境，适用于本地测试或服务器上线：

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

**版本更新**：
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

> 注意：多 Worker 模式下 WebSocket 需要 sticky session，单 Worker 模式已足够课程项目使用。

### 环境变量说明

`.env` 支持四种 AI 后端，至少配置一种：

```bash
# 通用配置（优先使用）
AI_PROVIDER=deepseek        # deepseek / qwen / zhipu / openai / auto（v6.0：auto=按注册顺序自动探测第一个 Key 有效的后端）

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

# 模型调用优雅降级（fallback，可选，v4.3）
# 主模型失败(限流/超时/不可用)时按序自动切换备用模型，调用方无感知
# 格式: "provider:model,provider:model,..."；留空=不降级(单模型)
# qwen-plus 与 deepseek-chat 能力相当(通用对话主力)，作备用首选
# LLM_FALLBACK_CHAIN=deepseek:deepseek-chat,qwen:qwen-plus
# LLM_FALLBACK_MAX_RETRIES=3
```

---

## 🧑‍💻 使用说明

系统**只服务求职者**——v7.0 曾引入「招聘者只读端 + 报告分享」，因与求职者定位冲突（画蛇添足）已于 v7.5 删除（CHARTER **DC-08**）；v7.0 引入的**用户认证与资源归属层也已于 v8.3 整体下线**（CHARTER **DC-10**）——本系统定位为单用户本地工具，数据全存本机、无外部访问，认证是过度工程。当前**全站免登录、一个视图**：

1. **看能力档案**（默认首屏）：一眼看到「当前简历 / 目标岗位 / 能力水平 / 待提升项」，并给出**下一步建议**（先有简历 → 再定目标 → 再测能力 → 补短板 / 排路径）；能力画像下方是**成长曲线**（完成第二场模拟面试后开始显示轨迹），左侧旅程时间线显示五步走到哪一步。
2. **建立素材库**：「简历库」上传一次简历（完整入库，不截断）；「岗位库」保存常练的岗位 JD。之后每次开练直接选用，不必重复上传与解析。
3. **开练**：面试面板选择「从简历库选择」（或上传本机简历文件）与「从岗位库选择」（或上传 JD 文件）→ 开始面试。支持文字或语音作答，会话中可随时切换模式与阶段。
4. **复盘**：报告页的每维度评分附**候选人原话引用**（quote），可逐条核对「这个分凭什么」；复盘成果支持 Markdown / HTML 导出自用。

---

## 🏗️ 项目结构

```
AI模拟面试官/
├── run.py                        # 一键启动入口 + lint 子命令（import-linter）
├── README.md                     # 面向用户的完整说明（本文件）
├── CHARTER.md                    # [v3.2] 不变宪章：架构约束/决策记录卡/已知局限/范围纪律
├── CHANGELOG.md                  # [v3.2] 版本迭代叙事（v2 → v8.3）
├── CODEBUDDY.md                  # AI 协作入口索引（新会话应先读它）
├── .importlinter                 # [v3.2] 分层依赖契约（L1-L4）
├── .gitattributes                # 换行符统一为 LF（跨平台协作）
├── .github/workflows/ci.yml      # [v7.2.1] CI：分层契约 + 后端全量测试 + 前端单测 + 构建
├── Dockerfile                    # 容器镜像（课程项目级）
├── docker-compose.yml            # Docker Compose 部署
├── .dockerignore                 # 容器构建忽略清单
├── requirements.txt              # Python 依赖（含 dev 依赖 import-linter）
├── .env.example                  # 环境变量模板
│
├── backend/                      # Python 后端
│   ├── main.py                   # FastAPI 应用装配（中间件/限流/startup/静态挂载）
│   ├── routers/                  # [v7.2.2 NEW] HTTP/WS 路由域拆分（system/voice/sessions/
│   │                             #   assets/reports/question_bank/diagnostics/market/
│   │                             #   analytics/profile/interview_ws + state 单例 + deps 依赖）
│   ├── config.py                 # 配置 + 面试官风格 + 轮次定义
│   ├── logger.py                 # 集中日志配置（RotatingFileHandler）
│   ├── llm_client.py             # 多 AI 后端客户端（含流式）
│   ├── db.py                     # SQLite 多表操作（aiosqlite）+ JD 权重缓存表
│   ├── schemas.py                # Pydantic 数据模型（含跨岗位对比）
│   ├── security.py               # 启发式内容检查（课程项目级，非安全边界）
│   ├── diagnosis_engine.py       # 双 Agent 诊断引擎
│   ├── dimension_weights.py      # JD 动态维度权重（含 SHA256 缓存）
│   ├── gap_analyzer.py           # 简历-岗位 Gap 分析 + 市场基准参照
│   ├── career_planner.py         # [v3.2] 职业路径规划（以 Gap 为基线做多阶段推理）
│   ├── profile_service.py        # [v8.0 NEW] 求职档案领域核心（四段聚合 + 建议规则表 + 五步完成度 + 技能缺口，L3）
│   ├── question_gen.py           # 问题生成（含市场数据注入）
│   ├── question_bank.py          # 题库 CRUD 管理
│   ├── resume_parser.py          # 简历解析（PDF/DOCX/TXT）+ [v6.5] PDF 两阶段文本修复
│   ├── web_research.py           # 岗位画像研究（DuckDuckGo）
│   ├── data_support.py           # 技能匹配数据
│   ├── skills_data.json          # 岗位技能静态数据
│   ├── market/                    # [v3.0] 市场数据子包
│   │   ├── __init__.py
│   │   ├── cleaner.py            # 数据清洗
│   │   ├── importer.py           # 外部数据导入
│   │   ├── service.py            # 导入编排 + 岗位快照检索
│   │   ├── store.py              # 数据持久化
│   │   ├── analytics.py          # [v8.2] 图表数据聚合（给人看，与 get_stats 刻意分离）
│   │   ├── insight.py            # [v8.2] 图表 AI 解读（section 注册表 + 5min TTL 缓存）
│   │   └── crawler/              # [v4.1 NEW] B 档内嵌实时采集（Playwright）
│   │       ├── python_job_scraper.py   # 采集核心（相对导入改造）
│   │       ├── salary_parser.py        # 薪资解析
│   │       ├── adapters.py             # 采集记录 → 标准 job dict + JD 组装
│   │       └── tasks.py                # 后台任务表（互斥/进度/TTL 清理）
│   ├── voice_service.py          # [v4.2 NEW] MiMo 云端语音代理（TTS 合成 + ASR 识别）
│   ├── resume_retriever.py       # [v5.0 NEW] 简历证据检索器（分块/加权/预算/证据包）
│   ├── output_sanitizer.py       # [v6.2 NEW] 面试话术输出净化（禁 Markdown/舞台提示/垫词，L2）
│   ├── resume_anchors.py         # [v6.3 NEW] 简历锚点五分类（技术选型/量化/架构/业务/团队，L2）
│   ├── score_adjustments.py      # [v6.3 NEW] 评分规则化加减分项（确定性正则 + evidence，L2）
│   ├── pressure_bank.py          # [v6.3 NEW] 压力题库（5 类 16 道，与简历/JD 解耦，L2）
│   ├── company_profiles.py       # [v6.5 NEW] 公司风格配置层（YAML 热加载/JD 匹配/片段生成，L2）
│   ├── company_profiles/         # [v6.5 NEW] 公司风格 YAML（内置字节/腾讯/阿里，加文件即加公司）
│   ├── weakness_memory.py        # [v6.6 NEW] 长期薄弱点 EMA 衰减 + 过期淘汰（L2）
│   ├── difficulty.py             # [v6.6 NEW] 动态难度调度器（轮内自适应，L2）
│   ├── interview_skills.py       # [v6.6 NEW] 面试技能状态机（有状态多轮，L3）
│   └── interview_engine/         # 面试引擎子包
│       ├── __init__.py
│       ├── session.py            # 核心状态机
│       ├── flow.py               # [v7.0 NEW] 流程状态显式化（decide_next 纯函数）
│       └── report.py             # 综合报告生成
│
├── frontend/                     # 原生 ES Module 前端（Vite 工程化，双入口）
│   ├── index.html                # SPA 骨架（主功能，默认首屏 = 能力档案）
│   ├── landing.html              # [v8.2] 独立产品落地页（根路径 `/` 由后端返回；v8.7 three.js 秀场动效改版）
│   ├── package.json / vite.config.js / eslint.config.js
│   └── src/
│       ├── main.js               # Vite 入口（注入全局 Chart + 装配 app.js）
│       ├── assets/
│       │   └── china-geo.json    # [v8.0] 中国地图 GeoJSON（动态 import 懒加载，不进主包）
│       ├── js/
│       │   ├── app.js            # 主入口 + Tab 注册表 + 哈希路由（#/home 等，v8.0 重构）
│       │   ├── navConfig.js      # [v8.0 NEW] 导航单一数据源（五步旅程，侧栏与底部导航同源于此）
│       │   ├── profileCard.js    # [v8.0 NEW] 能力档案首屏（建议卡 / 五维画像 / 成长曲线 / 待提升项）
│       │   ├── api.js            # HTTP + WebSocket 封装（含市场采集/城市映射/岗位详情）
│       │   ├── interview.js      # 面试流程控制（setup 视图 / 对话流 / 诊断面板）
│       │   ├── liveRadar.js      # 实时五维雷达图
│       │   ├── report.js         # 综合报告 + Gap 分析 + 跨岗位对比
│       │   ├── history.js        # 历史记录
│       │   ├── questionBank.js   # 题库管理界面
│       │   ├── resumeLibrary.js  # [v7.0] 简历库（跨会话复用的输入资产）
│       │   ├── positionLibrary.js  # [v7.0] 岗位库
│       │   ├── careerPlan.js     # [v3.2] 职业规划 Tab（时间轴 + 阶段卡片 + 技能曲线）
│       │   ├── marketData.js     # [v4.1] 市场数据 Tab（采集/岗位库/详情/分析，v7.1 视觉按设计规格统一）
│       │   ├── cityCoords.js     # [v8.2] 城市坐标表（支撑市场数据地理可视化）
│       │   ├── memoryGraph.js    # [v6.4] 长期记忆 Tab（2D SVG 薄弱点图谱 + 明细联动 + resolved）
│       │   ├── voice.js          # 语音交互（TTS + STT，v6.4 世代守卫真打断）
│       │   ├── themeToggle.js    # [v7.1 NEW] 全局主题切换器（手动深浅；v7.2 移除语义色切换器）
│       │   ├── landing.js        # [v8.7 NEW] 落地页动效总编排（three.js WebGL 墨晕 Hero / 逐字揭示 / 磁性按钮 / 3D 倾斜 / 时间线描边，仅 landing.html 使用）
│       │   └── utils.js          # 工具函数（含 confirm 弹窗 / emptyState 三件套 / 动效入口）
│       │   （v7.5 已删除：recruiterInbox.js / shareReport.js；v8.3 已删除：auth.js）
│       └── css/
│           ├── tokens.css        # Design Tokens（v7.1 纸墨印章色值重映射 + RGB 三元组）
│           ├── theme.css         # [v7.1 NEW] 主题切换相关样式（html.theme-dark；v7.2 重写为「墨夜纸墨」覆盖层）
│           ├── motion.css        # [v7.2 NEW] 动效基建层（面板过渡/stagger/骨架屏/盖章/countup/shake/降级；v8.7 第 11 节 landing 秀场 keyframes）
│           ├── surface.css       # [v8.5 NEW] 质感层（环境光/壳层玻璃/三级景深/渐变描边，注释单行 <link> 即整体回退）
│           ├── layout.css        # [v8.0 NEW] 壳层布局（侧栏/底部导航 + 旅程时间线 + 进度条，自 components.css 迁出）
│           ├── base.css          # reset + 排版
│           ├── components.css    # 组件层（v7.2.2 并入原 style.css，332 条规则合流去重）
│           └── pages/            # 领域样式（market / memory / profile / report / history / interview / landing）
│   ├── vitest.config.js          # [v7.4 NEW] 前端测试配置（environment: node，运行时全部打桩）
│   └── tests/
│       ├── voice.test.js         # [v7.4 NEW] 语音模块单测（世代号守卫/熔断韧性/VAD，16 例）
│       ├── interview.test.js     # [v8.6 NEW] 面试主循环 WS 消息派发契约（29 种消息 + 源码扫描，36 例）
│       └── landing.test.js       # [v8.7 NEW] 落地页动效纯函数（逐字拆分/磁性偏移/倾斜角/时间线进度钳制，25 例）
│
├── tests/                        # 后端自动化测试（1079 用例 + 1 live_llm 抽检，本机非 LLM 类全绿）
│   ├── conftest.py               # 共享 fixtures
│   ├── test_schemas.py           # Schema 验证
│   ├── test_api.py               # HTTP 路由集成测试（含安全测试）
│   ├── test_gap_analyzer.py      # Gap 分析器
│   ├── test_dimension_weights.py # 维度权重
│   ├── test_resume_parser.py     # 简历解析
│   ├── test_report.py            # 报告生成
│   ├── test_security.py          # 安全防护
│   ├── test_web_research.py      # 岗位画像研究
│   ├── test_data_support.py      # 技能匹配
│   ├── test_market_cleaner.py    # 市场数据清洗
│   ├── test_market_importer.py   # 市场数据导入
│   ├── test_career_planner.py    # [v3.2] 职业规划（schema + 路由 + 降级路径）
│   ├── test_market_crawler_*.py  # [v4.1] 采集适配器 + 后台任务状态机
│   ├── test_voice_service.py     # [v4.2] MiMo 语音服务（key 校验/错误处理/mock）
│   ├── test_voice_api.py         # [v4.2] /api/voice/* 代理路由
│   ├── test_session.py           # [v5.0] 会话状态机（追问/权重/薄弱点/恢复/多模式，49 例）
│   ├── test_resume_retriever.py  # [v5.0] 简历证据检索（分块/命中/预算/溯源，12 例）
│   ├── test_grillmind_borrowings.py  # [v6.2] 收尾强控/追问点/净化/任务绑定/思考时长/逐题拆解（50 例）
│   ├── test_mock_interviewer_borrowings.py  # [v6.3] 角色卡/锚点/加减分/JD gap/压力题/恢复红线（50 例）
│   ├── test_injection_dedup.py      # [v6.4] 注入去重（指纹稳定/先过滤后预算/耗尽回退，19 例）
│   ├── test_alternate_question.py   # [v6.4] 备选题/换题（台账/负向约束/重试上限，10 例）
│   ├── test_weakness_memory.py      # [v6.4] 长期记忆闭环（迁移幂等/resolved/回注入，17 例）
│   ├── test_diagnosis_golden.py     # [v7.0.3 NEW] 黄金样本评测（v7.2.1 扩容至 20 条确定性回归 + live-LLM 抽检）
│   ├── test_interview_ws.py         # [v7.3.1 NEW] WebSocket 面试主循环集成测试（4 条主路径 + 握手契约，覆盖率 8%→61%）
│   ├── test_market_store.py         # [v7.3.1 NEW] market/store.py 持久化（upsert 幂等 / 收藏不覆盖 / 查询边界）
│   ├── test_profile_service.py      # [v8.0 NEW] 求职档案聚合（建议规则表优先级 / 技能缺口集合运算 / 成长曲线）
│   ├── test_profile_api.py          # [v8.0 NEW] /api/profile 与 /api/profile/refresh（缓存失效）
│   └── fixtures/golden_answers.json # [v7.0.3 NEW] 黄金样本与人工标注（覆盖 16 类典型行为信号）
│
├── docs/                         # 文档：公开文档（入库）+ 过程性资料（仅本地，见 docs/README.md）
│   ├── README.md                 # docs 索引：公开 / 本地两类划分 + 文档约定
│   ├── API.md                    # 后端接口全量参考（59 HTTP + 1 WebSocket）
│   ├── LIMITATIONS.md            # 已知局限与架构取舍全文（23 条）
│   ├── job-crawler-UI设计系统规格.md  # [v7.1] 全站 UI 改造基线（Token/组件/深色覆盖/页面骨架）
│   ├── 产品定位延伸_全流程求职陪跑.md  # [v7.3] 定位向上延伸方案全文（DC-07）
│   ├── 前端设计方案_UIUX重构.md   # [v4.0] 前端信息架构与交互方案
│   ├── UI评审_v7.2_动效与高级感升级.md  # [v7.2] 动效体系评审全文
│   └── specs/                    # 在研设计稿
│   # 以下为过程性资料：本地保留、不随仓库公开（.gitignore 已排除，文件不删）
│   ├── archive/                  # week1–week10 需求文档 19 篇 + 竞品深度研读 6 篇
│   ├── research/                 # 竞品对标调研与学习报告 3 篇
│   ├── 答辩要点_测试与质量保障.md / 测评问题记录.md / 演示模式方案评估.md
│   ├── 初验演示脚本.md / 初验演示讲稿.md
│   ├── 立项报告/                 # 立项报告 docx（*.docx 受 .gitignore 约束）
│   └── AI对话存档/               # AI 会话存档（.gitignore 忽略）
│
├── data/                         # 运行时数据（自动创建，不提交 Git）
├── LICENSE                       # MIT 许可证
└── README.md                     # 本文件
```

---

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI + WebSocket + slowapi（频率限制） |
| **数据库** | SQLite（aiosqlite 异步驱动） |
| **AI 后端** | DeepSeek / Qwen / 智谱 GLM / OpenAI（可运行时切换） |
| **前端** | 原生 HTML5 + CSS3 + ES Module（无框架依赖）；three.js 仅限 landing 落地页（v8.7，动态 import 拆 async chunk，主应用包不受影响） |
| **图表** | Chart.js v4（雷达图） |
| **语音（v4.2）** | 小米 MiMo 云端（TTS/ASR，需 `MIMO_API_KEY`）+ 浏览器 Web Speech API 降级 |
| **简历解析** | pdfplumber + python-docx |
| **岗位研究** | DuckDuckGo 搜索 + LLM 分析 |
| **岗位采集（v4.1）** | Playwright + playwright-stealth（`playwright install chromium`，B 档内嵌 `market/crawler/`） |
| **日志** | logging + RotatingFileHandler（5MB×3 旋转） |
| **部署** | Docker + Docker Compose（跨平台一键部署） |
| **分层校验** | import-linter 契约（L1-L4，`run.py lint` 强制） |
| **测试** | pytest（后端 1079 用例 + 1 live_llm 抽检）+ vitest（前端 77 例，v7.4 起，本机非 LLM 类全绿） |
| **CI（v7.2.1，v7.4 扩容）** | GitHub Actions：import-linter 契约 + 后端全量测试 + 前端 vitest 单测 + 前端构建冒烟 |

---

## 🔌 API 参考

共 **59 个 HTTP 端点 + 1 个 WebSocket 端点**，完整清单（方法 / 路径 / 说明 / 限流档位）见 [docs/API.md](docs/API.md)。

面试主循环走 WebSocket（`/ws/interview/{session_id}`），HTTP 端点负责准备素材与取结果。服务启动后 `/docs`（Swagger UI）提供由 Pydantic Schema 自动生成的交互式文档，**字段级结构以它为准**。

> 全站免登录（认证与资源归属已于 v8.3 下线，见 CHARTER **DC-10**），所有端点均不含身份概念。

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

本系统包含一层**课程项目级的内容护栏**，目的是拦截最幼稚的注入尝试、重复刷屏和明显的流程操控，**不是**一道能被认真对待的安全边界：

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

## 🧪 测试策略与工程保障（答辩看点）

本项目的测试不是「堆数量」，而是**分层保障 + 评测（eval）**两套机制配合。1079 个自动化用例全绿，结构如下：

| 层级 | 代表文件 | 守什么 | 为什么必要 |
|------|----------|--------|-----------|
| ① 确定性脚手架不变式 | test_schemas / test_dimension_weights / test_score_adjustments / test_flow / test_output_sanitizer | 纯函数逻辑（Schema、权重、评分加扣分项、状态机、话术净化）一旦被改坏，立刻红灯 | LLM 不可控，但脚手架必须可控——这是「改代码不引入回归」的底线 |
| ② 端到端链路 | test_api / test_session / test_interview_ws | 简历→出题→诊断→报告全链路（HTTP）+ 面试主循环 4 条 WS 路径（心跳 / 换模式 / 结束口令 / 断连收尾）；穷尽异常 / 降级 / fallback 路径 | 保证「系统真的跑得通」，而非单个函数对；WS 主循环在 v7.2.2 拆分后曾是唯一没有测试直接钉住的核心路径 |
| ③ 安全与边界 | test_security | 注入拦截、恢复红线 | 课程项目级护栏的可验证证据（越权类用例随 v8.3 认证下线一并移除，详见 CHANGELOG v8.3） |
| ④ 黄金样本评测（eval） | test_diagnosis_golden | **诊断有效性**：最弱维度抓得对不对、加扣分命中没命中、证据引用是否原话 | AI 项目最该测、却最常被忽略——单测验证「工程正确性」，eval 验证「诊断准不准」 |

**为什么这是项目优势（而非负担）：**
- 学生 / 课程 AI 项目普遍「跑通 demo 就交」，测试多为 0–10 条且**零模型质量评测**；本仓库的四层 + eval 体现工业级工程素养。
- 最关键的差异化是 **④ 黄金样本评测**：固定样本 + 人工标注做确定性回归，并用 `live-LLM` 抽检（默认 deselect，需显式开启）做真实模型结构软断言——首次把「诊断准不准」纳入可观测 / 可回归范围。
- 测试已从「锁死 prompt 文案」重构为「从配置取追问链 / 收尾指令做行为断言」，因此**频繁改写提示词不会误红**，测试从「阻挠迭代」变成「允许迭代」。

> 诚实边界：诊断质量最终依赖 LLM，单测验证的是工程正确性；黄金样本 + live-LLM 抽检补齐「诊断有效性」的可观测性，但模型本身的质量仍需人工评审。详见下文「已知局限」。

## ⚠️ 已知局限与架构取舍

本系统定位为**课程项目**，以下局限是已知的、刻意的取舍，**而非待修复的 bug**。完整清单（23 条，含可选演进方向）见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)，要点如下：

- **无认证 / 无身份校验**：单用户本地工具，数据全存本机，全站免登录（CHARTER **DC-10**）
- **内容护栏可被绕过**：正则过滤防不住认真攻击者，是课程项目级的启发式，**不是安全边界**
- **诊断质量依赖 LLM**：单测验证的是工程正确性，诊断有效性靠黄金样本回归 + live-LLM 抽检做可观测
- **SQLite 单文件库 + 全局单例**：多 Worker 下 WebSocket 需 sticky session；LLM 客户端无按会话隔离
- **市场基准数据来源**：历史数据来自本人此前的采集项目导入（学术诚信披露，详见局限文档）
- **无断点续答**：流程位置已落库，但进程重启后不能从 DB 重建会话续答

> **诚实边界**：「1079 个用例通过」不等于「核心功能被验证」——核心诊断质量最终依赖模型，测试套件验证的是工程正确性，模型质量仍需人工评审。

---

## 📝 开发文档

`docs/` 分「公开文档」与「过程性资料（仅本地）」两类，索引与划分约定见 [docs/README.md](docs/README.md)。常用入口：

- [docs 索引与文档约定](docs/README.md)
- [API 参考（59 个端点 + WebSocket 协议）](docs/API.md)
- [已知局限与架构取舍（全文）](docs/LIMITATIONS.md)
- [UI 设计规格（全站改造基线）](docs/job-crawler-UI设计系统规格.md)
- [前端设计方案（UI/UX 重构·评审稿）](docs/前端设计方案_UIUX重构.md)
- [产品定位延伸方案](docs/产品定位延伸_全流程求职陪跑.md)

> 课程过程稿（week1–week10 需求文档）、竞品调研与答辩验收材料属过程性资料，**本地保留、不随仓库公开**（`.gitignore` 已排除）。


### 宪章与契约（v3.2）

- [不变硬约束 CHARTER.md](CHARTER.md)：架构原则 / 诊断五维度 / L1-L4 分层规则 / 决策记录卡模板 / 已知局限
- [版本迭代叙事 CHANGELOG.md](CHANGELOG.md)：v2 → v8.3 各轮新增、推翻、修复
- [.importlinter](.importlinter)：分层依赖契约文件（INI 格式，与 CHARTER 约束同步）

### 自动化测试

测试策略见上文「测试策略与工程保障」。常用命令：

```bash
# 运行全部测试（1079 用例 + 1 live_llm 抽检，全绿；push/PR 由 GitHub Actions 自动执行）
pytest tests/ -v

# 仅跑黄金样本评测（确定性回归，默认运行）
pytest tests/test_diagnosis_golden.py -v

# 黄金样本 + 真实 LLM 抽检（需 GOLDEN_LIVE_LLM=1 + 真实 Key，烧 token，仅手动触发）
$env:GOLDEN_LIVE_LLM="1"; $env:GOLDEN_LIVE_LLM_API_KEY="sk-..."; pytest tests/test_diagnosis_golden.py -v

# 覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing
```

测试覆盖：Schema 验证 / API 路由 / Gap 分析器 / 维度权重 / 简历解析 / 报告生成 / 安全防护 / Web 研究 / 技能匹配 / 市场数据 / 职业规划 / 收尾强控 / 追问点提取 / 输出净化 / 任务级模型绑定 / 逐题拆解 / 黄金样本评测

### 分层依赖检查

```bash
# 校验 L1-L4 分层契约（新增/重构模块后必跑）
python run.py lint
```

> Windows 下无需额外操作：`run.py lint` 已内置 `PYTHONUTF8=1`，避免 grimp 按 GBK 解析 UTF-8 源码导致漏检。


---

## 🤝 贡献

本项目为课程项目，暂不开放外部贡献。欢迎 Star ⭐ 和 Issue 反馈！

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。
