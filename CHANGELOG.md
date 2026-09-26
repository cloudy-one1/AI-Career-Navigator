# 变更日志（CHANGELOG）

> 记录 **v8.0 → v8.11** 的版本迭代叙事（新增 / 推翻 / 修复 / 范围）。v7.5.0 及更早的完整
> 历史见 [docs/changelog-archive.md](docs/changelog-archive.md)。不变的架构约束与决策记录见
> [CHARTER.md](CHARTER.md)，贡献流程见 [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md)。
>
> **品牌现名：AI 求职领航（曾用名 AI 求职陪跑平台，v8.3 更名）。旧版本章节中的“AI 求职陪跑”为历史名称，保留不删。**

---

## v8.11 部署安全收口 + 巨型文件按「可验证性」取舍（2026-09-24）

> 起因是一份外部给出的风险清单。动手前先把它的 15 条量化结论在 HEAD（`d405cee`）上重测一遍：
> **9 条成立、6 条不成立，且 6 条错的方向完全一致——全部低估**（`session.py` 写 1531 行实为
> 1756、`db.py` 写 1120 实为 1370、`interview.js` 写 1717 实为 2029、`except Exception` 写 60 处
> 实为 105 处、ruff 写 248 项实为 380 项）。这些数字在近 5 个提交里一个都对不上，不是测量过期，
> 是从没测过。本轮一切以下表实测值为准。

### P0 部署安全：把「默认暴露」改成「默认本机」

清单把问题写成"`HOST=0.0.0.0` + 全站免登录"，但**容器内的 `HOST=0.0.0.0` 是必需的**——改成
`127.0.0.1` 只会让宿主机端口映射直接打不通。真正的暴露面是端口**发布到宿主机的哪个地址**，
而 `docker-compose.yml` 原来写的是裸 `"${PORT:-8000}:8000"`，等价于发布到 `0.0.0.0`：
开箱即向整个局域网开放 `./data` 下全部简历与面试数据（免登录，见 DC-10）。

- 改为 `"${BIND_ADDR:-127.0.0.1}:${PORT:-8000}:8000"`。`docker compose config` 实测默认解析出
  `host_ip: 127.0.0.1`；设 `BIND_ADDR=0.0.0.0` 时正确放开——扩大访问面成为显式 opt-in。
- 文件头补「部署边界」警告块，含免登录后果、局域网/公网两条正确扩面路径，以及
  "`HOST=0.0.0.0` 不要改"的反向说明（防止下一个读到清单的人去改错的那一处）。
- 新增 `test_compose_publishes_port_to_loopback_by_default` 钉住默认值，并按 DC-11 证伪：
  改回裸端口写法该测试即变红。

### 门禁自测与真实门禁走了两条路（中文 Windows 上必红）

`run.py:31` 给 import-linter 子进程设了 `PYTHONUTF8=1`，而 `tests/test_layering_gate.py` 的
`_run_lint` 没设。`.importlinter` 里契约名是中文，import-linter 按平台默认编码读它，在 zh-CN
Windows 上即 GBK → `'gbk' codec can't decode` → 两个反向自测**确定性失败**。也就是说这套
"证明门禁会响"的自测，测的其实是"子进程恰好用了什么编码"。已补 `env=dict(os.environ,
PYTHONUTF8="1")`，2 passed。该失败在本轮改动前就存在。

### 清掉 9 处「重置连接」的死写

`tests/` 里 9 处 `db_mod._db = None` 意在"换库前丢掉缓存连接"，但 `get_db()` 每次调用都新开
一条 aiosqlite 连接，**全仓库没有任何地方读 `_db`**。删除全部 9 处后全量仍绿，等于反向证明了
它们是假的。这类写法的害处不在冗余，而在让读者以为存在一个可以重置的连接缓存。

### 巨型文件：按「拆了能不能验证」筛，而不是按行数排

| 目标 | 覆盖率 | 判定 | 依据 |
|---|---|---|---|
| `backend/db.py` 1370 行 | 高 | **拆** | 57 个平铺函数、唯一公共依赖 `get_db`、仅 1 处跨域调用、0 个 mock 目标 |
| `python_job_scraper.py` 1249 行 | 20% | **拆数据 + 提纯函数** | 817 行是城市码表；`scrape_jobs` 函数体覆盖 **0%** |
| `session.py` 1756 行 | **94%** | **不拆** | 8 个候选分组共 1141 行、共享 **72 个 `self` 属性**（同一个 130 行 `__init__` 定义） |
| `interview.js` 2029 行 | 薄 | **不拆** | 64 个函数共享 27 个模块级 `let`，仅导出 2 个 |
| `ws_interview` 498 行 | 58% | **不拆** | 未覆盖的 107 行正是最深的分支（技能动作/追问/补评），且是 `send_json` 串起来的顺序 IO |

后三者的共同点：拆出来不是分解而是**搬家**——把同一份共享状态和同一段顺序 IO 挪到另一个文件，
复杂度不减、可读性反降，而且要在没有测试的地方动实时面试主链路。DC-11 的口径是"绿灯要能被
证伪"，同理：**重构要能被验证**。

- `backend/db.py` → `backend/db/` 包（10 个文件，最大 `schema.py` 382 行）。57 个函数
  **AST 逐字等价**；`__init__.py` 显式 re-export，`from backend.db import X` 与 `backend.db.X`
  两种写法均不受影响；9 个私有名不外露（包外引用实测 0 处）。ruff 16 项 vs 原文件 17 项。
  门禁 KEPT，且验证过子模块不是盲区：临时让 `backend/db/schema.py` 向上 import，门禁准确报出
  `backend.db is not allowed to import backend.interview_engine` 并指到具体行。
- 码表外置为 `backend/market/crawler/job_site_dicts.py`（`CITY_CODES` 388 项 / `CITY_PINYIN`
  388 项 / `PROVINCE_MAP` 33 项 / `JS_FETCH_API` 1121 字符，**逐项值相等校验通过**），
  `python_job_scraper.py` 1249 → **437 行**。
- `scrape_jobs` 310 → 258 行：把内联的纯数据变换提成 `build_search_url` / `_job_address` /
  `_job_content` / `to_job_record`，并补 17 个用例。这一步的意义不是缩短函数，而是**在没有
  安全网的地方造出安全网**——那段逻辑原先藏在 0% 覆盖的函数体里，提成模块级函数后才能被测。
  该文件覆盖率 20% → 30%，剩余缺口正好只剩 `scrape_jobs` 的浏览器流程本身。
  两处重复的搜索页 URL f-string 合并为一个函数。

### 异常处理：105 处分类后，只动「连日志都不留」的那 14 处

按处理策略实测分布：记日志后落到后续流程 48、记日志+返回降级值 24、记录后重抛 17、
**静默 `pass` 8**、记日志+continue 2、**不记日志直接返回降级值 3**、**不记日志改默认值 3**。

宽捕 + 记日志 + 降级对一个 LLM 驱动的应用是合理设计，不是债；**静默吞掉才是**——它让 bug
以"数据本来就少"的形式消失。所以本轮：

- 7 处静默降级补上留痕，每处都写清为什么这个降级值得记录：`system.py` 读不出历史会话会被
  返回成"没有历史会话可预热"（把 DB 故障说成用户没面过试）、查缓存失败会被当成未命中于是
  **白花一次 LLM 调用**、`report.py` 难度摘要抛异常与"未启用"返回同一形状（把 bug 读成配置）；
  `question_gen.py` / `market/service.py` 同类。
- 2 处 `json.loads` 聚合从 `except Exception` 收窄到 `(JSONDecodeError, TypeError)`：
  `KeyError` 之类意味着 SELECT 列名漂了，应当炸出来而不是静默少一列。两侧各补一条用例，
  并逐条证伪（把 `TypeError` 从元组里去掉，对应用例即变红）。
- 5 处 scraper 的 `except Exception: pass` **保留**——装饰性滚动、关闭已死页面、WAF 探测轮询，
  这些逐轮打日志只会刷屏。但 WAF 超时告警现在会带上末次探测异常，否则分不清"被拦"和"浏览器挂了"。
- 结果：`except Exception` 站点 105 → 103，ruff BLE001 69 → 64（其中 2 处是真收窄，
  5 处是按仓库既有约定加 `# noqa: BLE001` 并写明理由）。其余 91 处本就是"记日志 + 降级"的
  既有设计，本轮未动——把它们一律改成精确类型是产品化阶段的活，收益低于风险。

### 更正本文档自己的两处过期数字

- 上节「范围纪律」写的 **ruff 248 项**：HEAD 实测 **380 项**，248 从未成立。
- 上节「遗留」写的 **`session.py` 1756 行/63 方法**：1756 行正确，方法数实为 **65**。

### 把「未定位归属」的 flaky 定位到了

上节登记的"一次偶发 `PytestUnhandledThreadExceptionWarning`"本轮**独立复现并归因**：
12 次全量（5 次默认 + 7 次以 `-W error::pytest.PytestUnhandledThreadExceptionWarning` 跑）中
命中 **4 次 ≈ 1/3**，且 4 次落点完全一致——`tests/test_interview_ws.py::TestPingPong::
test_ping_replies_pong_and_keeps_round_running`，线程名 `_connection_worker_thread`
（aiosqlite 每条连接自带的工作线程），底层 `RuntimeError: Event loop is closed`，
且 `args = (<Future pending>, RuntimeError(...))`。

机制已可解释：`tests/conftest.py:30` 的 `event_loop` 是 **session 级**，整场共用一个循环、
会话结束才 `loop.close()`；报错是某条 aiosqlite 连接的工作线程在循环已关闭后仍想往它调度回调。
也就是说**有连接没被 close 掉**——最可能是 WebSocket 被 abrupt 断开时 `finally: await db.close()`
未跑完，而 `TestPingPong` 正是突然断开连接的那条用例。这与同节另一条遗留
"WS 非断连异常分支不落终态 / `active_sessions` 无 TTL"是同一根线上的两个症状。

本轮**只登记不修**：确保"取消路径上连接必关"是对 WS 主链路的行为变更，风险高于本轮口径。
已写入 `docs/LIMITATIONS.md`。复现命令与命中概率（约 1/4 全量）一并记录，避免下一个人从头再找。

