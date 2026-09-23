# 测试与质量保障

> 从 README 迁入（v8.9 README 瘦身）。测试不是"堆数量"，而是**分层保障 + 评测（eval）**
> 两套机制配合。产品定位与架构约束见 [CHARTER.md](../CHARTER.md)，已知局限见
> [LIMITATIONS.md](LIMITATIONS.md)。

## 测试分层

| 层级 | 代表文件 | 守什么 | 为什么必要 |
|------|----------|--------|-----------|
| ① 确定性脚手架不变式 | test_schemas / test_dimension_weights / test_score_adjustments / test_flow / test_output_sanitizer | 纯函数逻辑（Schema、权重、评分加扣分项、状态机、话术净化）一旦被改坏，立刻红灯 | LLM 不可控，但脚手架必须可控——这是"改代码不引入回归"的底线 |
| ② 端到端链路 | test_api / test_session / test_interview_ws | 简历→出题→诊断→报告全链路（HTTP）+ 面试主循环 WS 路径（心跳 / 换模式 / 结束口令 / 断连收尾）；穷尽异常 / 降级 / fallback 路径 | 保证"系统真的跑得通"，而非单个函数对 |
| ③ 内容与边界 | test_security | 注入拦截、恢复红线 | 护栏的可验证证据（护栏本身仍是启发式，见 [../.github/SECURITY.md](../.github/SECURITY.md)） |
| ④ 黄金样本评测（eval） | test_diagnosis_golden | **诊断有效性**：最弱维度抓得对不对、加扣分命中没命中、证据引用是否原话 | AI 项目最该测、却最常被忽略——单测验证"工程正确性"，eval 验证"诊断准不准" |
| ⑤ 仓库卫生 | test_repo_hygiene | 根目录白名单、临时文件、运行产物、公开 Markdown 的相对链接 | 误提交的脚本与推到 GitHub 才 404 的坏链，都在 push 阶段红灯 |
| ⑥ 门禁自证 | test_layering_gate / test_dependencies / test_web_research::TestNoEventLoopBlocking | **反向验证**：故意越层的样本必须让分层门禁变红；backend 里每个非标准库 import 必须在 `requirements.txt` 有声明；同步 LLM 调用必须跑在非事件循环线程 | 前五层只能证明"我的断言是对的"，这一层证明"门禁本身会响"。v8.10 补设：此前 `run.py lint` 恒 0 退出、`parse_pdf` 依赖未声明的 PyPDF2 而唯一断言是 `isinstance(result, str)`——两者都是"绿灯没有信息量"（见 CHARTER DC-11） |

> 测试已从"锁死 prompt 文案"重构为"从配置取追问链 / 收尾指令做行为断言"，因此
> **频繁改写提示词不会误红**。

当前规模：**1098 个 pytest 用例**（`pytest tests/ --collect-only -q` 实测，2026-09-22，
v8.10 起含门禁自证层）+ 前端 3 个 vitest 套件。

## 常用命令

```bash
# 全量测试（1000+ 用例；live_llm 抽检默认跳过，push/PR 由 GitHub Actions 自动执行）
pytest tests/ -q

# 只收集不执行，快速看用例规模
pytest tests/ --collect-only -q

# 仅跑黄金样本评测（确定性回归，默认运行）
pytest tests/test_diagnosis_golden.py -v

# 黄金样本 + 真实 LLM 抽检（需 GOLDEN_LIVE_LLM=1 + 真实 Key，烧 token，仅手动触发）
GOLDEN_LIVE_LLM=1 pytest tests/test_diagnosis_golden.py -v

# 覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing

# 分层依赖契约检查（新增/重构模块后必跑）
python run.py lint
```

前端：

```bash
cd frontend
npm run test    # vitest
npm run lint    # eslint（当前 0 error）
npm run build   # 构建冒烟：导入/语法错误即红灯
```

### 按改动范围选择

- **小改动**（单模块逻辑、bug 修复、文案）：只跑受影响模块的测试文件，
  如 `python -m pytest tests/test_gap_analyzer.py -q`。
- **大改动**（跨模块重构、核心引擎 / DB 层 / 配置变更、发版前）：必须跑全量
  `pytest tests/ -q` + `python run.py lint`。

> Windows 下无需额外操作：`run.py lint` 已内置 `PYTHONUTF8=1`，否则读 UTF-8 源码与
> 带中文注释的 `.importlinter` 会按 GBK 解码直接崩（实测 `'gbk' codec can't decode byte 0xa1`）。
>
> ⚠️ **v8.10 纠正一处长期误解**：`run.py lint` 此前执行的是 `python -m importlinter.cli lint`，
> 而该模块没有 `if __name__ == "__main__"` 守卫 —— 它只导入模块就以 0 退出，**从不执行检查**，
> 所以本地与 CI 的这一步在 v3.2~v8.9 期间恒绿。现改为直接调用 click 命令对象
> （等价于 console script `lint-imports`），并配 `tests/test_layering_gate.py` 反向自测；
> 论证与代价见 [CHARTER.md](../CHARTER.md) 的 DC-11。

## CI

`.github/workflows/ci.yml`：push 到 `master` 与所有 PR 触发，两个 job——

| Job | 步骤 |
|---|---|
| `backend` | `pip install -r requirements.txt` → `python run.py lint`（分层契约） → `pytest tests -q`（全量） |
| `frontend` | `npm ci` → `npm run test`（vitest） → `npm run build`（构建冒烟） |

**干净环境可直接跑通**，无需真实 LLM Key、无需 `playwright install chromium`：

- `tests/conftest.py` 注入占位 Key，live-LLM 抽检默认 deselect；
- 采集器测试在导入前 stub 了 playwright（见 `test_market_crawler_job_scraper.py`）；
- `package-lock.json` 已入库，`npm ci` 不会因 lockfile 缺失红灯——**新增前端依赖后
  必须把 lockfile 一起提交**，否则该步直接失败。

## 依赖维护

`.github/dependabot.yml`：每周一检查一次 pip（根 `requirements.txt`）与 npm
（`frontend/`）依赖，PR 上限 5 条。

- `requirements.txt` 只声明版本下限（`>=`），dependabot 的更新是"放宽"而非"收紧"，
  合入前仍需本地安装 + CI 绿灯；
- 前端更新 PR 会同时改 `package.json` 与 lockfile，两者不同步会让 `npm ci` 红灯；
- `openai`（后端调用入口）与 `vite` / `vitest`（构建与测试链）的 **major 升级已冻结**，
  需人工在本机 + CI 双验证后再手动抬下限。
- **但"冻结"只挡 PR，不挡首次安装**：`requirements.txt` 只有下限（`>=`）本身就允许任意高
  版本，实测干净环境今天装到 openai 3.18.0。要真正锁住版本需要上限（`<4`）或锁定文件，
  已登记为局限（见 [LIMITATIONS.md](LIMITATIONS.md) 的"依赖冻结只挡 PR"条）。
