# AI 求职领航（原 AI 求职陪跑平台）

> 本文件是 CodeBuddy 的项目索引入口，每次新对话自动加载。**请先读以下三份文档再动手**：
>
> 1. **不变硬约束** → [CHARTER.md](CHARTER.md)（产品命题 / 架构约束 / 决策记录卡 / 已知局限 / 范围纪律）
> 2. **版本迭代叙事** → [CHANGELOG.md](CHANGELOG.md)（v2 → v8.7 各轮新增/推翻/修复）
> 4. **接口参考** → [docs/API.md](docs/API.md)（59 个 HTTP 端点 + 1 个 WebSocket，含限流档位与 WS 消息协议；改路由后应同步更新）
>
> 文档分区（现行 / 设计稿 / 调研 / 归档）见 [docs/README.md](docs/README.md)。

---

## 快速上手

- **定位（v7.3，v7.5 收缩，v8.1 术语统一）**：全流程求职陪跑平台「AI 求职陪跑」——五步主线：**职业定位**（市场数据/岗位库）→ **简历准备**（简历库）→ **面试演练**（模拟面试/题库/历史）→ **能力诊断**（综合报告/长期记忆）→ **发展路径**（职业规划）。原名为「定方向/备弹药/演练/诊弱点/定规划」，v8.1 统一为专业评测语系（改名不改结构，见 CHARTER DC-09）；v7.5 删除招聘者端与报告分享（"连机会"取消，回归求职者单端，见 CHARTER DC-08）；决策记录见 CHARTER DC-07，方案全文见 `docs/产品定位延伸_全流程求职陪跑.md`。
- **v8.0 领域核心**：以**求职档案（Profile）**为领域核心（`backend/profile_service.py`，L3），首屏为**能力档案**（默认 tab `home`）——聚合「当前简历 / 目标岗位 / 能力水平 / 待提升项」并给出**下一步建议**；三个能力模块降级为档案的读写者，形成「目标 → 现状 → 差距 → 行动 → 复测」闭环。详见 CHANGELOG v8.0。
- **核心价值**：诊断候选人的回答质量（STAR 完整性 / 量化程度 / 逻辑连贯性 / 岗位相关性 / 专业深度）+ 职业规划路径（v3.2 补齐的时间轴多阶段路径）+ 市场数据采集与分析（v4.1 新增）+ 云端语音交互（v4.2 MiMo TTS/ASR 新增）+ 模型调用优雅降级（v4.3 fallback）+ 简历证据检索 / 不会答恢复 / 薄弱点跨轮累计 / 会话中多模式切换（v5.0）+ Prompt 硬约束 / next_action 三态推进决策 / JSON 四级容错 / Provider 自动探测（AI_PROVIDER=auto）/ 命名空间知识库（v6.0）+ **面试收尾工程强控 / 简历前置追问点 / 输出净化 / 任务级模型绑定 / 报告逐题拆解 / VAD 节流（v6.2）**，**面试官角色卡三件套 / 简历锚点五分类 / 评分加减分项 / JD gap 注入 / 压力题库 / 恢复红线 + 3 次阈值 / assisted 标记（v6.3）**，**长期记忆闭环 / 2D 记忆图谱 / RAG 注入去重 / 备选题 / 语音真打断 / 面试页状态机收敛 / token 补强 / onboarding（v6.4）**，**长期薄弱点 EMA 衰减 + 过期淘汰 / 面试技能状态机 / 动态难度调度（v6.6）**，**简历库·岗位库（v7.0；同期的认证与资源归属层已于 v8.3 经 DC-10 下线）/ 流程状态显式化 / 诊断证据引用（v7.0）**，**全站 UI 统一「纸墨印章」/ 手动双主题 + 语义色 / 市场数据视觉统一 / 全国范围采集 / 岗位收藏持久化（v7.1）**，**语音链路强化：长录音 413 修复 / 开麦先停朗读 / 熔断连续失败+TTL / VAD 预滚校准 / 电平可视化 / 音色下拉 / 免手模式 + 前端测试从零起步（v7.4）**，**范围收缩：删除招聘者端与报告分享，回归求职者单端（v7.5，见 CHARTER DC-08）**。
- **技术栈**：Python 3.12 / FastAPI + WebSocket / SQLite (aiosqlite) / 多 AI 后端 / 原生 ES Module 前端 + Chart.js / three.js（v8.7，**仅 landing 落地页**动态 import，主应用零框架纪律不变）/ Playwright（v4.1 采集）/ 小米 MiMo 云端语音（v4.2，TTS/ASR 按官方 chat/completions 协议，域名 api.xiaomimimo.com）
- **当前版本**：v8.7（落地页 three.js 秀场动效改版；v8.4「能力画像按岗位分组」在研，设计稿见 `docs/specs/`，见 CHANGELOG.md）