### 验证（本机 Python 3.13.2 / zh-CN / cp936，2026-09-24）

- 后端全量 `pytest -q`：**1117 passed, 1 skipped**（用例数 1098 → 1118，本轮新增 20 条：
  采集器纯函数 17、tags 收窄两侧各 1、compose 门禁 1；本轮起点 HEAD 在本机为
  1095 passed + 2 failed + 1 skipped）。
- `python run.py lint`：**KEPT**（Analyzed 69 files, 164 dependencies）。
- `docker compose config`：默认 `host_ip: 127.0.0.1`；`BIND_ADDR=0.0.0.0 PORT=8001` →
  `host_ip: 0.0.0.0, published: 8001`。
- ruff 全仓 380 → 369；新增/改动的每个测试都做过反向证伪（compose 门禁、两处 tags 收窄、
  分层门禁的编码修复）。
- 未做：前端两个巨型文件、`ws_interview`、`session.py` 的拆分（理由见上表）；
  余下 91 处宽捕站点属"记日志+降级"的既有设计，不在本轮动。

---

## v8.10.1 依赖维护：清空 8 条悬挂的 dependabot PR（2026-09-23）

> v8.8 接入 dependabot 时写的口径是"每周自动维护依赖"，但接入后 PR 一直挂着没人处置：09-03 那批
> 5 条（#1/#2/#3/#4/#8）+ 后续两条 npm（#9/#10）+ 一条 three（#11），共 8 条、最长悬挂 20 天
> ——对外承诺与实际状态相反。本轮全部本地复验后落地，队列清零。

- **pip**：`openai>=1.30.0 → >=1.109.1`（#8）、`aiosqlite>=0.20.0 → >=0.22.1`（#4）；
  同批再清掉更早的三条同主线下限提升——`pydantic>=2.6.0 → >=2.13.5`（#3）、
  `playwright>=1.40 → >=1.62.0`（#2）、`pyyaml>=6.0 → >=6.0.3`（#1）。
- **npm**：`three ^0.185.1 → ^0.186.0`（#11）、`eslint ^10.9.1 → ^10.10.0`（#10，lockfile 实际解析到 10.11.0，仍在 `^10.10.0` 区间内）、`globals ^17.11.0 → ^17.12.0`（#9）；`package-lock.json` 随改动一并更新（`npm ci` 要求两者同步）。
- 同等改动落地后 GitHub 会自动关闭这些 PR，无需逐个点 Merge（前 5 条实测已在推送后自动关闭）。
- **顺带发现一处口径与机制的偏差（登记为局限，不在本轮修）**：v8.8 用 `ignore: semver-major`
  "冻结 openai 跨 major"，理由是"抬高下限会让所有新装环境直装新版"。但 `requirements.txt`
  只写下限这一件事本身就已允许任意高版本——实测只装 requirements 的干净环境今天解析到
  **openai 3.18.0**，两次复验的第二天再装已到 **3.19.0**（本机 dev 仍是 2.38.0，CI 为 3.x），
  冻结只挡住了 PR，没挡住首次安装，也没挡住版本每天在漂。全量用例在 3.18/3.19 下通过说明
  当前代码兼容，但这是运气不是机制；要真正控制风险需要上限或锁定文件（见 `docs/LIMITATIONS.md` 新增条目）。

### 验证（本机 Python 3.13.2 / zh-CN，2026-09-23）

- 干净 venv 只装新 `requirements.txt`：解析到 pydantic 2.13.5 / playwright 1.63.0 /
  pyyaml 6.0.3 / openai 3.19.0 / aiosqlite 0.22.1 / pdfplumber 0.11.10 →
  `pytest tests -q` **1097 passed, 1 skipped**，`run.py lint` 在同一 venv 内 **KEPT**。
  （同一套用例在干净 venv 42s 跑完、本机 dev 环境约 240s，差异未归因，不影响通过判定。）
- 前端 `npm run test` **77 passed**；`npm run build` 通过（three 0.186 的 async chunk
  746.94 kB，仍只在 landing 页）；`npm run lint` 0 error / 25 warning（与本轮前持平）；
  `npm audit --omit=dev` **0 漏洞**（余下告警全在 dev 链，即被冻结的 vite / vitest）。

---

## v8.10 守护机制纠偏：门禁空转 / 依赖声明错位 / 引用无校验 / 事件循环阻塞（2026-09-22）

> 起因是本轮外部审计提出的一个判断题：**"声称的守护"有没有在守护**。结论是四处没有，
> 且它们的失效方式同构——绿灯本身不携带信息。本轮不改产品功能、不加模块，只把这四条
> 从"看起来有"变成"确实有"，并为每一处补一条**反向自测**（论证与代价见 CHARTER DC-11）。

### 1. 分层门禁 `run.py lint` 此前从不执行检查（v3.2~v8.9 恒绿）

- `run.py` 执行的是 `python -m importlinter.cli lint`，而 `importlinter/cli.py` **没有
  `if __name__ == "__main__"` 守卫**：`-m` 方式只导入模块即以 0 退出，连帮助都不打印。
  于是本地打印"检查通过 ✓"只花 0.4 秒，CI 的同一步骤同样恒绿。旧注释里"裸
  `-m importlinter.cli` 只打印帮助不执行检查"的说法也是错的（实测无任何输出）。
- 改为直接调用 click 命令对象 `importlinter.cli.lint_imports_command`（等价 console script
  `lint-imports`），实测分析 **59 文件 / 144 依赖 → KEPT**（结论未变，变的是它现在真的在查）。
- 新增 `tests/test_layering_gate.py`：① 本仓库契约必须 KEPT 且输出含 `Analyzed`（防空转复发）；
  ② **故意越层的临时包必须让门禁变红**——已实测对照：违规样本下旧命令 exit 0 无输出、新命令 exit 1
  并打印 `not allowed to import`。
- 顺带纠正 CHARTER 约束 2 的层级表与 `.importlinter` 的漂移：表内缺 `profile_service` /
  `output_sanitizer` / `resume_anchors` / `score_adjustments` / `pressure_bank` 五个模块，
  且把"同层互依赖"写成不允许（实际存在 `gap_analyzer → market.store` 等 L2→L2）。

### 2. 干净环境里 PDF 简历必然解析失败，且失败被当成正文入库

- `parse_pdf` 一直 `from PyPDF2 import PdfReader`，而 **PyPDF2 既不在 `requirements.txt`、
  也不是任何声明包的传递依赖**（`pdfplumber` 依赖的是 pypdfium2）；同时 `requirements.txt`
  声明的 `pdfplumber` 全仓无一处 import。按 README 步骤装出的环境（CI / Docker / 评委本机）
  必然 ImportError。
- 更糟的是失败处理方式：`except Exception` 把异常转成**非空**字符串 `[PDF 解析失败: ...]`，
  于是路由的"提取不到文本"判断放过它 → `/api/resumes/upload` 返回 **201**、把这行错误文本
  存进简历库并注入出题 prompt。实测复现：`char_count: 59`、`raw_text: "[PDF 解析失败: ...]"`。
- 修复：解析层改用已声明的 **pdfplumber**（实测样例中文简历 1541 字，与原 PyPDF2 路径 1542 字
  基本等价），提取不到文本一律返回**空串**；三个上传端点统一 `400 未能从文件中提取到文本…`。
- 测试侧把永不可能红的 `assert isinstance(result, str)` 换成真断言（成功拼接 / 失败返回空串 /
  路由 400 且不入库），并新增 `tests/test_dependencies.py`：backend 内每个非标准库 import
  必须在 `requirements.txt` 有声明（别名与传递依赖显式登记），把这一整类问题挡在 CI。

### 3. "原话引用可复核"这一承诺此前运行期无人核对

- Prompt 要求每维度给 `quote`（候选人原话摘录），但 `normalize_result` 只是 `str(...)` 透传；
  唯一检查字面子串的 `test_golden_quotes_are_literal_answer_substrings` 用 FakeLLM 回声人工
  写好的引号——**它验不出模型把"摘录"写成"概括"**。
- 现在 `_score_and_weakest`（首评与 v8.6 补评共用同一入口）做字面比对：空白归一、含省略号的
  摘录按段全命中才算可核；不匹配标 `quote_verified=false`、报告页灰显并注"未在原话中核对到"，
  **保留引用不删除**（删了就把模型行为证据一起抹掉）。
- 可核率经 `/api/health` 的 `quote_stats` 暴露（进程内累计，重启归零），答辩/复盘可直接引用一个
  数字而非"我们要求模型引用原话"。端点数不变（复用 health，未新增路由）。

### 4. 事件循环阻塞与 LLM 无超时

- `web_research.enrich_jd_with_research` 在 `async def` 里直连同步 `chat_json`——全项目 11 处
  同步 LLM 调用里唯一漏网的（同函数上文的 DDG 请求已正确 `await to_thread`），且位于
  `create_session` 这条最高频入口。改为 `await to_thread(...)`，并加
  `test_web_research::TestNoEventLoopBlocking`（桩函数记录自身所在线程，断言不在主线程）。
- 简历/JD 上传的解析（逐页 `extract_text()`，CPU 密集）同样从事件循环移入 `to_thread`。
- 新增 `LLM_TIMEOUT`（默认 60s）并传给全部 6 处 `OpenAI/AsyncOpenAI` 构造点。此前不传即落到
  SDK 默认 **600s**：上游挂起会把面试主循环钉死十分钟，而且 SDK 只在超时/报错后才换下一个
  fallback 候选——"没有超时"实际等于"降级链一并失效"。`tests/test_llm_client.py` 钉住主候选与
  fallback 候选都带有限超时。

### 5. 文档与口径收口

- `docs/答辩要点_测试与质量保障.md` 的"约 900 用例"（v7.x 遗留）统一为实测 **1098**；删掉已随
  v7.5 下线的"分享脱敏"作为安全层证据；分层表由四层扩为六层（补 ⑤ 仓库卫生、⑥ 门禁自证）。
  初验演示脚本/讲稿、`docs/源代码交付说明.md` 的用例数与版本号同步。
- `docs/LIMITATIONS.md`：黄金样本"4 类典型回答"改为实测 **20 条人工标注样本**；新增 4 条本轮
  相关局限（守护有效窗口、PDF 解析能力上限、引用可核不阻断、超时为统一上限）。
