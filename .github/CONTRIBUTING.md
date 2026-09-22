# 贡献指南

感谢关注 **AI 求职领航**。这是一个单用户本地工具，欢迎 Issue 反馈与 PR。
提功能类 PR 前建议先开 Issue 说明动机——本项目有明确的**范围纪律**（见 `../CHARTER.md`），
不在命题内的功能即使实现得再好也不会合入。

## 开发环境

```bash
# 后端（Python 3.12+）
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # 至少填一个 LLM API Key
python run.py                      # http://localhost:8000

# 可选：市场数据实时采集需要浏览器内核
python -m playwright install chromium

# 前端（Node 20+）
cd frontend
npm install
npm run dev                        # http://localhost:5173，自动代理到 :8000
```

> **改完前端必须 `npm run build`**：`run.py` 托管的是 `frontend/dist`（不入库），
> 只改 `src/` 不构建的话界面不会变化。

## 提交前必做

```bash
python run.py lint                 # ① 分层依赖契约（import-linter）
pytest tests/ -q                   # ② 后端全量测试
cd frontend && npm run test        # ③ 前端 vitest（改动前端时）
npm run build                      # ④ 构建冒烟（改动前端时）
```

四步全绿再 push，CI 会自动重跑同样内容。小改动可先只跑受影响模块的测试文件
（`pytest tests/test_xxx.py -q`），但**推送前跑全量**。详细口径见
[docs/testing.md](../docs/testing.md)。

## 分层契约（本项目最容易踩的规矩）

`backend/` 按 L1 基础设施 → L2 领域数据 → L3 业务逻辑 → L4 应用入口 做**逻辑分层**，
下半层禁止 import 上半层，由 `.importlinter` + `python run.py lint` 强制。
新增/重构模块前先看 [docs/architecture.md](../docs/architecture.md) 的分层表与代码地图，
里面还列了三个踩过的反模式（L2 反向 import `main`、绝对 import 应改相对、循环 import）。

## 门禁要能变红（v8.10 起的规矩）

一条门禁只有在"它会为坏样本变红"被验证过之后，它的绿才有意义。本项目为此踩过两次：

- `run.py lint` 在 v3.2~v8.9 期间执行的是 `python -m importlinter.cli lint`，该模块没有
  `__main__` 守卫，**只导入即以 0 退出**——本地与 CI 的这一步恒绿了七个版本；
- `parse_pdf` 依赖未声明的 PyPDF2，干净环境必然 ImportError，而当时唯一的断言是
  `assert isinstance(result, str)`——该函数任何路径都返回 str，**永不可能红**，于是把
  "错误文本被当简历正文入库"这个 P0 掩盖成了绿灯。

因此：**新增任何门禁/断言（lint 步骤、契约检查、覆盖率阈值、CI job），同时补一条反向自测**，
用一个已知坏样本证明它会失败。现成的样板见 `tests/test_layering_gate.py`（故意越层的临时包
必须让门禁变红）与 `tests/test_dependencies.py`（每个非标准库 import 必须在
`requirements.txt` 里有声明）。完整论证与"若错代价"见 [CHARTER.md](../CHARTER.md) 的 DC-11。

## Commit Message

沿用 Conventional Commits，中文描述，带版本时写 scope：

```
feat(interview): v8.6 模拟面试模块改进（诊断链路 / 主循环 / WS 契约）
chore(deps): 冻结 openai / vite / vitest 跨 major 升级
```

禁止"fix bug""优化代码"这类空泛描述。有实质改动时必须能回答两件事：
**改了什么**、**为什么改**。

## 文档同步

改动落地时同步对应文档，不要留到"以后补"：

| 改动类型 | 要更新 |
|---|---|
| 用户可见的功能 / 使用方式 | `README.md` |
| 版本迭代 | `CHANGELOG.md`（近期）/ `docs/changelog-archive.md`（历史） |
| 架构约束、产品命题、有争议的取舍 | `CHARTER.md`（须补决策记录卡 DC-XX） |
| 模块地图、分层归属 | `docs/architecture.md` |
| 测试与 CI 口径 | `docs/testing.md` |

文档里的数字（用例数、端点数、覆盖率）**必须实测后写入**；公开 Markdown 不得链向
未入库的文件——这类坏链只在 GitHub 上暴露，已由 `tests/test_repo_hygiene.py` 在 CI 断言。

## 已知局限不是 bug

[docs/LIMITATIONS.md](../docs/LIMITATIONS.md) 里列的条目（无认证、护栏可绕过、SQLite
扩展性、语音半双工等）是**已知的、刻意的取舍**。针对它们的 Issue 我们更希望看到的是
新的证据或使用场景，而不是"应该生产级加固"。安全相关请读
[SECURITY.md](SECURITY.md)。
