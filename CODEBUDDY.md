# AI模拟面试官与职业规划

> 本文件是 CodeBuddy 的项目索引入口，每次新对话自动加载。**请先读以下三份文档再动手**：
>
> 1. **不变硬约束** → [CHARTER.md](CHARTER.md)（产品命题 / 架构约束 / 决策记录卡 / 已知局限 / 范围纪律）
> 2. **版本迭代叙事** → [CHANGELOG.md](CHANGELOG.md)（v2 → v3.2 各轮新增/推翻/修复）
> 3. 面向用户的完整说明 → [README.md](README.md)

---

## 快速上手

- **核心价值**：诊断候选人的回答质量（STAR 完整性 / 量化程度 / 逻辑连贯性 / 岗位相关性 / 专业深度）+ 职业规划路径（v3.2 补齐的时间轴多阶段路径）。
- **技术栈**：Python 3.12 / FastAPI + WebSocket / SQLite (aiosqlite) / 多 AI 后端 / 原生 ES Module 前端 + Chart.js
- **当前版本**：v3.2（见 CHANGELOG.md）

## 常用命令

```bash
python run.py                    # 启动开发服务器（端口 8000，热重载）
python run.py lint               # [v3.2] 运行 import-linter 分层契约检查
python -m pytest tests/ -q       # 运行测试套件
pip install -r requirements.txt  # 安装依赖（含 dev 依赖）
```

## 项目结构

```
AI模拟面试官/
├── CHARTER.md              # [v3.2] 不变宪章：架构约束/决策卡/已知局限/范围纪律
├── CHANGELOG.md            # [v3.2] 版本迭代叙事（v2 → v3.2）
├── CODEBUDDY.md            # 本索引入口
├── .importlinter           # [v3.2] 分层依赖契约（L1-L4，import-linter 强制检查）
├── .env / .env.example     # 环境变量
├── requirements.txt        # Python 依赖（含 dev 依赖 import-linter）
├── run.py                  # 一键启动 + lint 子命令
├── backend/                # FastAPI 后端（分层 L1-L4，见 CHARTER.md）
├── frontend/               # 原生 ES Module SPA + Chart.js
├── tests/                  # pytest 测试套件
├── data/                   # SQLite 数据库（interview.db）
└── docs/                   # 需求文档与周报
```

## 分层依赖速查（详见 CHARTER.md）

| 层级 | 模块 | 强制检查 |
|---|---|---|
| L1 基础设施 | `config` `logger` `llm_client` `db` | `.importlinter` 契约 + `run.py lint` |
| L2 领域模型/数据 | `schemas` `security` `resume_parser` `dimension_weights` `gap_analyzer` `market/*` | 同上 |
| L3 业务逻辑 | `question_gen` `diagnosis_engine` `interview_engine/*` `web_research` `question_bank` `data_support` `career_planner` | 同上 |
| L4 应用入口 | `main` | 可依赖所有层 |

> ⚠️ **硬性提醒**：所有关键约束、决策记录、已知局限、范围纪律、开发纪律（变更前复述 / Commit Message 规范 / 推送前必做 / 项目收尾）均在 **CHARTER.md**，不在本文件。新对话请先读 CHARTER.md。