- `docs/testing.md` 增补第 ⑥ 层与 `run.py lint` 的历史纠正；`docs/API.md` 记录 `/api/health`
  新字段与上传端点的解析失败口径；`.env.example` 增加 `LLM_TIMEOUT` 说明。
- CHARTER：新增 **DC-11 守护机制必须自证有效**；已知局限条目"50+ 用例"这类过期量级描述改为
  以 `docs/testing.md` 实测值为准。

### 验证（本机 Python 3.13.2 / zh-CN，2026-09-22）

- `python run.py lint` → 分析 59 文件 / 144 依赖，**KEPT**（真实执行，非空转）。
- `pytest tests -q` → **1097 passed, 1 skipped**（skipped 为默认关闭的 live-LLM 抽检），
  `--collect-only` 计 **1098** 条，较上轮（1080 collected / 1079 passed）**+18**：
  门禁自证 2、依赖声明 3、引用核对 6、LLM 超时 2、事件循环 offload 1、解析层单测净 +1、上传路由 3。
  其中解析层净 +1 是因为删掉了两条永不可能红的 `isinstance(result, str)` 断言。
- `pytest tests --cov=backend` → 覆盖率 **81%**（7483 statements）。
- 干净环境对照：临时 venv 只装 `requirements.txt` → `import PyPDF2` ModuleNotFoundError、
  `pdfplumber 0.11.10` 可用；样例 PDF 走新路径解析出 1541 字。
- 前端 `npm run test` 与 `npm run build` 见下节；本轮未动依赖版本。

### 范围纪律

- 未新增功能模块、未新增 HTTP 端点、未改诊断五维与双 Agent 架构（约束 1/3 不变）。
- 明确不做（课程口径）：认证/多租户、Postgres、向量 RAG、断点续答、按会话隔离 LLM 单例、
  ruff 248 项全量治理、前端测试栈重写。
- 遗留（登记不修）：`ws_interview` 498 行上帝函数与 `session.py` 1756 行/63 方法的拆分；
  WS 非断连异常分支不落终态；`active_sessions` 无 TTL；导出 HTML 的 Markdown 未转义 raw HTML；
  `api.js` 的 `token` 死参数与 `MARKET_CRAWL_TOKEN` 自锁；5 处引用未定义 CSS 变量；
  **一次偶发的 `PytestUnhandledThreadExceptionWarning`**（把该警告提升为 error 后跑全量，
  在 `tests/test_interview_ws.py::TestPingPong` 处命中 1 次；单跑该文件与 api+ws 组合各 8 次
  均未复现，HEAD 全量 1 次亦未复现，故未定位到归属；现象为工作线程内 ResourceWarning 逃逸，
  与本轮新增的 `to_thread` 调用点无确定因果关系，留待复现）。

---

## v8.9 仓库对外呈现标准化：README 瘦身 + docs 白名单 + 社区健康文件（2026-09-22）

> 起因是用户一句"把远端打造为一个正常 github 项目的样子，现在 readme 部分太过冗余"。
> 核对现状：README 已长到 **523 行 / 29.5KB**，其中 137 行是全量文件树、护栏表与测试分层表，
> 与 CHARTER.md、docs/ 重复，读者第一屏看不到"这是什么、怎么跑起来"；同时缺 CONTRIBUTING /
> SECURITY / Issue 与 PR 模板，仓库零截图。**本轮只动文档与仓库门面，运行时代码一行未改。**

### 1. README 523 → 193 行（29.5KB → 9.9KB）

- 迁出而非删除：全量代码地图 + 技术栈 + 分层表 + 诊断体系 + 面试模式 → `docs/architecture.md`；
  测试五层分工 + 常用命令 + CI/dependabot 口径 → `docs/testing.md`；内容护栏表与已知绕过方式 →
  `.github/SECURITY.md`；环境变量逐项说明改为一句话指向 `.env.example`（模板本就逐条注释）。
- 修正**仓库名漂移**：CI 徽章与 clone 地址仍指向改名前的 `AI-simulated-interviewer`，
  此前靠 GitHub 的 301 才没坏（curl 实测 `301 → AI-Career-Navigator`），统一为现名。
- 新增三张界面截图（`landing / profile / interview`，见下节口径）。
- 数字口径全部实测后写入：`pytest --collect-only` 实测 **1080 用例**（"1000+"成立）；
  FastAPI 路由实测 **59 个 `/api` 端点 + 1 个 WebSocket**；`docs/LIMITATIONS.md` 实测 23 条；
  `INTERVIEWER_STYLES` 实测 7 种。

### 2. docs/ 由"整目录不跟踪"改为白名单入库

`.gitignore`：`docs/` → `docs/*` + 6 条 `!` 放行（`README.md` 索引 / `architecture.md` /
`testing.md` / `API.md` / `LIMITATIONS.md` / `changelog-archive.md`）。API.md 与 LIMITATIONS.md
本就写好了却因整目录排除而只在本地，这次一并公开。原 `docs/README.md` 的本地视角清单
（过程稿 / 竞品调研 / 验收材料）移入 `docs/本地资料索引.md`，该文件仍不跟踪。

### 3. 社区健康文件全部放 `.github/` 下

`CONTRIBUTING.md`、`SECURITY.md`、`PULL_REQUEST_TEMPLATE.md`、
`ISSUE_TEMPLATE/{bug_report,feature_request,config}`。**刻意不放根目录**——GitHub 认 `.github/`
路径，而根目录白名单（v8.4 第 4 条卫生断言）不必为此扩容。

### 4. CHANGELOG 拆分

185KB → 正文 **51KB（v8.0 起）** + `docs/changelog-archive.md` **135KB（v2 → v7.5.0）**。
搬迁区间实测不含相对链接，故不产生新坏链；逐字搬迁，不改写历史叙事。

### 5. 截图的取材与脱敏

用 Playwright 以 1440×900 @2x 抓取，缩到 1x 后存 PNG（325KB / 483KB / 481KB）。
入库前先查 `data/interview.db`：24 份简历全为 `张三` / `e2e_resume` / `李明浩(test)` 等
测试样本，无真实个人信息——**截图带数据，先确认数据不是本人的**。

### 6. 验证

- `tests/test_repo_hygiene.py` 五条全绿（新入库 Markdown 的相对链接受检；根目录白名单未变）；
- `python run.py lint` 分层契约通过；全量 `pytest tests -q` **1079 passed, 1 skipped**
  （skipped 为 live-LLM 抽检，需真实 Key 手动触发），与"1080 collected"口径一致；
- 新 README 的 CI 徽章 URL 与 clone 地址 curl 实测 200，不再依赖 301。

---

## v8.8 标准开源工程要素核对：dependabot 接入 + LICENSE 署名 + CI 干净环境复核（2026-09-03）

> 起因是用户递来一份标准开源仓库核对清单：**LICENSE / README（含快速开始）/ CI（干净环境能跑通）/ CHANGELOG / dependabot**。**核对结论**：五项里四项早已在库——CHANGELOG 自 v2 记到 v8.7、CI 已跑后端全量 pytest + 前端 vitest/build、README 快速开始与 `.env.example` 逐条对齐；真正的缺口只有两个：**dependabot 完全缺失**（`.github/` 下只有 workflows/）、**LICENSE 版权持有人署名空缺**（仅 `Copyright (c) 2026`）。本轮按"缺什么补什么"处理，不重做已有文件。

### 1. dependabot 接入（新增 `.github/dependabot.yml`）

- 两个 package-ecosystem：`pip`（`directory: "/"`，对应根 `requirements.txt`）与 `npm`（`directory: "/frontend"`，对应 `package-lock.json`），`version: 2`。
- 节奏 `weekly`（`day: monday`）、`open-pull-requests-limit: 5`，避免依赖变更一次涌入；**commit message 不自定义前缀**，沿用 dependabot 默认，以免与 CHARTER 的 Commit Message 规范冲突。
- 文件头注释钉住两条合并门槛：`requirements.txt` 只声明版本下限（`>=`），合入前仍需本地安装 + CI 绿灯；前端更新会同时改 `package.json` 与 lockfile，而 CI 走 `npm ci`，两者不同步直接红灯（ci.yml 已有同款口径注释）。
- **首轮扫描当天即产出 7 个 PR**（pip 5 + npm 2，各自卡在 `open-pull-requests-limit: 5`），按风险分三档处置：
  | PR | 依赖 | 变化 | 处置 |
  |---|---|---|---|
  | #1 | pyyaml | 6.0 → 6.0.3 | 合并（patch，仅加 Python 3.14 支持） |
  | #3 | pydantic | 2.6.0 → 2.13.5 | 合并（同 major，changelog 全为 fixes） |
  | #4 | aiosqlite | 0.20.0 → 0.22.1 | 合并（breaking 已核对，见下） |
  | #2 | playwright | 1.40 → 1.62.0 | 保留待人工验证（跨 22 个 minor，且需重装 chromium） |
  | #6 | openai | `>=1.30.0` → `>=3.6.0` | **冻结**（跨 2 个 major，直击 `backend/llm_client.py`） |
  | #5 | vite | 5.4.21 → 8.2.2 | **冻结**（跨 3 个 major，构建链配置可能不兼容） |
  | #7 | vitest | 2.1.9 → 4.1.11 | **冻结**（跨 2 个 major，测试 API 可能变） |
- **aiosqlite 0.22 的 breaking 已核对**：官方 changelog 写明 `Connection` 不再继承 `threading.Thread`，不用 context manager 的调用方必须 `await close()` 或 `stop()`，否则 ResourceWarning。本项目 `backend/db.py`、`backend/market/store.py`、`backend/market/importer.py` 全部是 `db = await get_db(); try: ... finally: await db.close()` 模式——**正是新版要求的做法**，故 #4 不受影响。
- **跨 major 升级一律加 `ignore: version-update:semver-major` 冻结**（openai 在 pip 段，vite / vitest 在 npm 段）。理由：`requirements.txt` 只写下限（`>=`），抬高下限等于要求**所有新装环境**直装新版——一旦有 breaking，"首次安装即崩"会外溢到 README 的快速开始流程，而 PR 页面的 checks 只能覆盖 CI 那一种环境。冻结后需人工在本机 + CI 双验证，再手动提下限。

