# 架构与代码地图

> 从 README 迁入（v8.9 README 瘦身）。本文回答"代码放在哪、依赖朝哪个方向、模块各管什么"。
> 不变的架构约束与决策记录见 [CHARTER.md](../CHARTER.md)；接口清单见 [API.md](API.md)；
> 已知局限见 [LIMITATIONS.md](LIMITATIONS.md)。

## 技术栈

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

## 分层依赖契约

目录不作为强制的物理分层，但导入方向必须遵守逻辑分层，**下半层禁止 import 上半层**
（`.importlinter` 契约 + `python run.py lint` 强制执行，论证与反模式见 CHARTER 约束 2）：

| 层级 | 职责 | 代表模块 |
|---|---|---|
| **L1 基础设施** | 配置 / 日志 / LLM 客户端 / DB，无项目内向上依赖 | `config.py` `logger.py` `llm_client.py` `db.py` |
| **L2 领域模型与数据** | Schema、解析、检索、权重、Gap、市场数据、语音、记忆 | `schemas.py` `security.py` `resume_parser.py` `resume_retriever.py` `dimension_weights.py` `gap_analyzer.py` `knowledge_store.py` `voice_service.py` `market/*` `weakness_memory.py` `difficulty.py` |
| **L3 业务逻辑** | 出题、诊断、面试引擎、规划、档案聚合 | `question_gen.py` `diagnosis_engine.py` `interview_engine/*` `career_planner.py` `profile_service.py` `interview_skills.py` |
| **L4 应用入口** | 应用装配与路由 | `main.py` `routers/*` |

> 上表列的是**代表模块**，逐模块的权威登记以仓库根的 `.importlinter` 为准（该文件是
> 契约的唯一真相源，`run.py lint` 读它；v8.10 起该命令才真正执行检查，见 CHARTER DC-11）。
> 同层模块之间允许互相依赖（如 L2 内 `gap_analyzer → market.store`）。

## 代码地图

```
AI求职领航/
├── run.py                        # 一键启动入口 + lint 子命令（import-linter）
├── README.md                     # 面向用户的快速开始（本文件的父级入口）
├── .importlinter                 # 分层依赖契约（L1-L4）
├── .gitattributes                # 换行符统一为 LF（跨平台协作）
├── .github/                      # CI 工作流 / dependabot / 社区健康文件 / 截图资源
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
├── docs/                         # 公开文档（本目录）；过程性资料仅本地保留
├── data/                         # 运行时数据（自动创建，不提交 Git）
└── LICENSE                       # MIT 许可证
```

## 诊断体系

### 诊断维度

| 维度 | 说明 | 权重 |
|------|------|------|
| **STAR 完整性** | 情境-任务-行动-结果 四要素是否齐全 | JD 动态调整 |
| **量化程度** | 是否有具体数据支撑（数字、百分比、时间） | JD 动态调整 |
| **逻辑连贯性** | 叙事逻辑是否清晰、因果关系是否合理 | JD 动态调整 |
| **岗位相关性** | 回答与岗位要求的匹配度 | JD 动态调整 |
| **专业深度** | 技术理解是否深入、方案选型是否有洞见 | JD 动态调整 |

> 维度**数量**由 CHARTER 约束 3 固定，不可增减；权重由 LLM 根据 JD 自动分析确定，
> 范围 0.10–0.40，归一化后用于加权评分（`dimension_weights.py`）。

### 双 Agent 流程

```
用户回答 → Diagnostician（诊断 + 追问） → Rewriter（改写建议） → 前端展示
                   ↓                              ↓
              五维评分 + 追问                优化后的参考答案
```

两个 Agent 独立分步、各有独立 prompt，**禁止合并**（CHARTER 约束 1 / DC-01）——
避免同一模型为产出漂亮改写而调高自评分。

### 面试模式

**拟真模式（6 阶段）**

| 阶段 | 内容 |
|------|------|
| 破冰 | 自我介绍 + 背景了解 |
| 技术广度 | 多领域基础能力考察 |
| 技术深度 | 核心技术栈深入追问 |
| 项目拷问 | 简历项目深度挖掘 |
| 行为面 | 团队协作/冲突处理等 |
| 反问 | 候选人反问环节 |

**传统模式（5 轮次）**：笔试 → 技术一面 → 技术二面 → 综合面试 → 自定义环节

会话中可随时切换模式与阶段；7 种面试官风格，另有公司风格配置层
（`company_profiles/`，加 YAML 文件即加一家公司）。

## API 概览

共 **59 个 `/api` HTTP 端点 + 1 个 WebSocket 端点**（口径：只计 11 个 router 注册的路由，
`main.py` 直接注册的 `GET /` 产品落地页不在其内）。

面试主循环走 WebSocket（`/ws/interview/{session_id}`），HTTP 端点负责准备素材与取结果。
服务启动后访问 **`/docs`（Swagger UI）**，字段级结构以它为准；逐条清单与限流档位见
[API.md](API.md)。

> 全站免登录，所有端点均不含身份概念——这是单用户本地工具的设计前提，见
> [LIMITATIONS.md](LIMITATIONS.md)。
