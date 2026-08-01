
<h1 align="center">🤖 AI 模拟面试官</h1>

<p align="center">
  <strong>v3.1 — 生产级加固 + 市场数据深度集成</strong>
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
  支持简历解析、双 Agent 诊断、流式反馈、语音交互、题库管理
</p>

---

## 📖 项目简介

AI 模拟面试官是一个面向求职者的智能面试练习平台。上传简历后，AI 会模拟大厂面试流程（6 阶段拟真模式 / 5 轮次传统模式），围绕 **STAR 完整性、量化程度、逻辑连贯性、岗位相关性、专业深度** 五个维度进行实时诊断，提供改写建议和综合评分报告。

### 核心亮点

- **双 Agent 诊断引擎**：Diagnostician（诊断）+ Rewriter（改写）独立协作，非单一评分
- **动态维度权重**：根据 JD 自动调整各维度权重 + SHA256 缓存，诊断更贴合岗位
- **流式诊断反馈**：WebSocket 实时推送诊断结果、追问、雷达图数据
- **7 种面试官角色**：友好/严格/压力/专业/好奇/质疑/鼓励型自动切换
- **双模式面试**：拟真 6 阶段（破冰→技术广度→技术深度→项目拷问→行为面→反问）+ 传统 5 轮次
- **语音交互**：浏览器内置 Web Speech API 实现题目朗读（TTS）+ 语音回答（STT）
- **Gap 分析**：简历-岗位六维度透明匹配（技能/城市/学历/经验/薪资/可信度），含市场基准参照
- **跨岗位对比**：一份简历同时对比多个 JD，输出排名与择岗建议
- **岗位画像研究**：DuckDuckGo 搜索 + LLM 分析，自动丰富 JD 背景
- **市场数据注入**：出题时自动注入市场行情（热门技能/薪资分位/学历分布）
- **Web 安全加固**：slowapi 频率限制 + 安全响应头 + 请求体大小限制
- **安全防护**：5 层安全体系（频率限制 + 输入注入检测 / 输出泄露检测 / 状态校验 / 记忆防污染）
- **多 AI 后端**：DeepSeek / 通义千问 / 智谱 GLM / OpenAI 可切换
- **题库管理**：CRUD + 收藏 + 从面试会话导入
- **Docker 部署**：Dockerfile + docker-compose.yml 一键部署
- **自动化测试**：50 个测试用例覆盖核心路径

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

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key（至少配置一个 AI 后端）

# 5. 启动服务
python run.py
```

启动后访问：
- 🎯 **面试页面**：http://localhost:8000
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
AI_PROVIDER=deepseek        # deepseek / qwen / zhipu / openai

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
```

---

## 🏗️ 项目结构

```
AI-simulated-interviewer/
├── run.py                        # 一键启动入口（本地开发）
├── Dockerfile                    # 生产级容器镜像
├── docker-compose.yml            # Docker Compose 部署
├── .dockerignore                 # 容器构建忽略清单
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量模板
│
├── backend/                      # Python 后端
│   ├── main.py                   # FastAPI 入口 + HTTP/WebSocket 路由 + 频率限制
│   ├── config.py                 # 配置 + 面试官风格 + 轮次定义
│   ├── logger.py                 # 集中日志配置（RotatingFileHandler）
│   ├── llm_client.py             # 多 AI 后端客户端（含流式）
│   ├── db.py                     # SQLite 多表操作（aiosqlite）+ JD 权重缓存表
│   ├── schemas.py                # Pydantic 数据模型（含跨岗位对比）
│   ├── security.py               # 5 层安全防护
│   ├── diagnosis_engine.py       # 双 Agent 诊断引擎
│   ├── dimension_weights.py      # JD 动态维度权重（含 SHA256 缓存）
│   ├── gap_analyzer.py           # 简历-岗位 Gap 分析 + 市场基准参照
│   ├── question_gen.py           # 问题生成（含市场数据注入）
│   ├── question_bank.py          # 题库 CRUD 管理
│   ├── resume_parser.py          # 简历解析（PDF/DOCX/TXT）
│   ├── web_research.py           # 岗位画像研究（DuckDuckGo）
│   ├── data_support.py           # 技能匹配数据
│   ├── skills_data.json          # 岗位技能静态数据
│   └── interview_engine/         # 面试引擎子包
│       ├── __init__.py
│       ├── session.py            # 核心状态机
│       └── report.py             # 综合报告生成
│
├── frontend/                     # 原生 ES Module 前端
│   ├── index.html                # SPA 骨架
│   ├── css/style.css             # 全局样式（含 Gap 分析/市场参照/跨岗位对比）
│   └── js/
│       ├── app.js                # 主入口 + Tab 切换
│       ├── api.js                # HTTP + WebSocket 封装
│       ├── interview.js          # 面试流程控制
│       ├── liveRadar.js          # 实时五维雷达图
│       ├── report.js             # 综合报告 + Gap 分析 + 跨岗位对比
│       ├── history.js            # 历史记录
│       ├── questionBank.js       # 题库管理界面
│       ├── voice.js              # 语音交互（TTS + STT）
│       └── utils.js              # 工具函数
│
├── tests/                        # 自动化测试（50 用例）
│   ├── conftest.py               # 共享 fixtures
│   ├── test_schemas.py           # Schema 验证（11 测试）
│   ├── test_gap_analyzer.py      # Gap 分析器（21 测试）
│   └── test_api.py               # HTTP 路由集成测试（18 测试）
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
| **语音** | Web Speech API（浏览器内置，无需后端） |
| **简历解析** | pdfplumber + python-docx |
| **岗位研究** | DuckDuckGo 搜索 + LLM 分析 |
| **日志** | logging + RotatingFileHandler（5MB×3 旋转） |
| **部署** | Docker + Docker Compose（跨平台一键部署） |
| **测试** | pytest（50 用例） |

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

## 🔒 安全特性

| 层级 | 防护内容 |
|------|---------|
| L0 频率限制 | slowapi 全局限流 + 高敏感端点独立限流 |
| L1 输入注入检测 | 50+ 正则模式：角色逃逸 / Prompt 盗取 / 越狱 / 编码绕过 |
| L2 输出泄露检测 | System Prompt 片段泄漏检测 |
| L3 状态异常校验 | 重复回答检测（Jaccard 相似度）+ 内容质量校验 |
| L4 记忆防污染 | 检测篡改历史 / 替换简历 / 撤回回答行为 |
| HTTP 安全头 | x-content-type-options / x-frame-options / x-xss-protection |

**请求体限制**：简历上传 10MB，普通请求 1MB。

---

## 📝 开发文档

详见 `docs/` 目录：

- [v1 模块需求文档](docs/)
- [v2 大版本迭代需求](docs/week2_v2迭代_需求.md)
- [模块差距分析](docs/week3_三个模块差距分析与阶段结论.md)
- [v2.6 深化诊断核心](docs/week4_深化诊断核心_需求.md)
- [v3.0 市场数据层改造](docs/week5_v3数据层_需求.md)

### 自动化测试

```bash
# 运行全部 50 个测试
pytest tests/ -v

# 覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing
```

测试覆盖：Schema 验证（11）/ Gap 分析器（21）/ HTTP 路由（18）


---

## 🤝 贡献

本项目为课程项目，暂不开放外部贡献。欢迎 Star ⭐ 和 Issue 反馈！

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。