### 2. LICENSE 补署名

- 第 3 行 `Copyright (c) 2026` → `Copyright (c) 2026 cloudy-one1`，与 git 提交作者 / GitHub 账号一致；MIT 正文一字未动。

### 3. CI 干净环境复核（结论：不改 CI）

逐行复核 `.github/workflows/ci.yml`，三个"干净环境常见红灯源"在本仓库都已有兜底，故本轮不动 CI 工作流：

| 风险点 | 兜底 |
|---|---|
| 无真实 LLM Key 导致 pytest 收集失败 | `tests/conftest.py` 模块级注入 `AI_PROVIDER=deepseek` + `DEEPSEEK_API_KEY=test-key`；live-LLM 抽检默认 skip（需 `GOLDEN_LIVE_LLM=1` 手动触发，见 ci.yml 口径注释） |
| playwright 浏览器未安装 | 采集器测试在导入前 stub playwright（见 `test_market_crawler_job_scraper.py`），无需 `playwright install chromium` |
| `npm ci` 与 lockfile 不同步 | `frontend/package-lock.json` 已入库（85KB），CI 显式 `cache-dependency-path` 指向它 |

本地冒烟（非 CI 真实环境，用于确认本轮改动未破坏既有门禁）：`python run.py lint` 通过 ✓；`python -m pytest tests/test_repo_hygiene.py -q` **5 passed** ✓（dependabot.yml 位于 `.github/` 内，不触发根目录白名单）；`npm run build` 8.70s 构建成功、零告警 ✓。

### 4. README / CODEBUDDY 同步

- README：徽章区补 GitHub Actions CI passing 徽章；「工程保障」特性补入 dependabot；「测试策略」章节新增「持续集成与依赖维护」小节，写明 CI 两个 job 与干净环境跑通的三条兜底、dependabot 的节奏与合入门槛。**快速开始**一节与 `.env.example` 逐条比对无偏差，未改动。
- CODEBUDDY.md：当前版本 → v8.8。

### 5. 文档跟踪范围调整：CHANGELOG / CHARTER 恢复入库

- **起因**：核对「CHANGELOG」这一项时发现它**根本不在仓库里**——`.gitignore` 按此前"对外仓库不含文档"的旧决策，把 `docs/`、`/CHANGELOG.md`、`/CHARTER.md`、`/CODEBUDDY.md` 一并排除（仓库内 docs 文件数为 0）。也就是说"CHANGELOG 记录变化"此前只在本地成立，推到 GitHub 看不到。经用户确认：解禁 CHANGELOG 与 CHARTER（标准开源要素），docs/ 与 CODEBUDDY.md 维持不入库。
- **只删 .gitignore 两行会让 CI 红灯**，故连带完成三件事：
  1. `tests/test_repo_hygiene.py` 的 `ALLOWED_ROOT_FILES` 登记 `CHANGELOG.md` / `CHARTER.md`（第 4 条根目录白名单否则直接失败）；
  2. CHANGELOG 与 CHARTER 文件头对 `CODEBUDDY.md` 的 Markdown 链接改为**纯文本 + 注明「本地文档，未入库」**（第 5 条断言「被跟踪 Markdown 的相对链接目标必须也被跟踪」会拦死链）；
  3. 同步改写测试文件头 docstring 与第 4 条断言提示语里的旧口径（"对外仓库不收文档"）。
- 验证：`python -m pytest tests/test_repo_hygiene.py -q` **5 passed**（白名单 + 链接检查双绿）；`git status` 确认两份文档已从 untracked 进入索引。

### 6. 范围纪律

- 只动工程配置与文档：LICENSE / .gitignore / .github/dependabot.yml / tests/test_repo_hygiene.py / CHANGELOG.md / CHARTER.md / README.md / CODEBUDDY.md；后端与前端源码、CI 工作流本体一行未改；不引入任何新依赖（运行时与构建时均无）。
- 不 commit / 不 push（文档解禁随下次提交生效）。

---

## v8.7 落地页秀场动效改版：three.js WebGL 墨晕 + 大留白重排（2026-09-01）

> 起因是用户递来 `MengTo/threeui`（React + Three.js 的 WebGL shader 视觉组件库）要求「参考这个项目做一个动效十足的首页，注意留白，元素之间多留空，别把页面塞满」。**关键决策**：用户在技术路线选项中显式选择**引入 three.js**——这一条覆盖了 v8.5 条目里「刻意不借鉴 shader 实时背景、不引 three.js」的记录决策；覆盖**仅限 landing.html 独立入口**，主应用「零框架依赖」纪律不变（three 拆为 735KB min / 190KB gzip 的 async chunk，landing 首屏渲染后才拉取；主应用包 385KB 不受影响）。范围经用户确认：只改 landing 落地页，主应用与后端零改动；动效强度「拉满秀场感但仍不碰霓虹/弹跳/粒子爆炸」；允许为大留白重排区块。

### 1. WebGL 流动墨晕 Hero

- `frontend/src/js/landing.js`（新增，约 380 行）的 `initHeroGL()`：动态 `import('three')`，全屏三角形 + 自定义 GLSL fragment shader（fbm 噪声，桌面 5 octaves / 移动端 3），印章红 / 黄铜 / 青绿三个色源在墨黑底上以约 36s 周期低频流动，指针视差 lerp 跟随。色值与 tokens 纸墨色板同源（`HERO_COLORS` 注释注明同步关系）。
- 渲染循环只在 Hero 可见（IntersectionObserver threshold 0.02）且页面处于前台时运行；`pixelRatio` 封顶 1.5；`pagehide` 释放 GL 资源。
- **三级降级**：three chunk 加载失败 / WebGL 上下文创建失败 / `webglcontextlost` → canvas 透明，露出 `.ld-hero::before` 的 CSS 径向墨晕（v8.2 既有层，保留为永久 fallback，不可删）；`prefers-reduced-motion` → 渲一帧静态（uTime=12）后永不启动循环；JS 整体未加载 → 内容默认可见（`.ld-reveal` 渐进增强契约不变，不出现 opacity:0 死页）。

### 2. DOM 秀场动效（缓动统一 --ease-out 系，时长 250–650ms，不用弹跳曲线）

- **逐字标题揭示**：`splitChars()` 遍历标题子节点（保留 `.ld-hero-accent` 嵌套配色），逐字包 `.ld-char`（`--ci` 错峰 40ms）；原文写 `aria-label`、字 spans `aria-hidden`，读屏不念两遍。keyframes 在 motion.css 新增第 11 节（`ld-char-in`：上移 + 轻旋 4deg + 模糊消散，640ms）。
- **磁性按钮**：pointermove 吸附（强度 0.28、钳 ±12px）+ 离开 lerp 归位；仅 `pointer:fine` 启用。
- **卡片 3D 倾斜 + 高光跟随**：`normPointer → tiltAngles`（±7deg 钳制）lerp 驱动 `perspective(900px) rotateX/Y`，`--mx/--my` 锚定 `::before` 径向高光。
- **纵向时间线滚动描边**：中轴 `::before` 轨道 + `::after` 黄铜→朱砂渐变 `scaleY(--tl-p)` 生长（origin top），`timelineProgress()` 以视口 72% 线为生长起止；五个步骤节点左右交替，圆形序号章骑跨中轴。
- **Hero 视差 + 淡出**：内容层 0.16 速率下沉，70% Hero 高度内线性淡出。
- 共享 `createLerpLoop()`（无任务自动停摆）与单个 scroll 被动监听（rAF 节流）；全部交互挂 `prefers-reduced-motion` 总开关，JS 侧不再执行。

### 3. 大留白重排（用户核心诉求）

- tokens.css **只新增**：`--space-9/10/11`（96/128/160px）与 `--text-display-1/2/3`（clamp 流式展示字号）；区块间距升至 160px、Hero 满屏 `calc(100vh - 56px)`、五步由五列 grid 改为纵向时间线、3×2 卡片改为疏朗 2 列大卡（gap 32px）。
- landing.html 结构重排：Hero 增 `<canvas class="ld-hero-gl">` 挂载层与滚动提示；五步改 `<ol class="ld-timeline">` 语义结构（保留全部 5 个 hash 跳转）；补引 motion.css（纪律：keyframes 只在动效层定义）；主题切换逻辑从内联 script 迁入 landing.js；新增内联 SVG favicon。
- vite.config.js `chunkSizeWarningLimit` 700→800（注释说明：three async chunk 仅此一个超限来源）。

### 4. 顺手修复的三个实测 bug

- **深色模式 Hero 变白底**：`--slate-800/900` 在深色主题被重映射为纸白色，v8.2 起 Hero 底色引用它们导致深色下变白。新增专用 token `--ld-hero-bg`（浅色 #171A18 / 深色 #101310），Hero 两主题恒为深墨底——这才是 landing.css 头部纪律③的原意。
- **深色标题渲染成白色色块**：theme.css 深色 h1 渐变文字（`background-clip: text` + 透明填充）与逐字 `.ld-char` spans 冲突（char 的 filter/transform 打断父级文本裁剪路径）。深色下对 Hero 标题禁用渐变文字，accent 段恢复朱砂填充；`.ld-h2` 不拆字符，不受影响。
- **窄屏「拿 Offer」断成「拿Of/fer」**：逐字 span 使英文单词可在任意字母间断行，accent 段加 `white-space: nowrap` 作为整体换行单元。

### 5. 测试与验证

- 新增 `frontend/tests/landing.test.js`（25 例，node 环境）：`charEntries`（offset 累计 / 空串 / 代理对不拆散）、`magneticOffset` 与 `tiltAngles` 边界钳制（含 -0 归一化）、`normPointer` 越界与零尺寸、`timelineProgress` 生长起止、`parallaxShift / heroFade` 退化输入。
- `npm run test` **77 passed**（16 voice + 36 interview + 25 landing）；`npm run build` 零告警（landing 入口本体 9.4KB）；`pytest tests/test_repo_hygiene.py -q` 5 passed。
- playwright 真机截图（桌面浅/深双主题 + 390px 移动端）：WebGL 墨晕渲染、逐字揭示、时间线描边生长、卡片倾斜高光、深色 Hero、移动端断行全部符合预期，**控制台 0 错误 0 警告**（favicon 404 已随内联 SVG 图标消除）。