## 常用命令

```bash
python run.py                    # 启动开发服务器（端口 8000，热重载）
python run.py lint               # [v3.2] 运行 import-linter 分层契约检查
python -m pytest tests/ -q       # 运行后端测试套件（当前 1079 用例 + 1 live_llm 抽检默认跳过）
pip install -r requirements.txt  # 安装依赖（含 dev 依赖）
python -m playwright install chromium  # [v4.1] 市场数据实时采集所需（跳过则实时采集不可用）
cd frontend && npm run build     # [v7.0] 改前端后必须构建，run.py 托管的是 dist（不入库）
cd frontend && npm run test      # [v7.4] 前端 vitest 套件（voice.js / interview.js / landing.js，77 例）
```

## 项目结构

```
AI模拟面试官/
├── CHARTER.md              # [v3.2] 不变宪章：架构约束/决策卡/已知局限/范围纪律
├── CHANGELOG.md            # 版本迭代叙事（v2 → v8.3）
├── CODEBUDDY.md            # 本索引入口
├── .importlinter           # [v3.2] 分层依赖契约（L1-L4，import-linter 强制检查）
├── .env / .env.example     # 环境变量
├── requirements.txt        # Python 依赖（含 dev 依赖 import-linter）
├── run.py                  # 一键启动 + lint 子命令
├── backend/                # FastAPI 后端（分层 L1-L4，见 CHARTER.md）
│   ├── market/crawler/     # [v4.1] B 档内嵌 Playwright 采集子包（L2，随 market 同层）
│   ├── voice_service.py    # [v4.2] MiMo 云端语音服务（TTS/ASR 代理，L2/L3）
│   ├── output_sanitizer.py # [v6.2] 面试话术输出净化（禁Markdown/舞台提示/垫词，L2）
│   ├── resume_anchors.py    # [v6.3] 简历锚点五分类（技术选型/量化/架构/业务/团队，L2）
│   ├── score_adjustments.py # [v6.3] 评分规则化加减分项（确定性正则 + evidence，L2）
│   └── pressure_bank.py     # [v6.3] 压力题库（5 类 16 道，与简历/JD 解耦，L2）
│   └── knowledge_store.py  # [v6.0] 命名空间知识库（rag:interview/career/resume，L2）
│   ├── company_profiles.py # [v6.5] 公司风格配置层（YAML 热加载/JD 匹配/片段生成，L2）
│   ├── company_profiles/   # [v6.5] 公司风格 YAML（内置字节/腾讯/阿里，加文件即加公司）
│   ├── weakness_memory.py  # [v6.6] 长期薄弱点 EMA 衰减 + 过期淘汰（L2）
│   ├── difficulty.py       # [v6.6] 动态难度调度器（轮内自适应，L2）
│   ├── interview_skills.py # [v6.6] 面试技能状态机（有状态多轮，L3）
│   ├── interview_engine/flow.py  # [v7.0] 面试流程状态显式化（decide_next 纯函数，L3）
│   ├── profile_service.py       # [v8.0] 求职档案领域核心（四段聚合 / 建议规则表 / 五步完成度 / 技能缺口，L3）
│   ├── market/analytics.py + insight.py  # [v8.2] 图表数据聚合 / 图表 AI 解读（L2）
│   └── routers/            # [v7.2.2] APIRouter 域拆分（system/voice/sessions/assets/reports/
│                           #   question_bank/diagnostics/market/analytics/profile/interview_ws
│                           #   + state 单例 + deps 依赖）
├── frontend/               # 原生 ES Module SPA（Vite）+ Chart.js + three.js（仅 landing，双入口：index + landing）
│   ├── index.html                                         # 主 SPA 入口（v7.3 旅程分组导航；v7.5 删分享页入口）
│   ├── landing.html                                       # [v8.2] 独立产品落地页（后端 `/` 返回；v8.7 秀场动效改版）
│   ├── src/js/main.js + app.js                            # 入口装配 / Tab 切换
│   ├── src/js/landing.js                                  # [v8.7] 落地页动效总编排（three.js WebGL 墨晕 Hero + 逐字/磁性/倾斜/时间线，仅此页使用）
│   ├── src/js/navConfig.js                                # [v8.0] 导航单一数据源（五步旅程）
│   ├── src/js/profileCard.js                              # [v8.0] 能力档案首屏（建议卡 / 五维画像 / 成长曲线 / 待提升项）
│   ├── src/js/interview.js + history.js + questionBank.js # 演练域（模拟面试 / 历史记录 / 题库）
│   ├── src/js/resumeLibrary.js + positionLibrary.js       # 备战域（简历库 / 岗位库，v7.0）
│   ├── src/js/report.js + memoryGraph.js + careerPlan.js  # 洞察域（综合报告 / 长期记忆图谱 / 职业规划）
│   ├── src/js/marketData.js + cityCoords.js + src/css/pages/market.css + src/css/pages/profile.css  # [v4.1] 市场数据 Tab（v7.1 视觉按设计规格统一）；profile.css 能力档案
│   ├── src/js/themeToggle.js + src/css/theme.css         # [v7.1] 手动双主题 + 深色语义色切换
│   ├── src/css/layout.css                                # [v8.0] 壳层布局（侧栏/底部导航 + 旅程时间线 + 进度条）
│   ├── src/assets/china-geo.json                         # [v8.0] 中国地图 GeoJSON（动态 import 懒加载）
│   ├── src/css/surface.css                               # [v8.5] 质感层（环境光/玻璃/景深/渐变描边，注释单行 <link> 即整体回退）
│   └── src/css/tokens.css                                # [v7.1] 纸墨印章色值重映射（变量名不变；v8.5 质感变量族 / v8.7 landing 间距与展示字号均只增不改）
├── tests/                  # pytest 测试套件（1079 用例 + 1 live_llm 抽检；含 golden 样本回归、WS 主循环集成）
│   └── test_repo_hygiene.py  # [v7.2.2 / v8.3.2] 仓库卫生：根目录白名单 + 禁散落临时文件/测试脚本/运行产物
├── data/                   # SQLite 数据库（interview.db / market.db）
└── docs/                   # 文档两类（见 docs/README.md）
    ├── 公开文档（入库）      # README 索引 / API.md / LIMITATIONS.md / UI 规格 / 产品定位 / 前端方案 / UI 评审 / specs 设计稿
    └── 过程性资料（仅本地）  # archive（week1-week10 + 竞品研读）/ research / 答辩要点 / 测评记录 / 演示稿 / 立项报告 / AI对话存档
        # .gitignore 已排除——文件留在本地供答辩与复盘，不随仓库公开。
        # 公开文档里不要链到这些文件（GitHub 上会 404），需提及时写纯文本文件名。
```

