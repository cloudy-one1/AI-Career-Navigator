
<h1 align="center">🤖 AI 模拟面试官与职业规划</h1>

<p align="center">
  <strong>v6.0 — 竞品借鉴专项：Prompt 硬约束 + 三态推进决策 + JSON 四级容错 + Provider 自动探测（课程项目级，非生产级）</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/fastapi-0.110+-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/docker-supported-blue.svg" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/status-active-success.svg" alt="Status">
</p>

<p align="center">
  基于大语言模型的多轮模拟面试系统<br>
  支持简历解析、双 Agent 诊断、流式反馈、语音交互、题库管理、职业路径规划
</p>

---

## 📖 项目简介

AI 模拟面试官是一个面向求职者的智能面试练习平台。上传简历后，AI 会模拟大厂面试流程（6 阶段拟真模式 / 5 轮次传统模式），围绕 **STAR 完整性、量化程度、逻辑连贯性、岗位相关性、专业深度** 五个维度进行实时诊断，提供改写建议和综合评分报告。

### 核心亮点

- **全新 UIUX（v4.0）**：三步引导准备 Setup + 双栏面试工作台（对话流 + 固定诊断面板）+ 复盘态诊断卡（环形总分/原文改写对照）+ 报告 Dashboard + 深色主题（跟随系统）
- **Vite 工程化（v4.0）**：Design Tokens 四层 CSS 架构 + 左垂直导航（桌面/平板/移动三态自适应）+ npm 开发/构建脚本
- **市场数据 Tab（v4.1）**：B 档内嵌 Playwright 实时采集（省份→城市级联多选 + 进度轮询，采集自动回灌 market.db）+ 岗位库检索统计 + 全屏岗位详情（跳转 51job 原文）+ 单选 Gap 分析 / 多选跨岗位对比，纸墨印章双风格自由切换
- **MiMo 云端语音（v4.2）**：后端代理 mimo-v2.5-tts（合成）+ mimo-v2.5-asr（识别，官方 chat/completions 协议），前端双引擎自动降级，录音用 MediaRecorder，密钥仅存后端不泄漏
- **双 Agent 诊断引擎**：Diagnostician（诊断）+ Rewriter（改写）独立协作，非单一评分
- **动态维度权重**：根据 JD 自动调整各维度权重 + SHA256 缓存，诊断更贴合岗位
- **流式诊断反馈**：WebSocket 实时推送诊断结果、追问、雷达图数据
- **7 种面试官角色**：友好/严格/压力/专业/好奇/质疑/鼓励型自动切换
- **双模式面试**：拟真 6 阶段（破冰→技术广度→技术深度→项目拷问→行为面→反问）+ 传统 5 轮次
- **语音交互（v4.2 升级）**：小米 MiMo 云端语音优先（TTS 朗读 + ASR 语音转文字），未配 Key / 失败自动降级浏览器原生 Web Speech API，语音作为输入输出替代层不参与诊断内核
- **Gap 分析**：简历-岗位六维度透明匹配（技能/城市/学历/经验/薪资/可信度），含市场基准参照
- **跨岗位对比**：一份简历同时对比多个 JD，输出排名与择岗建议
- **职业规划路径**（v3.2）：以 Gap 六维快照为基线，LLM 推理多阶段时间轴路径（需补技能/里程碑/岗位跃迁），替代横截面打分
- **分层依赖强制**（v3.2）：import-linter 契约（L1-L4）确定性拦截所有 import 越层，`run.py lint` 一键校验
- **岗位画像研究**：DuckDuckGo 搜索 + LLM 分析，自动丰富 JD 背景
- **市场数据注入**：出题时自动注入市场行情（热门技能/薪资分位/学历分布）
- **Web 层限流**：slowapi 频率限制 + 安全响应头 + 请求体大小限制（降低滥用，非安全边界）
- **启发式内容检查**：基于关键词/正则拦截最幼稚的注入尝试（非安全边界，可被绕过；详见「已知局限」）
- **多 AI 后端**：DeepSeek / 通义千问 / 智谱 GLM / OpenAI 可切换
- **模型调用优雅降级（fallback）**：主模型失败（限流/超时/不可用）时按 `LLM_FALLBACK_CHAIN` 自动切换备用模型，调用方无感知（v4.3）
- **简历证据检索（v5.0）**：本地关键词 + 优先级加权轻量检索器，为追问与诊断实时产出「本轮证据包」，配合证据硬规则约束模型**只依据简历证据或亲述评价**、严禁编造经历，杜绝"AI 凭空捏造候选人做过的事"
- **不会答恢复（v5.0）**：检测到候选人示弱（不会/不懂/没思路…）自动切换辅导式引导，而非机械继续拷打
- **薄弱点跨轮累计（v5.0）**：把各轮诊断的薄弱标签跨轮聚合，实时面板 + 报告沉淀「今日弱点」，并新增逐题参考答案背诵（修复参考答案恒为空）
- **会话中多模式/多阶段切换（v5.0）**：模拟过程中动态切换模式（simulation / traditional / coach / hardcore / interview_only）与阶段（phone_screen / tech_round_1 / tech_round_2 / hr）
- **Prompt 硬约束 + 三态推进决策（v6.0）**：出题 Prompt 写死题型枚举/难度递进/只出题不替答；诊断与"追问/下一题/收束（next_action）"同一次 LLM 调用产出，会话层只做兜底校验（对标 career-copilot）
- **JSON 四级容错（v6.0）**：LLM 输出解析走 直接解析→提取{}块→字符级修复→宽松解析 四级降级，轻微畸形输出（围栏/截断/尾逗号/单引号）就地修复，不再浪费 fallback 候选
- **Provider 注册表自动探测（v6.0）**：`AI_PROVIDER=auto` 按注册顺序自动选用第一个配置了有效 Key 的后端；Key 校验下沉配置层，切换后端时无效 Key 即时告警
- **命名空间知识库（v6.0）**：`rag:interview/career/resume` 命名空间隔离的本地关键词检索 + `augment_prompt` 注入（零托管依赖，前向储备）
- **题库管理**：CRUD + 收藏 + 从面试会话导入
- **Docker 部署**：Dockerfile + docker-compose.yml 一键部署
- **自动化测试**：491 个测试用例覆盖核心路径（含依赖 API Key 的 LLM 类测试）

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
```

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

## 🏗️ 项目结构

```
AI-simulated-interviewer/
├── run.py                        # 一键启动入口 + lint 子命令（import-linter）
├── CHARTER.md                    # [v3.2] 不变宪章：架构约束/决策记录卡/已知局限
├── CHANGELOG.md                  # [v3.2] 版本迭代叙事
├── .importlinter                 # [v3.2] 分层依赖契约（L1-L4）
├── Dockerfile                    # 容器镜像（课程项目级）
├── docker-compose.yml            # Docker Compose 部署
├── .dockerignore                 # 容器构建忽略清单
├── requirements.txt              # Python 依赖（含 dev 依赖 import-linter）
├── .env.example                  # 环境变量模板
│
├── backend/                      # Python 后端
│   ├── main.py                   # FastAPI 入口 + HTTP/WebSocket 路由 + 频率限制
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
│   ├── question_gen.py           # 问题生成（含市场数据注入）
│   ├── question_bank.py          # 题库 CRUD 管理
│   ├── resume_parser.py          # 简历解析（PDF/DOCX/TXT）
│   ├── web_research.py           # 岗位画像研究（DuckDuckGo）
│   ├── data_support.py           # 技能匹配数据
│   ├── skills_data.json          # 岗位技能静态数据
│   ├── market/                    # [v3.0] 市场数据子包
│   │   ├── __init__.py
│   │   ├── cleaner.py            # 数据清洗
│   │   ├── importer.py           # 外部数据导入
│   │   ├── service.py            # 导入编排 + 岗位快照检索
│   │   ├── store.py              # 数据持久化
│   │   └── crawler/              # [v4.1 NEW] B 档内嵌实时采集（Playwright）
│   │       ├── python_job_scraper.py   # job-crawler 采集核心（相对导入改造）
│   │       ├── salary_parser.py        # 薪资解析
│   │       ├── adapters.py             # 采集记录 → 标准 job dict + JD 组装
│   │       └── tasks.py                # 后台任务表（互斥/进度/TTL 清理）
│   ├── voice_service.py          # [v4.2 NEW] MiMo 云端语音代理（TTS 合成 + ASR 识别）
│   ├── resume_retriever.py       # [v5.0 NEW] 简历证据检索器（分块/加权/预算/证据包）
│   └── interview_engine/         # 面试引擎子包
│       ├── __init__.py
│       ├── session.py            # 核心状态机
│       └── report.py             # 综合报告生成
│
├── frontend/                     # 原生 ES Module 前端（Vite 工程化）
│   ├── index.html                # SPA 骨架
│   ├── package.json / vite.config.js
│   └── src/
│       ├── js/
│       │   ├── app.js            # 主入口 + Tab 切换（含市场数据分支）
│       │   ├── api.js            # HTTP + WebSocket 封装（含市场采集/城市映射/岗位详情）
│       │   ├── interview.js      # 面试流程控制
│       │   ├── liveRadar.js      # 实时五维雷达图
│       │   ├── report.js         # 综合报告 + Gap 分析 + 跨岗位对比
│       │   ├── history.js        # 历史记录
│       │   ├── questionBank.js   # 题库管理界面
│       │   ├── careerPlan.js     # [v3.2] 职业规划 Tab（时间轴 + 阶段卡片 + 技能曲线）
│       │   ├── marketData.js     # [v4.1] 市场数据 Tab（采集/岗位库/详情/分析）
│       │   ├── voice.js          # 语音交互（TTS + STT）
│       │   └── utils.js          # 工具函数
│       └── css/
│           ├── tokens.css        # Design Tokens（语义 Token + 深色预留）
│           ├── base.css          # reset + 排版
│           ├── components.css    # 框架组件
│           └── pages/            # 领域样式（含 market.css 纸墨印章风格）
│
├── tests/                        # 自动化测试（400+ 用例，本机非 LLM 类全绿）
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
│   └── test_resume_retriever.py  # [v5.0] 简历证据检索（分块/命中/预算/溯源，12 例）
│
├── docs/                         # 需求文档与周报
│   ├── week1_*.md                # v1 模块需求
│   ├── week2_v2迭代_需求.md       # v2 大版本迭代
│   ├── week3_*.md                # 模块差距分析
│   ├── week4_深化诊断核心_需求.md  # v2.6 深化诊断
│   └── week5_v3数据层_需求.md     # v3.0 市场数据层
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
| **前端** | 原生 HTML5 + CSS3 + ES Module（无框架依赖） |
| **图表** | Chart.js v4（雷达图） |
| **语音（v4.2）** | 小米 MiMo 云端（TTS/ASR，需 `MIMO_API_KEY`）+ 浏览器 Web Speech API 降级 |
| **简历解析** | pdfplumber + python-docx |
| **岗位研究** | DuckDuckGo 搜索 + LLM 分析 |
| **岗位采集（v4.1）** | Playwright + playwright-stealth（`playwright install chromium`，B 档内嵌 `market/crawler/`） |
| **日志** | logging + RotatingFileHandler（5MB×3 旋转） |
| **部署** | Docker + Docker Compose（跨平台一键部署） |
| **分层校验** | import-linter 契约（L1-L4，`run.py lint` 强制） |
| **测试** | pytest（400+ 用例，本机非 LLM 类全绿） |

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