### 6. 范围纪律

- 只动 landing 入口相关文件 + tokens/motion 的追加式扩展；主应用 index.html 及其 JS 一行未动，后端零改动；CHARTER.md 未触碰；v7.1 纸墨印章色板不变。
- 设计稿：`docs/specs/2026-09-01-landing-motion-design.md`。

---

## v8.6 模拟面试模块：外部评估报告对照 + 四项改进（2026-09-01）

> 起因是用户递来第三方《模拟面试模块 · 专项深度评估》（v8.3 快照，A / 9.0 分，只读评估产物）要求「对照比较给出修改建议」。**复核结论**：报告的技术判断基本属实（10 条断言 9 条属实、1 条表述不准），但它是一张**滞后两轮**的快照——行数与版本号均已过时；更要紧的是它第七节 5 条改进里，**1 条后半段已落地、4 条早已登记为已知局限**，真正的新增信息只有 1 条。本轮先逐条对齐，再把核对后仍然成立的问题按优先级修掉。对照报告产出到项目外 `F:/Desktop/AI面试官评估产出/模拟面试模块_评估报告对照与修改建议.html`（与另两份评估产物同处，**不入库**）。

### 0. 复核：报告的三种"不准确"

| 类别 | 内容 |
|---|---|
| **数字过时** | `session.py` 报告称 1306 行 → 实测 **1499**；`interview.js` 称 1623 行 → 实测 **1796**；版本称 v8.3 → 仓库已到 **v8.5** |
| **建议已落地** | 第七节建议 #1 的后半句「至少把追问内容纳入本题最弱维度证据」在 v8.x 已完成：`report.py:_build_follow_up_map()` + `qa_breakdown.follow_ups` + `detailed_qa.follow_ups` + Markdown 导出。**追问补充此前是"进得了报告、进不了分数"，缺口只剩"不重评"** |
| **早已登记** | 双 Agent 成本（LIMITATIONS L14）、无断点续答（L12）、测试偏纯函数（L18）、前端补测（v8.3.3 已列"本轮明确未做"）——报告把它们当新发现，实际是既有登记的推进 |

**唯一的新增发现**：`thinking_seconds` 完全由前端上报、后端只做 0–600s 归零，且它是报告 `qa_breakdown` 与 `_fallback_impact()` 兜底文案的判据之一——报告只列为"恶意前端可污染"，低估了"前端计时本身会系统性失真"这一层。

另：报告称"非流式诊断走 `asyncio.to_thread`"表述不准——那是 v1 兼容降级路径，WS 主路径走 `_astream`/`chat_stream_async` 真异步。

### 1. 追问补评（P0，用户指定优先）

- 追问补充提交后触发一次**只含 Diagnostician 单段**的增量重评（不产改写、不产追问，约为正常诊断一半 token），**五维分 + 加权总分 + 最弱维度全部更新**——用户的口径是"追问补充必须影响总分"，不做"只更新总分"的缩水版。
- **补评与首评共用 `_score_and_weakest()`**（v8.6 从 `normalize_result` 抽出）：加权公式、规则化加减分项、最弱维度交叉校验三处口径必须同源，否则报告里会出现"同一道题两种算法"。新增 `test_same_scores_as_first_assessment` 钉住这一点。
- **原分必留痕**：`pre_follow_up` 保存首评快照，`reassessment_delta` 记录变动量，报告 `qa_breakdown` / `detailed_qa` / Markdown 导出 / 诊断卡四处同步披露——与 `assisted`、`follow_up_skipped` 同一条诚实纪律。
- **补评可以降分**：prompt 显式约束"补充不等于加分"，`reassessment_stats.downgraded_questions` 收集补充反而暴露问题的题。若补评只能涨分，追问就从诊断工具退化成送分机制，比不补评更有害。
- **只补评一次 / 失败静默回退**：同一题二次追问不再补评（否则分数被反复改写，首评快照失去意义）；拿不到 `reassessment_done` 即视为没发生，保留首评。刻意**不重跑难度调度**——难度档已按首评触发，事后改分不撤销已变过的档。
- 开关：`FOLLOW_UP_REASSESS`（默认 true）。

### 2. 改写改为按需生成（P1）

- `AUTO_REWRITE=false` 时诊断完成即返回，改写由前端拿到评分后发 `request_rewrite` 索取。省的是**感知延迟**（用户不再干等第二次完整往返），不是 token——这点在配置注释与 LIMITATIONS 里都写明了，避免被误读成"省调用"。
- **刻意不用后台并发**：`diagnosis_done` 后 WS 层会立刻推下一题/追问，改写流会串台到新题卡片上。改用按需请求 + `round/question_idx` 身份校验，请求晚到（已翻页）直接拒绝。
- `run_rewrite_streaming()` 独立成流，自动路径与按需路径**共用同一实现**；`rewrite_done` 补带 `round/question_idx`，供前端回填到正确的诊断卡。
- `request_rewrite` 与 `ping` 统一由 `_handle_control_message()` 处理——答题等待循环与追问等待循环都要响应，两处各写一遍迟早漏掉一种（漏掉的表现是"点了没反应"，且只在特定时机复现）。

### 3. 启发式精确化（P3，保持确定性、不引 LLM）

- `needs_recovery` 加**转折豁免**：命中示弱词但转折词在其后、且转折后还有实质内容（≥8 字）则不触发。修复"我没做过这个，但我了解原理"被误判卡壳——误判的代价是双重的：恢复话术打断节奏，且该题被打上 `assisted` 标记进了报告，成一个假信号。
- `is_end_signal` 加**长度约束**（≤30 字）：长回答里顺带提到"结束面试"四字不再掐断整场面试。30 字取的是"能容纳中英口令（"OK, let's End Interview now" 为 28 字）、又远短于任何实质回答"。
- 不改成 LLM 判定：`session.py` 既有注释已论证关键词匹配的理由（低成本、可测试、无幻觉），且这是同步路径，为它多一次 LLM 往返不值当。

### 4. 前端补测（P2）

- `handleWSMessage` 加 `export`（**唯一改动，零逻辑修改**），新增 `frontend/tests/interview.test.js`（36 例）：node 环境下用 Proxy 做最小 DOM 替身 + `vi.mock` 桩化四个依赖，覆盖 29 种消息类型的派发契约、未知类型静默忽略、`error`/`security_block` 转 toast、`mode_change` 同步模式、`radar_update` 驱动雷达；另有一条**源码扫描**用例，断言 switch 的 case 标签覆盖全部契约类型。
- **不抽纯函数重构、不加 DOM 依赖**：为可测性拆 1796 行文件收益低于风险；`vitest.config.js` 的 `environment: 'node'` 是 v7.4 的刻意选择，本轮维持。

### 5. 思考时长：从"完全信任前端"降级为"可交叉校验"（P4）

- 服务端记录"推题 → 收到回答"的墙钟差。**不变量：前端上报值不可能大于它**（后者还多算网络与渲染）。违反时以服务端值为准并标注 `thinking_seconds_anomalous`。
- 为什么值得做：该数字进报告 `qa_breakdown`，还是 `_fallback_impact()` 兜底文案（"耗时偏长，可能被质疑熟练度"）的判据。页面切后台、设备休眠、组件重渲染导致计时起点被重置都会让它失真——这不是"恶意才出问题"。

### 6. 明确不做

- **断点续答**：需序列化整个 `InterviewSession`，CHARTER.md:180 已列"现阶段不做"，报告自己也标注为可选。
- **启发式改 LLM 语义判定**：见上第 3 条理由。
- **前端抽纯函数重构 / 引 happy-dom**：见上第 4 条理由。

### 7. 验证

- 后端全量 `python -m pytest tests/ -q`：**1079 passed / 1 skipped**（基线 1039 + 本轮 40）。
- `python -m pytest tests/test_repo_hygiene.py -q` 5 passed。
- 前端 `npm run lint` 0 errors / 25 warnings；`npm run test` **77 passed**；`npm run build` 通过。
- 协议变更已同步 `docs/API.md`（客户端→服务端 4→5 种、服务端→客户端新增 4 种）；已知局限已同步 `docs/LIMITATIONS.md`（21 → 23 条）。

### 8. 范围纪律

- 未新增任何 npm / Python 依赖；未触碰 CHARTER.md 任何架构约束与决策记录；`.importlinter` 分层契约未改（本轮改动全部落在既有 L2/L3/L4 内）。
- 本轮 4 项均为**既有能力增强**，非新功能模块。

> ⚠️ **待用户确认的并行改动**：本轮进行期间，工作区出现了非本轮产出的 `frontend/src/js/landing.js` + `frontend/tests/landing.test.js` + `three` 依赖 + `vite.config.js`/`package.json` 改动（其文件头自称"v8.6 新增"）。它们与本章同处 v8.6，但主题不同（落地页 WebGL）。本轮未改动这些文件，前端 77 例中包含 landing 的 25 例。若两者要合并为同一版本，需统一 v8.6 叙事。

---

## v8.5 全站视觉质感提升：threeui 手法迁移（2026-09-01）

> 起因是用户递来 `MengTo/threeui`（React + Three.js 的 WebGL shader 视觉组件库）希望参考其视觉语言。**评估结论**：组件形态（React + Three.js）不可引入——会破坏本项目原生 ES Module 架构并与 DC-09 专业评测定位冲突；但其**视觉手法**（大面积低频渐变环境光、玻璃拟态、多层景深阴影、渐变描边、hover 光晕、入场错峰）可以零成本迁移为原生 CSS。本轮**只做质感**——不动色板（v7.1 纸墨印章基线不变）、不改 DOM 结构、不改任何 JS 业务逻辑与后端，**零新增依赖**。

### 1. 独立质感层 `surface.css`
- 新增 `frontend/src/css/surface.css`，层叠位置：components.css 之后、motion.css 之前（详见 index.html 头部注释）。
- 该文件**不定义任何 animation**（一律交给 motion.css）。出现异常时注释 `<link>` 即可完整回退到 v8.3 视觉，爆炸半径最小——这是本轮最关键的纪律。
- `tokens.css` 新增**质感变量族**（环境光/表面/景深/描边/内高光/玻璃参数），`:root` 与 `html.theme-dark` 各一份；**既有色值一个都不改**。