## 分层依赖速查（详见 CHARTER.md）

| 层级 | 模块 | 强制检查 |
|---|---|---|
| L1 基础设施 | `config` `logger` `llm_client` `db` | `.importlinter` 契约 + `run.py lint` |
| L2 领域模型/数据 | `schemas` `security` `resume_parser` `resume_retriever`（v5.0，禁止依赖 L3/L4） `dimension_weights` `gap_analyzer` `knowledge_store`（v6.0，禁止依赖 L3/L4） `market/*`（含 v4.1 `crawler/` 子包，采集代码禁止依赖 L3/L4） `voice_service`（v4.2，禁止依赖 L3/L4） `output_sanitizer`（v6.2，禁止依赖 L3/L4） `resume_anchors`（v6.3，禁止依赖 L3/L4） `score_adjustments`（v6.3，禁止依赖 L3/L4） `pressure_bank`（v6.3，禁止依赖 L3/L4） `company_profiles`（v6.5，禁止依赖 L3/L4） | 同上 |
| L3 业务逻辑 | `question_gen` `diagnosis_engine` `interview_engine/*` `web_research` `question_bank` `data_support` `career_planner` `interview_skills`（v6.6） `profile_service`（v8.0） | 同上 |
| L4 应用入口 | `main` + `routers/*`（v7.2.2 域拆分） | 可依赖所有层 |

> ⚠️ **硬性提醒**：所有关键约束、决策记录、已知局限、范围纪律、开发纪律（变更前复述 / Commit Message 规范 / 推送前必做 / 项目收尾）均在 **CHARTER.md**，不在本文件。新对话请先读 CHARTER.md。
> ⚠️ **仓库卫生（v8.3.2 起 CI 强制）**：文档一律进 `docs/` 并按四区归档（见 [docs/README.md](docs/README.md)）；根目录只允许白名单内的工程文件与 `backend/frontend/tests/docs/data/.github` 六个目录，白名单见 `tests/test_repo_hygiene.py` 的 `ALLOWED_ROOT_FILES` / `ALLOWED_ROOT_DIRS`——新增散落文件会直接让 CI 红灯。