**已知绕过方式**：换说法、错别字、同义词、中英混杂、Base64/拼音/编码变形均可绕过上述正则。生产环境必须依赖**认证/授权 + 服务端可信边界 + 模型侧指令隔离**，而非客户端关键词过滤。

**请求体限制**：简历上传 10MB，普通请求 1MB。

---

## ⚠️ 已知局限与架构取舍

本系统定位为**课程项目**，以下局限是已知的、刻意的取舍，而非待修复的 bug：

| 局限 | 说明 | 可选演进方向（未实现） |
|------|------|------------------------|
| **无认证/授权** | `session_id` 为随机串，防猜测但**不是访问控制**；拿到链接可读他人简历/诊断/报告 | 接入登录体系 + 会话归属校验；敏感接口加 `Depends(auth)` |
| **WebSocket 无连接身份校验** | `/ws/interview/{session_id}` 仅校验会话存在性，不校验连接者身份；任何持有 session_id 的客户端均可接管该会话流程，与"无认证/授权"同源 | 接入认证层 + 连接归属校验；v3.1 已为 `switch_provider` 单例重赋值加锁消除重赋值竞态 |
| **全局单例可变状态** | `llm_client`/`diagnosis_engine` 为模块级单例，被所有会话共享、无按会话隔离；多后端高频切换或并发导入下内部 provider 状态存在理论竞态 | 引入按会话隔离的客户端实例或请求作用域依赖（课程项目阶段仅文档披露，不做隔离） |
| **双 Agent 成本** | Diagnostician + Rewriter 每题至少 2 次 LLM 调用，流式下延迟与 token 成本翻倍 | 做单 Agent + 结构化输出（JSON）的对比实验，量化"分 vs 合"的质量/成本权衡后再决策 |
| **模型调用单点故障（已缓解）** | 原仅单模型，任一 provider 故障即硬失败；v4.3 起支持 `LLM_FALLBACK_CHAIN` 优雅降级，主模型失败自动切备用模型，调用方零改动、不影响双 Agent 诊断客观性 | 仍建议为备用 provider 配置独立密钥以保障可用性 |
| **SQLite 扩展性** | 单文件数据库；多 Worker 下 WebSocket 需 sticky session，水平扩展受限 | 换异步 Postgres / 引入连接池；或改用内存态 + 持久化分离 |
| **内容护栏可被绕过** | 见上节，正则过滤防不住认真攻击者 | 见上节演进方向 |
| **测试偏纯函数** | 50 个用例覆盖了权重计算、Schema 校验等确定性逻辑；但**诊断准确性、追问是否抓最弱维度、评分稳定性**依赖 LLM 输出，难以在单测中验证 | 引入基于黄金样本的回归评测（LLM-as-judge / 人工抽检），把"核心主张"纳入可观测范围 |
| **证据检索为本地启发式** | v5.0 简历证据检索是本地关键词 + 优先级加权，非语义向量检索；中文分词粒度受限，同义/模糊表述可能漏命中，仅作证据提示不替代向量库；可调参数为代码级常量未下沉 `.env` | 引入轻量向量库（如 sqlite-vec / faiss）做语义召回；参数下沉配置 |
| **知识库为关键词检索且未接入业务流** | v6.0 `knowledge_store.py` 为命名空间隔离的本地关键词检索（对标向量 RAG 的降级实现），同义表述可能漏命中；当前是 L2 前向储备，尚未被任何业务流调用 | 接入职业规划/出题的 Prompt 增强；知识规模大时升级向量索引 |
| **next_action 依赖模型自觉** | v6.0 三态推进决策采信模型声明，模型误判"回答合格"时可能少追问；已用"回答过短仍强制追问"硬兜底 + 未声明时回退阈值规则，且追问次数上限不受影响 | 用真实面试样本统计 next_action 与人工判断的一致率后再决定是否提升模型话语权 |
| **参考答案面板未渲染** | v5.0 报告已产出 `detailed_qa`（逐题参考答案）字段，但前端 `report.js` 尚无对应渲染面板，属前后端待对齐 | 在报告 Tab 补逐题参考答案背诵面板 |
| **市场基准数据来源（学术诚信披露）** | Gap 分析的"市场基准参照"数据来自本人此前已完成并提交的采集项目（job-crawler）的 `data.db`，经 importer + store 导入 `market.db`，**本次仅做管道整合、不含数据采集工作量** | 若评审基于"本次周期实际产出"，可评估替换为小样本人工整理/公开数据集 |
| **权重注入 prompt 因果未验证** | Diagnostician prompt 中的权重真正生效处在 `weighted_score()` 加权平均；prompt 是否改变模型打分分布未经 A/B 验证（已有 prompt 已改为中性诚实表述） | 做"有无权重说明文字"的 A/B 对照实验，量化影响 |
| **LLM 权重稳定性未测** | `analyze_jd_weights()` 用 LLM 判 JD 权重，`temperature=0.2` 非完全确定，"千岗千面"卖点的同-JD 权重方差从未测过 | 固定 JD 反复采样统计权重方差，给出稳定性区间 |
| **输出检测仅监控不阻断** | `security.check_output()` 检测到泄漏仅记日志、不拦截、不脱敏，泄漏内容原样返回前端，属可观测性而非输出安全边界 | 需要时做输出脱敏/阻断（产品化阶段事项） |
| **职业规划路径未经验证** | v3.2 的路径推理为单次 LLM 生成，阶段划分/顺序/里程碑合理性未做 A/B 或专家校验；LLM 失败时走启发式三段式兜底 | 用真实职业样本做专家评审；将"路径可行性"纳入黄金样本回归评测 |