### 2. threeui 手法 → 本项目落地对照
| threeui 手法 | 落地方式 | 备注 |
|---|---|---|
| 大面积低频渐变环境光 | `body::after` 6 层径向渐变（含 3 条壳层色带） | CSS 等价于 shader 背景，零依赖 |
| 玻璃拟态 Glassmorphism | Header / 侧栏 / 底部导航 + 悬浮层 | 同屏 ≤ 4 个；滚动容器与 canvas 容器强制禁滤镜（性能硬规则） |
| 多层景深 | `--depth-1/2/3` + `--depth-hover` | 替代单层平影，明确 z 轴秩序 |
| 顶部内高光 sheen | `inset 0 1px 0` 亮线 + 底部 inset 暗线 | 模拟纸的受光边；深色侧已有的处理对称补到浅色 |
| 渐变描边 Gradient border | `mask-composite` 1px 渐变 | 仅用于「下一步建议」卡，保留 urgency 三态左边框 |
| hover 抬升 + 光晕 | 分级 `translateY` + `::before` 径向渐变渐显 | 沿用既有 `.card-hover` 契约，不重复定义 transform |
| 入场错峰 stagger | `animation-timeline: view()` 渐进增强 | `@supports` 包裹；Firefox 内容直接可见，零风险 |

### 3. 刻意不借鉴的部分
- 3D 翻转、粒子爆炸、霓虹辉光、弹跳缓动、shader 实时背景——与 DC-09「禁游戏化、要专业感」判断依据冲突；技术上引入 three.js（~600KB + 常驻 GPU 占用）换来 CSS 渐变同等观感得不偿失。

### 4. 参数定档
- 玻璃不透明度 **20%** + 模糊 **44px** —— 用户在原型滑块拖到两边界值确认（最极透最重的磨砂）。
- 极透玻璃的**可读性补偿**：`backdrop-filter` 加 `brightness(1.07)` 浅色提亮 / `brightness(0.60)` 深色压暗，保证墨色 / 纸白文字对比度。

### 5. 顺手修复
- `landing.html` 缺 `layout.css`（Header 裸奔）已补；
- `landing.html` 的 `theme.css` 被 `landing.css` 覆盖（深色落地页不生效），把 theme.css 移到最后修正。

### 6. 范围纪律遵守
- CHARTER.md 任何架构约束 / 决策记录未触碰；
- 未新增任何 npm 依赖；
- 仅 `market.css` / `memory.css` 用「减法」统一（它们已有 54 处重视觉，叠加会过腻）。

### 7. 验证
- `npm run test` 16 passed；`python -m pytest tests/test_repo_hygiene.py -q` 5 passed；`npm run build` 4.44s / main CSS 98.84 kB（含 surface.css）；playwright 真机双主题截图，Header 玻璃 / 卡片景深 / 内高光 / 雷达图均符合预期，控制台零错误。

---

## v8.3.3 外部评估报告复核与低成本收尾（2026-09-01）

> 起因是用户递来一份第三方《AI 求职领航（AI 模拟面试官）· 深度评估报告》（v8.3 快照，综合评级 A / 8.6 分，只读评估产物存放于项目目录之外），要求「评估」。本轮只做**复核 + 低成本收尾**：先逐条核验报告结论的真伪与时效性，再把仍然成立、且改动成本最低的项收尾。用户明确划定的范围是「低成本收尾」三项，**不含**部署边界加固、前端补测与演示加固。

### 1. 复核：三条结论已过时，不是待修项
- 报告称「README 3 处写 1026 用例，实测 1039」→ 实测 `1026` **零命中**，README 四处均为 1039（v8.3.2 已统一）。
- 报告称「根目录有垃圾文件 `({` / `b.textContent)`」→ v8.3.2 已删除，当前根目录仅白名单文件。
- 报告称「`.dockerignore` 中文注释 GBK/UTF-8 混编码乱码」→ 实测为正常 UTF-8，未复现。

### 2. 删除孤儿密钥文件 `data/.auth_secret`
- v8.3 按 DC-10 下线认证后遗留的一行 64 位密钥。`git ls-files` 确认**未被跟踪**（`.gitignore:15` 的 `data/` 已覆盖），故直接删文件，无需 `git rm --cached`。
- 全仓 `auth_secret|AUTH_SECRET` 仅命中 `CHARTER.md` / `CHANGELOG.md` / `docs/archive/week8_认证与资源归属_需求.md` 三处历史叙事，**代码零引用**，删除零功能风险。

### 3. 前端死代码清理（ESLint warnings 26 → 24）
- `voice.js`：删 `ttsUtterance`（声明 1 处 + 赋值 4 处，全程只写不读）。**保留**同段的 `ttsSpeaking` / `mimoAudio` / `speechSeq`——后三者是 v6.3「真打断」机制的真实载体，误删会破坏打断语义。
- `report.js`：移除未使用的 `escHtml` 导入。**`utils.js` 的 `escHtml` 本体保留**（`interview.js` / `history.js` 在用）——为消一条警告砍掉活代码是负收益。

### 4. `drawGeoMap` 不是死代码，而是「渲染器已就绪、卡片未接线」
- 报告将其列为死代码（且误记为在 `interview.js`，实际在 `marketData.js`）。核查发现它**不能按死代码删除**：后端 `backend/market/insight.py` 已注册 `Section(key="geo", title="岗位地理分布")`，`tests/test_market_insight.py` 断言 `SECTIONS` 集合含 `"geo"`；前端渲染器、柱状图降级、`cityCoords.js` 坐标表、`china-geo.json` 资产、vite 懒加载配置**全部就位**，只差两步接线——`CHART_CARDS` 缺一项 `kind:'geo'`、`drawAllCharts` 缺一个 `else if (kind === 'geo')` 分发分支。
- 判据：删除需连带处置后端 section 与测试断言（跨模块），接线属新增功能，二者均超出本轮范围。故本轮**保留代码 + 三处注释**：`CHART_CARDS` 上方写清状态与两步接线方式；`marketData.js` 地理专区段首写防误删警示（点名后端 section 与测试断言）；`cityCoords.js` 头部标注唯一消费者及处置绑定关系。
- ESLint 的 `drawGeoMap` 未使用告警**刻意保留**：它是"未接线"这一事实的真实信号，消掉反而丢失信息。

### 5. 文档数字核对（一处真漂移）
- 一致：README / CODEBUDDY / `docs/API.md` 的 **1039 用例**（本次无后端改动，沿用 v8.3.2 实测基线）、**前端 16 例**（vitest 实测 16 passed）、**59 HTTP + 1 WebSocket**（按 `backend/routers/*.py` 逐域重数复核，与 API.md 一致；口径为 11 个 router 注册的路由，不含 `main.py` 直接注册的 `GET /` 落地页，已在 API.md 补注）。
- 修正：README 称已知局限「19 条」，实测 `docs/LIMITATIONS.md` 表格 **21 条**（README 两处均已改）；`LIMITATIONS.md` 结论句中过时的「50 个测试用例通过」→ **1039 个用例通过**。

### 6. 本轮明确未做（后续可选项）
- 部署边界加固：Docker/compose 默认 `0.0.0.0` 暴露 + 无认证，公网部署须反向代理鉴权，或在 README / `.env.example` 加醒目警告（守 DC-10，不重建认证）。
- 前端补测：`interview.js` 的 WS 状态处理与 `profileCard` 渲染仍是测试盲区（前端仅 voice.js 16 例）。
- 演示加固：进程重启会丢进行中面试（已披露），演示脚本未标注"演示前勿 reload"。
- 其余约 22 条 ESLint 未使用变量警告。
- `geo` 卡片接线，或整条孤岛（含后端 section 与测试断言）一并下线——二选一，需单独一轮。

验证：`npm run lint` 0 errors / 24 warnings（原 26）；`npm run test` 16 passed；`npm run build` 256 模块转换成功、4.42s。本轮无后端改动，未跑全量 pytest。

---

## v8.3.2 仓库整理：清垃圾、docs 分层、根目录白名单（2026-09-01）

> 起因是用户的要求："全面整理项目，清理垃圾文件，整理架构"。诊断下来是三类「脏」叠加：根目录堆了运行产物与散落文档、`docs/` 40 篇文档平铺无分层、文档叙述与代码现状脱节。本轮**只做整理，不新增功能、不动架构分层**。

### 1. 根目录清垃圾
- 删畸形文件 `({` 与 `b.textContent)`（某次命令误写产生）、对话上传附件 `upload_*.jpg`×2；清掉 `.pytest_cache/`、`.grimp_cache/`、`.import_linter_cache/`、`.coverage` 与全部 `__pycache__/`。
- **`.gitignore` 补两条实测遗漏**：`git check-ignore -v` 实测只有 `.coverage` 与 `.agnes/` 命中规则——`.grimp_cache/` 与 `.pytest_cache/` 不出现在 `git status` 纯属依赖 pytest 自己在缓存目录内写 `.gitignore`。依赖关系方自觉不如自己声明。

### 2. 根目录文档归档（不再散落）
- `AI模拟面试官_项目立项报告_V1.0.docx` → `docs/立项报告/` 并 `git rm --cached`——靠 `.gitignore` 已有的 `*.docx` 规则做到**本地保留、不入库**，不为二进制破例开白名单；`career-copilot-学习报告.md` → `docs/research/`；未跟踪的 `初验演示脚本.md` / `初验演示讲稿.md` → `docs/` 并纳入版本管理。

### 3. docs/ 四区分层
- 新增 `docs/README.md` 作为索引：**现行基线**（`docs/` 根）/ **设计稿** `specs/` / **调研** `research/` / **归档** `archive/`。
- **归档只搬不删**：week1–week10 需求文档与 6 篇竞品研读移入 `docs/archive/`——它们是 CHARTER「开发纪律」要求的批判性思维证据，删掉等于销毁评分依据；已下线功能的两篇（报告分享与招聘端 **DC-08**、认证与资源归属 **DC-10**）文首加状态警示后归档。
- `docs/superpowers/specs/` → `docs/specs/`，删除 superpowers 空壳目录。

### 4. 死代码清理（逐项 grep 验证后才删）
- 前端：`api.js` 删 `diagnose` / `getWeaknessProfile` / `getWeaknessSuggestions` / `getProviders` / `switchProvider`；`utils.js` 删 `clone`；`voice.js` 删 `getTTSVoice`；`navConfig.js` 删 `stepKeyToTab` 与 `JOURNEY_KEYS`。
- 后端：`score_adjustments.py` 删 `describe_adjustments`。
- **核查后保留（不是遗漏）**：`api.js` 的 `uploadResume` / `uploadJd`（分别被 `careerPlan.js` 与 `interview.js` 的 v8.3.x `handleSetupUpload` 调用）、`landing.html`（v8.2 活入口）、`utils.js` 的 `stampIn` / `shake`（与 `motion.css` 的 `.stamp-in` / `.shake` 成对，单删 JS 会留下孤儿 CSS，收益低于风险）。

### 5. 防复发：根目录白名单断言
- `tests/test_repo_hygiene.py` 新增第 4 条 `test_root_directory_whitelist`。原三条都是**黑名单**（禁 `_` 前缀 / 禁散落 `test_*.py` / 禁运行产物），**拦不住"任意新散落文件"**——本轮那两个畸形文件与两份散落文档一条黑名单都不违反，黑名单只能针对已知模式，白名单才能回答"这个文件凭什么在根目录"。已反证：临时 `probe.txt` 执行 `git add -N` 后该断言如期红灯（探针已撤销）。

### 6. 文档与现状对齐
- CHANGELOG：顶部章节按「新 → 旧」重排（原 v8.2.0 压在 v8.3.0 之上、v8.3.0 又压在 v8.3.1 之上）；文件头版本区间 v8.1 → v8.3；更正 v8.3.1 中"`api.js` 两个导出待下一轮清理"的叙述（实为活代码）。
- README / CODEBUDDY：项目结构树与真实目录对齐（补 landing.html、简历库/岗位库模块、CI 工作流、docs 分层），测试基线 1026 → **1039 passed / 1 skipped**。
- **链接有效性**：新增一次性校验（扫描 108 个 Markdown 的 47 条相对链接），修掉 7 条因 docs 迁移而失效的链接（CHANGELOG 指向 week8 需求文档 ×2、`docs/archive/*` 的 `../CHANGELOG.md` 应为 `../../`×3、演示模式方案评估与 MockFlow 研读互链 ×2）。

### 7. README 标准化 + 新增 API 参考
- **新增 `docs/API.md`**：从 `backend/routers/*.py` 装饰器逐条提取全量端点——**59 个 HTTP 端点 + 1 个 WebSocket**（其中 `assets.py` 的 2 个 `PATCH` 端点首轮按 get/post/put/delete 提取时被漏掉，补全后核对总数）。按域分组给出方法/路径/说明/限流档位，并单列 WS 帧格式、客户端→服务端 4 种消息、服务端→客户端 19 种消息与关闭码语义。此前 40+ 端点**零参考文档**——README 里唯一的 `/api/` 字样还都是历史流水账顺带提到的。
- **README 重排为标准骨架**：目录 → 项目简介 → 核心特性 → 快速开始 → 使用说明 → 项目结构 → 技术栈 → **API 参考** → 诊断体系 → 面试模式 → 内容护栏 → 测试策略 → 已知局限 → 开发文档 → 贡献 → 许可证。原本「使用说明」被压在「内容护栏」之后（真正的用法是全篇最薄的一节），已提到「快速开始」之后。
- **「核心亮点」75 行 → 「核心特性」15 条**：原清单每条都挂 `（v8.0）/（v7.4）/（v6.1）` 版本号，等于把 CHANGELOG 抄进 README；版本叙事的归宿是 CHANGELOG，README 只答"这项目能干什么"。砍下的内容在 CHANGELOG 里一条不少，零信息损失。
- **已知局限外迁 `docs/LIMITATIONS.md`**：19 行大表移出 README 主体（README 保留 6 条要点 + 指针），既缩短首屏，也让局限文档可被单独引用。
- 新增 `docs/API.md` / `docs/LIMITATIONS.md` 已登记进 `docs/README.md` 索引与 `CODEBUDDY.md` 深入文档指针。

> 未做的部分：**无截图**（用户本轮选择先解决文档结构）。这是 GitHub 首屏观感影响最大的单项，留待后续补 `docs/screenshots/`。

### 8. 明确公开范围：过程性资料退出远端（本地保留）

用户确认本仓库定位为**作品集 / 对外展示**，公开面应是代码与工程文档的专业度，故把过程性资料从 git 索引移除（**文件不删**，留在本地供答辩与复盘查阅）：

| 类别 | 内容 | 处理 |
|---|---|---|
| 课程过程稿 | `docs/archive/` 的 week1–week10 需求文档 19 篇 | 退出索引（含 AI 协作全过程记录，属作业材料） |
| 竞品研读 | `docs/archive/` 6 篇深度研读 + `docs/research/` 3 篇 | 退出索引（分析他人项目的学习资料） |
| 验收材料 | 答辩要点 / 测评问题记录 / 演示模式评估 / 初验演示脚本与讲稿 | 退出索引（含对外自曝缺点的测评记录） |
| 立项报告、AI 对话存档 | docx 与会话存档 | 本就由 `.gitignore` 排除，维持不变 |

`.gitignore` 新增「过程性资料：本地保留、不入库」条目并逐条列明，注释写清**判断依据是仓库定位**而非文件重要性——后续若要当作业提交，删掉对应条目即可恢复跟踪，可逆。

- **连带修掉 5 处"本地正常、远端 404"的链接**（README 3 处指向 archive、CHANGELOG 2 处指向 week8 需求文档）：改为纯文本文件名并注明「本地过程资料，未入库」。这类坏链接只在使用 GitHub 渲染时才暴露，本机完全看不出来。
- **新增第 5 条卫生断言 `test_markdown_links_point_to_tracked_files`**：被跟踪的 Markdown 里，相对链接的目标必须也被跟踪，否则 CI 红灯（已反证：临时插入坏链接如期失败，探针已撤销）。
- **`_tracked_files()` 改用 `git -c core.quotepath=false ls-files`**：此前 Windows 下非 ASCII 路径会输出成八进制转义，做字符串比对时误判"文件未跟踪"（写这条断言时才暴露出来）。
- `docs/README.md` 索引重写为「公开文档 / 过程性资料」两类，README 与 CODEBUDDY 的结构树同步。

验证：`pytest tests/test_repo_hygiene.py -q` **5 例通过**；`run.py lint` 分层契约通过；远端 404 检测覆盖 12 个被跟踪 Markdown / 29 条相对链接，全部指向已跟踪文件。

验证：`pytest tests/test_repo_hygiene.py -q` 4 例通过；`run.py lint` 分层契约通过；前端 `npm run build` 通过。

---

## v8.3.1 面试入口收敛：简历/岗位来源只保留「从库选」（2026-08-31）

> 起因是用户的要求："模拟面试入口里只需要留一个从岗位库选择，从简历库选择就行了，且要用圆角括号"。诊断下来的真问题是：原本 Step 1 同时提供「上传文件」「粘贴文本」「从库选」三种来源，对一个已被前置（简历库/岗位库 Tab）承载好的产品来说，是在重复同一件事——引导用户走"先入简历库、再来面试"的主路径能减少"上传了又丢"、"粘贴到一半换页"等半成品状态。

- **Step 1 DOM 收敛**：`interview.js` 移除「上传简历文件 / 解析文件」「上传 JD / 解析 JD」「粘贴 / 上传」「粘贴 JD」整组入口，只剩「简历来源（从简历库选择）」「岗位来源（从岗位库选择）」两个库选择下拉，括号按要求统一为圆角 `（）`。
- **死代码清理**：`handleUpload` / `handleJdUpload` 函数、`sourceSwitch` 函数、`onSourceChange` 函数全部移除（它们的前置 DOM 已不存在，保留只会增加阅读负担）；`onSourceChange` 改写为 `loadLibraryPicker`，挂载到 `setup` 视图末尾自动展开两个库选择下拉（去掉 `value !== 'library'` 的隐藏分支，因为来源只剩一种）。
- **导入收敛**：`interview.js` 不再 import `uploadResume` / `uploadJd`；`api.js` 仍保留这两个函数（导出端保留可避免其他可能的本地调用失败，移除属于下一轮清理范围）。
  - **v8.3.2 更正**：随后以 `handleSetupUpload()` 把「上传本机文件」作为「从库选」的**并列入口**加回 setup（简历走 `/api/resumes/upload` 入库、JD 走 `/api/upload-jd` 仅解析回填），故 `uploadJd` 重新被 `interview.js` 调用、`uploadResume` 由 `careerPlan.js` 调用——两个导出端**都是活代码**，不属于「下一轮清理范围」。本条按 CHARTER 纪律保留原文（历史叙述不改写），仅标注更正。
- **校验与提示语同步更新**：「下一步」按钮文案从「可直接粘贴或上传解析」改为「先从简历库选择一份简历，或直接在文本框中填写」；textarea 的 placeholder 改为「从上方库下拉中选择后将自动填入此处，仍可手动编辑」。

验证：前端 `npm run build` 通过（dist 已更新），前端 vitest 16 例通过；后端无接口层变化，无需重跑后端测试。

---

## v8.3.0 砍掉登录认证，回归单用户本地工具（2026-08-31）

> 起因是用户的直接指令："砍掉登录认证这个功能"。诊断下来的根因是 v7.0 引入的认证层在本场景是**过度工程**——本系统是单用户本地工具，数据全存本机 `interview.db`，既无第二用户也无外部访问。DC-06 自己承认"默认部署下认证从不生效"，归属（owner_id）更是伪维度：单用户下"按 owner 过滤"恒等于"不过滤"。决策记录见 CHARTER **DC-10**。