> **关键结论**："50 个测试用例通过"不等于"核心功能被验证"。核心诊断质量依赖 LLM，当前测试套件验证的是**工程正确性**，而非**诊断有效性**。

---

## 📝 开发文档

详见 `docs/` 目录：

- [v1 模块需求文档](docs/)
- [v2 大版本迭代需求](docs/week2_v2迭代_需求.md)
- [模块差距分析](docs/week3_三个模块差距分析与阶段结论.md)
- [v2.6 深化诊断核心](docs/week4_深化诊断核心_需求.md)
- [v3.0 市场数据层改造](docs/week5_v3数据层_需求.md)
- [前端设计方案（UI/UX 重构·评审稿）](docs/前端设计方案_UIUX重构.md)

### 宪章与契约（v3.2）

- [不变硬约束 CHARTER.md](CHARTER.md)：架构原则 / 诊断五维度 / L1-L4 分层规则 / 决策记录卡模板 / 已知局限
- [版本迭代叙事 CHANGELOG.md](CHANGELOG.md)：v2 → v3.2 各轮新增、推翻、修复
- [.importlinter](.importlinter)：分层依赖契约文件（INI 格式，与 CHARTER 约束同步）

### 自动化测试

```bash
# 运行全部测试
pytest tests/ -v

# 覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing
```

测试覆盖：Schema 验证 / API 路由 / Gap 分析器 / 维度权重 / 简历解析 / 报告生成 / 安全防护 / Web 研究 / 技能匹配 / 市场数据 / 职业规划

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