### 后端（认证层整体下线）
- **删除认证模块**：`backend/auth.py`（bcrypt 哈希 / JWT 签发 / 密码策略 / 用户上下文）与 `backend/routers/auth.py`（注册 / 登录 / me 三接口）整个移除；`main.py` 不再注册 `auth.router`；`.importlinter` 的 L2 名单与 `requirements.txt` 的 `bcrypt`/`PyJWT` 一并移除。
- **`config` 去认证开关**：`AUTH_ENABLED` / `AUTH_SECRET` / `AUTH_ROLES` / `validate_role` / `UserRole` 全部移除——这些是为"多用户/多角色"预设的旋钮，单用户下全是死代码。
- **数据层去归属**：`db.users` 表删除；`resumes` / `positions` / `sessions` 的 `owner_id` 列经 `init_db` 幂等迁移 `DROP COLUMN` 删除；`journey_marks` 的 `(owner_id, step_key)` 主键重建为 `step_key` 主键（多 owner 的打点按最晚时间归并）。`save_resume` / `save_position` / `list_resumes` / `list_positions` / `list_sessions` / `list_recent_reports` / `mark_journey_step` / `list_journey_marks` 全部去掉 `owner_id` 形参。
- **路由去鉴权**：`sessions` / `reports` / `market` / `profile` / `analytics` 各路由移除"登录态必填 / 资源归属断言"；WebSocket 握手只校验会话是否存在（不存在 `close(4000)`），不再校验 token、不再发 `4001`。
- **`profile_service` 去 owner 维度**：`get_profile` / `build_weakness_context` / `build_skill_gap_context` 去掉 `owner_id` 形参；60s TTL 缓存从"按用户分键的 dict"简化为单槽位（原本按 user 分键在单用户下纯属累赘）。
- **修掉的连带 bug**：`market._annotate_in_library` 原本按 `owner_id` 分支查 `positions`——认证下线后该列消失，此路径会直接 `no such column` 500；现已合并为单条 `market_job_id` 查询。

### 前端（账户面板与 token 机制删除）
- 删 `src/js/auth.js`（token 存取 + 账户面板）与 `src/css/pages/auth.css`；`navConfig.js` 移除 `ACCOUNT_ITEM` 与侧栏/底部导航的"账户"入口；`index.html` 移除 `user-btn` 顶栏按钮与 `account-panel`。
- `api.js` 移除 token 注入头与 401 全局事件的广播、WS 握手不再带 `token` query、移除 `4001` 处理分支；`app.js` 移除 `auth:changed` / `auth:unauthorized` 监听与启动拉取登录态；`report.js` 导出不再带 token query。
- 文案：`landing.js` 的"不登录也可以直接使用 / 登录后归集到账户"改为"本机运行，数据不出你的电脑 / 打开即用，无需注册"。

### 测试
- 删 `tests/test_auth.py`（107 例）；改 `tests/test_api.py`（删 `TestAuthIntegration` 与 AUTH 开关 fixture）、`tests/test_entities.py`（归属隔离用例改为"列表返回全部"语义）、`tests/test_profile_service.py`（去 owner 形参、删"按用户隔离缓存"用例、journey 打点用例改为幂等语义）、`tests/test_interview_ws.py`（删 4001 用例、新增"握手无需 token"用例）。
- **新增迁移回归**：`tests/test_db.py::TestAuthRemovalMigration` 钉住 v8.3 的三个不可逆迁移——`users` 表被删、`owner_id` 列被删、`journey_marks` 重建为 step_key 且多 owner 打点按最晚时间归并。

验证：后端全量 **1039 passed / 1 skipped**（基线 1026 + 本轮重构后回归），`run.py lint` 分层契约通过，前端 `npm run build` 通过，前端 vitest 16 例通过。

---

## v8.2.0 市场数据分析 + AI 解读 + 产品落地页（2026-08-31）

> 补齐「数据分析」视图的数据底座与可解释性，并新增产品落地页（landing）。

- **后端（L2）**：新增 `backend/market/analytics.py`——为「数据分析」视图一次性取回、可直接渲染的图表数据聚合（城市/学历/薪资等维度分布），与 `store.get_stats()` 刻意分离（给 LLM 的摘要 vs 给人看的图表关注点不同）；新增 `backend/market/insight.py`——市场图表 AI 解读，section 注册表驱动、5 分钟 TTL 缓存 + 显式失效、按需调用、失败可降级（无 Key / 异常一律返回 `{"error": ...}`，不阻塞图表渲染）；`routers/market.py` 接入 analytics / insight 两能力。
- **前端**：新增落地页 `frontend/landing.html` + `src/css/pages/landing.css` + `src/js/cityCoords.js`（城市坐标，支撑市场数据地理可视化）。
- **测试**：新增 `tests/test_market_analytics.py` / `test_market_insight.py` / `test_market_to_position.py`。

---

## v8.1.0 术语统一：从游戏化隐喻转向专业评测语系（2026-08-31）

> 起因是用户的一句判断："定方向、备弹药、作战室这些太抽象了，整个系统要显得高级一点"。诊断下来的根因不是抽象，而是**语域错配**——游戏化与军事隐喻（作战室 / 弹药 / 加练）与"专业评测工具"的定位冲突，削弱了诊断数据的可信度。决策记录见 CHARTER **DC-09**。

- **全站术语统一（A 方案）**：首屏「作战室」→ **能力档案**；五步主线「定方向 / 备弹药 / 演练 / 诊弱点 / 定规划」→ **职业定位 / 简历准备 / 面试演练 / 能力诊断 / 发展路径**；「下一步最佳动作」→ **下一步建议**；「能力雷达」→ **能力画像**；「我还差什么」→ **待提升项**；对外文案禁用"加练 / 开一场 / 打怪"一类游戏化表达。
- **只改显示名，不动结构**：tab key、哈希路由、数据结构零变更——跨模块跳转（`history.js` / `marketData.js` 的 `.nav-item[data-tab=...].click()`）与既有测试全部不受影响。
- **同步范围**：前端界面文案、后端用户可见文案（六条建议文案、规划器降级模板）与注释、测试断言，以及 CHARTER / README / CODEBUDDY / 设计文档四份主文档。CHANGELOG 与 DC-07 的历史条目保留原文——那是当时的决策记录，不因改名而改写。

### 能力成长曲线（P1：让"进步"可见）
- `db.list_recent_reports(owner_id, limit)` 用**一次 JOIN**（`reports JOIN sessions`）取回最近 N 份报告的时间与评分，替代逐份 `get_report` 的 N+1 取数；`reports` 表无 owner 列，归属只能靠 JOIN 判定。
- 档案 `level.history` 产出按时间正序的评分序列；前端在能力画像卡下方绘制折线，并给出"首末提升/回落 ±X.XX"的可读结论。
- **少于两个点不画线**：一场数据画不出趋势，此时呈现空态引导（"完成第二场模拟面试后显示轨迹"）而非一条误导性的直线。

### 五步主线完成度（P1：让"走到哪一步"有状态）
- 判定口径：**能推导就不落库**——职业定位=已选目标岗位、简历准备=已传简历、面试演练=开过场、能力诊断=出过报告，均由档案实时推导；只有**发展路径**（是否生成过规划）无法推导，靠新增的 `journey_marks` 打点表记录，规划生成成功时由 `/api/career-plan` 打点。
- 未登录（`owner_id` 为空）**不落库**，仅实时推导——不用 `__anon__` 之类哨兵键把匿名用户的数据混在一起。
- 前端侧栏时间线与顶部进度条呈现三态：已完成（青绿实心 + 对勾）/ 进行中（印章红描边）/ 未开始（灰描边）；已完成区间的连接线转青绿实线。选中态（你在看哪一步）改为印章红外环，与完成度（你走到哪一步）在视觉上可叠加、互不覆盖。

### 简历 → 市场与规划匹配（P2）
- `compute_skill_gap()` 用**集合运算**而非 LLM 做简历技能与市场热门技能的比对（确定性事实判断，不该由模型猜）；匹配口径为"忽略大小写精确匹配 + 词长≥2 的子串兜底"——市场侧技能名口径很脏（"Python" vs "Python3"），但也必须防止 "C" 命中 "C++" 导致缺口被系统性低估。
- `CareerPlanRequest` 新增可选字段 `resume_id`（支持以简历库档案为规划起点）与 `skill_gap_context`（技能缺口注入规划 Prompt 与降级模板）。
- 档案卡摘要条展示「技能缺口」——直接回答"往哪补"。

---

## v8.0.0 求职档案：引入领域核心，接通诊断 → 规划闭环（2026-08-31）

> 起因是用户对架构层次的判断："这个整体架构还是太 low 了，往一个产品的角度想想架构"。盘出来的真问题是：三个模块是**并列的工具箱**而非一条主线——没有承载用户状态的核心实体，且最有价值的数据链路（面试诊断 → 职业规划）是断的。

- **新增求职档案（Profile）领域核心**（`backend/profile_service.py`，L3，已登记 `.importlinter`）：聚合四组状态——当前简历 / 目标岗位（含市场基准）/ 能力水平（五维 + 环比）/ 待提升项。
  - **档案是"投影"而非新真相源**：不新增宽表冗余存储，每次请求从 resumes / positions / reports / weakness_memory / market.db 聚合，避免双写一致性问题；代价用 60 秒 TTL 缓存抵消。
- **下一步建议（规则决策表）**：六条规则的判定顺序即产品优先级（先有简历 → 再定目标 → 再测能力 → 补短板 / 排路径），纯函数、零延迟、可解释，不调 LLM。
- **接通「面试诊断 → 职业规划」断层**：`CareerPlanRequest` 新增可选字段 `weakness_context`，由 `/api/career-plan` 注入、规划器的 Prompt 与**降级模板**同时消费——规划第一次知道用户练过什么、弱在哪里，LLM 失败时同样以真实短板为起点。
- **前端「能力档案」首屏**：建议卡 + 五维雷达（当前 vs 上一场）+ 待提升项 + 三大能力入口；`navConfig.js` 成为导航单一数据源（侧栏与底部导航同源于一份配置），`app.js` 的 if/else 链改为 tab 注册表并新增哈希路由（`#/home` 等，刷新与后退直达）。
- **缓存失效联动**：面试出报告后前端调 `POST /api/profile/refresh`，避免"演完成档要等 60 秒才更新"。
- **已知局限（P0 阶段登记）**：`weakness_memory` 以 dimension 为主键、**全局无 owner 维度**（v6.3 早于 v7.0 认证），故「待提升项」本阶段沿用其全局性，后续按 `_ensure_owner_columns` 的 PRAGMA+ALTER 范式补 `owner_id`。
- 验证：后端全量 **1009 passed / 1 skipped**（996 原有 + 13 新增档案用例），`run.py lint` 分层契约通过，前端 build 与 vitest 16 例通过。

---

