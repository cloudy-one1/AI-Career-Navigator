# 变更日志（CHANGELOG）

> 记录 v2 → v8.8 的版本迭代叙事（新增/推翻/修复/范围）。不变的架构约束与决策记录见 [CHARTER.md](CHARTER.md)，日常协作入口见 CODEBUDDY.md（AI 协作索引，本地文档，未入库）。
>
> **品牌现名：AI 求职领航（曾用名 AI 求职陪跑平台，v8.3 更名）。旧版本章节中的"AI 求职陪跑"为历史名称，保留不删。**

---

## v8.8 标准开源工程要素核对：dependabot 接入 + LICENSE 署名 + CI 干净环境复核（2026-09-03）

> 起因是用户递来一份标准开源仓库核对清单：**LICENSE / README（含快速开始）/ CI（干净环境能跑通）/ CHANGELOG / dependabot**。**核对结论**：五项里四项早已在库——CHANGELOG 自 v2 记到 v8.7、CI 已跑后端全量 pytest + 前端 vitest/build、README 快速开始与 `.env.example` 逐条对齐；真正的缺口只有两个：**dependabot 完全缺失**（`.github/` 下只有 workflows/）、**LICENSE 版权持有人署名空缺**（仅 `Copyright (c) 2026`）。本轮按"缺什么补什么"处理，不重做已有文件。

### 1. dependabot 接入（新增 `.github/dependabot.yml`）

- 两个 package-ecosystem：`pip`（`directory: "/"`，对应根 `requirements.txt`）与 `npm`（`directory: "/frontend"`，对应 `package-lock.json`），`version: 2`。
- 节奏 `weekly`（`day: monday`）、`open-pull-requests-limit: 5`，避免依赖变更一次涌入；**commit message 不自定义前缀**，沿用 dependabot 默认，以免与 CHARTER 的 Commit Message 规范冲突。
- 文件头注释钉住两条合并门槛：`requirements.txt` 只声明版本下限（`>=`），合入前仍需本地安装 + CI 绿灯；前端更新会同时改 `package.json` 与 lockfile，而 CI 走 `npm ci`，两者不同步直接红灯（ci.yml 已有同款口径注释）。

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

## v7.5.0 范围收缩：删除招聘者端与报告分享，回归求职者单端（2026-08-31）

> 起因是用户对 v7.0/v7.0.1 引入的"双端"结构的复盘判断："这个项目的定位应该是面向求职者，强加双端是在画蛇添足"。本轮**只做删除、不动求职者功能**：招聘者角色 / 收件箱 / 身份分流 / 报告分享链路全部移除，产品从"六步旅程 + 双端"回归"五步旅程 + 求职者单端"；**认证与资源归属保留**（求职者登录跨设备归集是单端自身能力，与"第二端"解耦）。需求理解与取舍理由见 `docs/week10_范围收缩_回归求职者单端_需求.md`，决策记录见 CHARTER **DC-08**。

### 1. 删除招聘者端（v7.0.1）

- **后端**：删 `routers/share.py` 中 `/api/recruiter/inbox`、`/api/recruiter/reports/{token_hash}` 两个收件箱接口；`share_access.py` 的 `recruiter_inbox` / `open_inbox_report` 逻辑；`db.py` 的 `list_inbox_shares` / `get_inbox_share` 与 `shared_with` 列迁移。
- **前端**：删 `recruiterInbox.js`（收件箱页面）、侧边栏"连接"分组与"收到的报告"入口（桌面 + 移动端）、`recruiter-inbox-panel`、登录态角色显示。
- **角色层**：`AUTH_ROLES` 收窄为 `("jobseeker",)`；注册不再有身份选择（`rolePicker` 删除）；`validate_role` 对 recruiter 一律回退 jobseeker；`UserRole` 枚举删 `RECRUITER`。`users.role` 列**保留**（存量数据无碍，逻辑上恒为 jobseeker）。

### 2. 删除报告分享（v7.0）

- **后端**：删 `routers/share.py`（`POST /api/sessions/{id}/share`、`GET /api/sessions/{id}/shares`、`DELETE /api/shares/{token}`、`GET /api/shared/{token}`、`GET /share/{token}` 分享页 HTML）与 `share_access.py`（token 签发 / SHA-256 摘要 / `redact_pii` 脱敏 / `resolve_shared_report`）；`schemas.py` 删 `ShareCreateRequest`；`db.py` 删 share_links 全部 8 个函数，`init_db` 对老库幂等 `DROP TABLE IF EXISTS share_links`。
- **前端**：删 `share.html` / `share-main.js` / `shareReport.js` 三个分享页文件与 Vite 多入口；报告页"🔗 分享给招聘者"卡片整块移除（`renderShareSection` / `renderShareList` / `renderLastUrl`）；auth.css 删 193 行 share 样式。
- **测试**：删 `tests/test_share.py`（36 例）；`test_auth.py` 的角色回退断言改为 recruiter → jobseeker。

### 3. 同步影响

- 侧边栏旅程分组：备战 / 演练 / 洞察 / 连接 / 账户 → **备战 / 演练 / 洞察 / 账户**（`data-audience` 身份显隐机制一并移除，导航不再有按身份切换逻辑）。
- 产品叙事：六步旅程（含"连机会"）→ **五步旅程**；README / CHARTER / CODEBUDDY / 产品定位文档同步收敛。
- 验证：`pytest tests/ -q` **996 passed, 1 skipped**；`run.py lint` 分层契约通过；`npm run build` 单入口构建通过；全库 grep 无 recruiter/share 代码残留（允许历史文档与 CHANGELOG 旧条目）。

### 4. 范围说明（刻意保留）

- **认证与资源归属不删**：`AUTH_ENABLED` 开关、登录/注册、会话/简历/岗位 owner 隔离、WS 握手校验全部保留——它们服务求职者自己（跨设备归集），不是"第二端"。
- **报告 Markdown/HTML 导出自用**保留；`output_sanitizer` 脱敏能力保留（未来如重建分享，可复用）。
- 历史文档（week8 需求、v7.0/v7.0.1 CHANGELOG 条目）保留作为决策记录，不代表现行范围。

---

## v7.4.0 语音链路强化：长录音 413、熔断过脆、免手闭环（2026-08-31）

> 起因是对 v4.2 落地的语音链路做了一次完整审计（TTS / ASR / 语音→诊断三条链路 + 三份测试），结论是「后端工程约束扎实、前端交互闭环未合拢」。本轮按严重度分级定向修复，**不引入新厂商、不做端到端 Realtime、不动诊断内核**。需求理解与取舍理由见 `docs/week9_语音链路强化_需求.md`。

### 1. P0 修复：长录音必然 413，回答直接丢失

- **问题本质**：`RequestSizeLimitMiddleware._UPLOAD_PATHS` 是个白名单，`/api/voice/asr` 从未登记，因此录音上传走的是普通请求的 `MAX_REQUEST_BYTES=1MB` 额度；而前端 `VAD_DEFAULTS.maxDurationMs=120000` 允许录 120 秒（约 1~2MB 音频）——**两者直接冲突**。短录音一切正常，只有长回答才炸，而长回答恰是语音面试的主场景。413 返回后前端只 toast 一句「识别失败」，用户录了两分钟的回答直接消失。
- **修复**：`_UPLOAD_PATHS` 增加 `/api/voice/asr`（10MB 额度）；`routers/voice.py` 按实际读到的 body 长度做二次校验并 413。两道防线互为补充而非冗余——中间件按 `Content-Length` 预检，分块传输没有该头时会跳过，此时路由层是唯一防线（音频随后要 base64 膨胀 1.33 倍转发 MiMo，超限应尽早拒绝而非白等超时）。

### 2. P1 修复：云端路径开麦前不停朗读（v4.2 换引擎时的回归）

- **问题本质**：v4.2 把主引擎从浏览器 STT 换成 MiMo ASR 时，新写的 `startRecording()` 漏抄了旧路径 `startListening()` 里的那句 `stopSpeaking()`。后果：面试官还在念题时用户点麦克风，外放的题目语音被自己的麦克风采集，连同真回答一起送进 ASR；更糟的是 `lastInputSource` 已标记为 `voice`，**ASR 容错评分会把这段串扰盖掉**。功能更强的新引擎，防御反而比它要替代的降级引擎少一行。
- **修复**：`startRecording()` 补 `stopSpeaking()`，两条路径对齐。

### 3. P1 修复：MiMo 熔断改为「连续失败计数 + TTL 恢复」

- **问题本质**：`mimoStatus` 一旦置 `failed` 就**整个页面生命周期不再重试**，而触发条件极宽松（探测失败、任一题合成超时、`audio.play()` 被自动播放策略拒绝、413）。一次抖动的代价是几十毫秒，整场面试退回机械音的代价是全部音质——用不可逆手段响应可逆故障，比例失衡。
- **修复**：连续失败累计到 3 次才熔断，熔断后 60s 允许重新探测一次（TTL 内不重试，避免每题浪费一次注定失败的请求）；新增 `resetMimoStatus()`，在 `connectWS()` 开新一场面试时调用，不再继承上一场的降级。

### 4. P2：VAD 预滚校准（固定阈值 0.02 的两头失效）

- **问题本质**：固定 0.02（RMS）两头不讨好——嘈杂环境底噪长期超阈，「说完」永远检测不到，只能等 120s 硬上限兜底（正好撞上 P0 的 413）；低增益麦克风又把整段语音判成静音，同样拖到硬上限。
- **方案**：开录后先用 700ms 取窗口内**最小** RMS 当底噪，阈值 = 底噪 × 2.0 + 0.012，夹在 [0.008, 0.12]，之后全程固定。
- **刻意不做连续自适应**：先写的慢升快降版本在测试中被推翻——持续说话会被缓慢「学」成底噪，导致同一场面试里判定标准漂移；且在嘈杂环境收敛到位需要几十秒，等收敛完 `maxDurationMs` 早就到了。取舍已写入需求文档。

### 5. P2：录音电平可视化

云端 ASR 是请求-响应协议，整段录完才有字，**中间反馈反而不如浏览器降级路径（有 interim 结果实时上屏）**。复用 VAD 已在计算的 RMS，新增 `stt:level` 事件，前端渲染 3px 绝对定位电平条（不挤占布局），停止后归零。

### 6. P2：音色选择

后端 `voice_service` 支持 9 个预置音色 + OpenAI 风格别名表，但前端每个调用点都硬编码 `'default'`，配置层能力在 UI 层完全不可达。新增模块级 `setTTSVoice()` 与引导页「语音设置」下拉（8 个音色 + 跟随服务端默认），配置摘要同步。

### 7. P3：免手模式（默认关）

闭环此前断在两处：念完题要手动点麦克风、说完还要手动点提交。新增引导页开关（默认关）→ 念完题自动开麦 → VAD 判定「说完」自动停录 → 倒计时 3 秒自动提交。

安全约束（自动提交是「替用户做决定」，误提交代价远大于多点一次按钮）：

- 只对 VAD 判定的自动停止生效（`reason === 'auto'`），手动点停止语义上是「我还要再说一段」；
- 转写文本少于 10 字不提交；
- 倒计时期间打字 / 点麦克风 / 点取消 / 换题 / 手动提交均可撤销，倒计时控件全量复位。

### 8. 顺带修复：MiMo 播放路径缺一次性守卫

写测试时发现 `mimoSpeak` 的 `onended` / `onerror` / `play().catch` 三条收口路径**没有一次性守卫**（`browserSpeak` 有 `ended` 标志）。个别浏览器会在播放结束时既走 ended 又抛 error，`onEnd` 被调用两次，调用方（`autoReadQuestion` 切回输入、免手模式自动开麦）会连锁执行两遍。已对齐补上。

### 9. 测试补位

- **此前 `voice.js`（23KB）零自动化覆盖**，而它装着世代号竞态与 VAD 状态机这两块最脆弱、且 v6.3/v6.4 反复修过的逻辑。
- 新增 `frontend/vitest.config.js` + `frontend/tests/voice.test.js`（**16 例**）：世代号守卫 4 例（请求在飞时打断不播放、播放中打断摘回调、自然结束只触发一次、canceled 不当作结束）、熔断韧性 4 例（单次失败不熔断 / 达阈值才熔断 / TTL 内不重试且过期可重试 / reset 复位）、VAD 6 例（静音停录 / minSpeechMs 未达不停 / 硬上限 / 嘈杂环境可检测说完 / 固定阈值在同场景检测不到 / `vad:false` 不启动采样器 + 电平事件）、开麦互斥 1 例，另加 1 例电平事件。
- 运行环境选 `node` 而非 `happy-dom`：`MediaRecorder` / `AudioContext` / `speechSynthesis` 在 DOM 模拟库里同样没有实现，全都得打桩，多引一个依赖没有收益。
- 后端新增 2 例（`tests/test_voice_api.py`）：>1MB 录音必须放行、超限必须 413 且**不得转发上游**（`transcribe` 未被调用）。

### 10. 已知局限（本轮未做，不掩饰）

- VAD 只判断「何时停」，**不做端点检测、不裁剪音频**：开头等待与结尾 2.5s 静音仍在上送音频里，付费时长与尾部幻听风险未消除；
- 预滚校准在「开麦瞬间就在说话」时会高估底噪；
- 免手模式依赖云端 ASR，浏览器原生 STT 无自动停录语义，该模式下不启用；
- 音频不落库（报告只有转写文本，无原始音频与 ASR 置信度）；转写失败即丢弃 blob，无重试；
- `/api/voice/*` 未挂鉴权依赖，`AUTH_ENABLED` 开启后仍公开，唯一防线是 `RATE_LIMIT_VOICE=20/min`（按 IP）；
- 原计划把 `atob` 逐字节循环换成 `fetch(dataURL)`，评估后**放弃**——收益仅几毫秒，却要在全模块最 delicate 的竞态函数里新增一个 await 点，风险收益不成比例。

---

## v7.3.2 全功能端到端冒烟：修复题库「看得见、改不了」（2026-08-31）

> 起因是对项目做了一次**全功能端到端冒烟**：真实服务（localhost:8000）+ 真实 LLM（DeepSeek/Qwen 实调）+ 真实 Playwright 采集 + MiMo 云端语音 TTS→ASR 闭环，共验证 89 个检查点（基础/市场/资产/面试主循环/报告/规划/分享招聘端/题库/语音/运维），覆盖六步旅程全部功能域。冒烟发现 1 个真实缺陷，本轮修复。（注：本条目与 v7.4.0 同晚并行完成，发布时版本号让位于语音链路强化，APP_VERSION 随 v7.4.0 发布。）

### 1. 修复：题库「列表里看得见、编辑/删除却报不存在」

- **问题本质**：`question_bank._exists()` 的存在性校验写的是 `list_questions(limit=1, offset=question_id - 1)`——把**自增主键 id 当成了分页行偏移量**。id 只有在从未删除过题目时才恰好与偏移量一一对应；只要题库删过任意一题（id 出现空洞），偏移量就与主键失去对应，`_exists` 对真实存在的题返回 False，PUT/DELETE 一律报"题目 N 不存在"。首测复现：创建 3 题（id=10/11/12），删掉 id=10 后，id=11 的编辑/删除全部失败，而列表里它明明可见。
- **修复**：`db.py` 新增 `get_question(question_id)` 按主键查单题（对齐 `get_session` / `get_resume` / `get_position` 的既有风格，tags/is_favorited 同步反序列化）；`_exists` 改为一行 `await db.get_question(question_id) is not None`。
- **为什么以前没暴露**：大多数题库很少物理删除题目，id 长期连续，偏移量恰好"碰对"。这类"巧合正确"的代码正是端到端真实数据才能逼出来的。
- **回归测试**：`test_db.py` 新增按主键查询 + id 空洞场景 2 例；`test_api.py` 新增"删首题制造空洞后，剩余题仍可编辑/删除"API 回归 1 例。

### 2. 端到端验证结论（工程记录）

- **面试主循环（真实 WS + 真实 LLM）**：37s 走完，主问题 3、追问 2，收到 17 种协议帧（含流式 diagnosis_chunk / rewrite_chunk、追问、补题、结束口令、interview_done），报告五维齐全、逐题拆解 2 条。
- **流程状态落库（v7.3.1 修复）实战验证**：面试完成后 `GET /api/sessions/{id}` 返回 `flow_state=finished, answered_count=2`——v7.3.1 修复的 `_mark_flow` 漏 `await` 在真实运行路径确认生效。
- **MiMo 语音闭环**：云端 TTS（`used=True`，353KB WAV）→ 回灌 ASR → 逐字还原原文（与原文共同字符 28）。
- **分享与脱敏**：创建分享（201）→ 免登录只读 → 分享页 HTML → 撤销，全程通；手机号/邮箱无明文泄漏。
- **市场**：统计/检索/详情/收藏幂等/城市映射/岗位画像研究（LLM）全通；Playwright 实时采集任务终态 done 但 51job 返回 0 条（反爬波动，导入管道兜底，见已知局限）。
- **其他全通**：Gap 分析（10.4s）/ 跨岗位对比（8.4s）/ 职业规划（16.8s，3 阶段时间轴）/ 简历库与岗位库 CRUD / 反馈 / 公司风格（3 家）/ 后端热切换（qwen↔deepseek）/ 历史会话。
- 全量套件 **1033 passed / 1 skipped**。

---

## v7.3.1 品牌尾巴收尾 + 面试主循环测试补位（2026-08-31）

> 起因是收尾清单里的三类遗留：版本号在横幅 / 健康检查 / FastAPI title 三处漂移；v7.2.2 路由拆分后 `interview_ws.py`（面试主循环）成为唯一没有测试直接钉住的核心路径；构建期两条 import 噪音。本轮范围：**功能零增删**，只做品牌/版本统一、测试补位，以及过程中暴露的一处真实缺陷修复。

### 1. 品牌与版本号统一（P0）

- 新增 L1 单点版本源 `config.APP_VERSION`，`main.py`（FastAPI title/version + 启动日志）、`routers/system.py` 的 `/api/health`、`run.py` 启动横幅三处统一引用。此前横幅写死「AI面试官 v3.1」、health 硬编码返回 `"3.1"`，与实际版本脱节——这正是"品牌统一"声称完成后仍留下的一条尾巴。
- `main.py` 启动生命周期由已弃用的 `@app.on_event("startup")` 迁移到 `lifespan`。
- `run.py` 横幅与 `frontend/src/css/components.css` 残留的 v2 时代旧名注释统一为「AI 求职陪跑」。
- README「参考答案背诵面板未渲染」局限描述改写：如实说明 `detailed_qa` 当前只进 Markdown 复盘导出，报告 Tab 渲染的是 `qa_breakdown`（含「✍️ 含改写示范」徽标但不展示答案正文），避免把两者混为一谈。

### 2. 修复：流程状态「显式化」从未真正落库（补测试时暴露的真实缺陷）

- **问题本质**：`interview_ws._mark_flow()` 是 `async`，但 5 处调用（WAITING_ANSWER / GENERATING_FOLLOW_UP / DECIDING_NEXT / ADVANCING_ROUND / FINISHED）**全部漏写 `await`**——只创建协程对象后丢弃。后果是 v7.0 引以为傲的「流程状态显式化」从未写入过一行库数据，`set_flow_state()` / `update_session_flow()` 一次都没执行；运行时仅表现为 `RuntimeWarning: coroutine was never awaited`，不中断、不报错，完全静默。
- **修复**：5 处补 `await`。这是本轮唯一的行为变更，也是"补测试"直接换来的收益——桩对象缺属性才把它逼出来。
- **教训（测试基建）**：`TestClient` 的 `receive_json()` 会无限阻塞，桩一旦发生契约漂移，测试表现为"跑很久"而非失败，极难定位。已给读帧加 10s 超时（`_recv_with_timeout`），把永久挂起转成带排查线索的快速失败；同一文件耗时从"挂起"降到 4.9s。

### 3. 测试补位（P1）

- 新增 `tests/test_interview_ws.py`（6 例）：真实 FastAPI WS 管线 + 最小 `FakeSession` 桩（只实现 WS 层实际触碰的接口，本身就是 WS 层对会话层的隐性契约清单）。钉住 ping/pong、switch_mode（合法切换 / 非法模式报错但不断连）、结束口令（跳过诊断、照常生成完整报告）、断连（落部分报告 + `finally` 清理 `active_sessions`），外加握手契约（4001 未授权 / 4000 会话不存在）。`interview_ws.py` 覆盖率 **8% → 61%**。
- 新增 `tests/test_market_store.py`（5 例）：upsert 幂等（重复采集不增行）、收藏不覆盖（钉住 v7.1「重新采集不清空感兴趣」的落库承诺）、收藏只翻标记且不改写数据时间戳、空库友好空态、过滤与分页。TTL 清理不在此处——那是采集任务表的职责，已由 `test_market_crawler_tasks.py` 覆盖。
- 全量套件 **1028 passed / 1 skipped**（原 1017）。

### 4. 工程噪音清理（P2）

- 消除 Vite 构建的两条 dynamic/static import 警告：`api.js` 对 `auth.js`（`auth.js` 只依赖 `utils.js`，不存在原注释所担心的循环依赖）、`interview.js` 对 `api.js`（顶部已静态引用，却又在 4 处 `await import()`）的动态导入全部收敛为静态导入——两者都已无法拆出独立 chunk，动态化零收益。构建恢复干净输出。
- `CHARTER.md` 决策记录卡按 DC-01 ~ DC-07 重排（此前 DC-06 误排在 DC-05 之前）。

---

## v7.3.0 产品定位延伸：全流程求职陪跑平台（2026-08-31）

> 起因是项目复盘中的一个直感："功能是不是太多且太独立了，给人一种很混乱的感觉"。全量盘点结论：「功能太多」成立、「各自为政」不成立（api.js/tokens.css/身份联动等共享基建与跨功能数据链路已经很统一）——混乱来自"产品边界失控的叙事"：一个月七期专项迭代堆出 15 个功能域，产品名仍叫"模拟面试官"。本轮范围纪律：**功能零增删、后端业务逻辑零改动**（main.py 路由拆分与 CSS 双轨合流已由同日的 v7.2.2 工程整改完成），只动叙事、导航与品牌。

### 1. 定位与决策

- 产品定位向上延伸：「AI 模拟面试官与职业规划」→「**AI 求职陪跑平台**」，一句话定位"从定方向到拿 Offer 的全流程 AI 求职陪跑"；原命题的"诊断 + 规划"两条产品线成为六步旅程中的两步（诊弱点 / 定规划），命题不废、向上生长。方案全文见 `docs/产品定位延伸_全流程求职陪跑.md`，决策记录见 CHARTER **DC-07**（放弃的替代方案：收缩定位砍孤岛功能 / 维持原定位仅做文档修补）。

### 2. 信息架构（导航重组）

- 侧边栏域分组（面试域/资产域/洞察域/招聘端）→ 旅程分组：**备战**（简历库/岗位库/市场数据）/ **演练**（模拟面试/题库/历史记录）/ **洞察**（综合报告/长期记忆/职业规划）/ **连接**（收到的报告）+ 账户；成员按旅程顺序重排，默认落地面板仍为模拟面试，分组随身份显隐机制（`data-audience`）不变。
- 移动端底部导航按同一旅程顺序重排（简历→岗位→市场→面试→题库→历史→报告→记忆→规划→收件箱→账户）。

### 3. 品牌文案统一

- `index.html` 标题与 Header 品牌、`share.html` 品牌行与免责声明、报告导出页品牌（`backend/routers/reports.py`）、FastAPI title（"AI 面试官 v3.1" 自 v3.1 起失更，一并修正为 "AI 求职陪跑平台"，version 7.3.0）与启动日志、题库模板头（`questionBank.js`）、采集子包 docstring、`docker-compose.yml` 注释、`frontend/package.json` description——全部统一为「AI 求职陪跑」；版本徽标 v7.2 → v7.3。
- 主文档同步：CHARTER（产品命题改写 + DC-07）、README（标题/标语/简介/亮点置顶条目）、CODEBUDDY（定位/当前版本/结构树补齐 6 个缺失前端文件与 routers/）。

---

## v7.2.2 工程整改：main.py 路由域拆分 + CSS 双轨合流 + 临时文件治本（2026-08-31）

> 起因是外部评审点名的三笔结构债：66 条路由挤在 main.py 单体（2109 行）、style.css 与 components.css 双轨并存 + dark.css 自述废弃却仍在引入链、临时脚本反复误提交（git 历史两次专门清理）。本轮全部为**零行为变更**的结构整改——路由表逐条对账 + 全量测试回归验证。

### 1. 后端：main.py 拆分为装配层 + 路由域包

- 新增 `backend/routers/`（L4，与 main 同层登记进 .importlinter）：`state.py`（全局单例收敛：llm_client / diagnosis_engine / active_sessions / 限流器——switch_provider 的重赋值改走属性赋值，消除跨模块 import 旧实例的漂移风险）+ `deps.py`（认证依赖与归属断言的组合点）+ 11 个域路由（system / auth / voice / sessions / assets / reports / share / question_bank / diagnostics / market / analytics）+ `interview_ws.py`（WS 主循环整体迁出）。
- main.py 从 2109 行减至约 150 行纯装配：中间件、startup、include_router（保持原域顺序）、静态挂载。
- **零行为变更验证**：拆分前后路由表逐条 diff（65 条全对上，新增 4 条为 FastAPI 自带 /docs 族）；`run.py lint` 通过；全量 pytest 回归唯一失败是 test_career_planner 里 `patch("backend.main.career_planner...")` 的间接寻址——改为直接 patch 源模块 `backend.career_planner.plan_career`（对路由层未来重构更稳健）。
- 文档同步：CHARTER 约束 2 的 L4 行、README 项目结构。

### 2. 前端：CSS 双轨合流（数据驱动，零层叠位移）

- **实测推翻"style.css 是死遗留"的直觉**：320 条规则中 299 条在用——它是现役基础组件层，真正的债是双轨边界不明 + 21 条死规则 + dark.css 空文件。
- **合并采用零层叠位移路径**：style.css 全文并入 components.css，且 components 的 `<link>` 从页面样式之前**移到之后**（承接原 style.css 的加载位次）——逐文件验证选择器重叠：components 原内容与 pages/*.css 零真实重叠、style 与 auth 零真实重叠、与 motion 仅 2 处非冲突属性互补，故合流后所有层叠胜负与拆分前逐位等价。
- 剔除 21 条死选择器（17 个规则块，删除前用全量递归词法扫描二次校验，有出入即中止）；dark.css（659 字节纯注释自述废弃）摘链删除。
- tokens.css / market.css 中 4 处架构注释同步；dist 已重建。

### 3. 临时文件治本（针对"反复发作"）

- .gitignore 临时段从一次性清单通用化：根目录 `_` 前缀文件/目录一律不入库（`/_*`）。
- 新增 `tests/test_repo_hygiene.py`（3 条断言：根目录无 `_` 前缀跟踪文件 / 无散落 test_*.py / 无 .log/.db 运行产物）钉进 CI 全量测试——今后误提交在 push 阶段红灯，不再依赖事后人肉发现。

---

## v7.2.1 评审修复 + 黄金样本扩容 4→20 + CI 接入（2026-08-31）

> 起因是外部深度评审指出三处具体缺陷（分享页雷达图 / 导出复盘鉴权 / XSS 转义不成体系）与两项工程缺口（黄金样本仅 4 条、无 CI）。本轮范围纪律：只修评审指认的问题，不动架构（main.py 路由拆分、interview.js 拆层列为后续专项）。

### 1. 修复（评审指认）

- **分享页/招聘端雷达图从未绘制（v7.0.1 起）**：`shareReport.js` 的 `mountRadar(scope)` 引用了不在作用域内的 `data`（`renderReportInto` 的参数），每次挂载抛 `ReferenceError` 被静默吞掉——外部 HR 看到的分享页核心可视化恰好缺失。改为 `mountRadar(container, data)` 显式传参，并顺手把雷达硬编码 Indigo 蓝改为印章红色板。
- **导出复盘 Markdown 不带鉴权（v7.0 起）**：`api.js exportReview()` 裸 `fetch` 绕过了「全站唯一出口」约定（`api.js` 自身注释），登录用户导出会 401 且不触发全局登出广播。`request()` 增加 `raw` 选项（返回原始 Response，token 注入与 401 广播照常生效），导出改走统一出口。与 v7.2.0 §六的 `/export.html` 401 修复（token query 兜底）为两条不同导出路径，互补。
- **XSS 转义不成体系**：全站 `escHtml` 仅 6 处使用，同一类数据在 `report.js` 有转义、在 `interview.js` 裸拼。本轮立规矩「innerHTML 模板内插值一律转义」，落地 6 处：追加题理由（`data.reason`，LLM 相邻自由文本）、质量横幅薄弱维度名、轮次摘要薄弱维度名、技能条技能名（数字插值统一 `Number()` 化）、公司风格下拉（`<option>` 拼接改 DOM 赋值 `replaceChildren`，杜绝属性位逃逸）。

### 2. 黄金样本评测扩容（4 → 20 条）

- 原 4 条覆盖「量化/口号/完整/甩锅」四类；新增 16 条覆盖 10 条确定性规则的每个信号：数据矛盾、名词堆砌、答非所问、甩锅外部、回答过短、有动词无数字、量化充分、跨项目串联、坦诚不足、失败反思、双加分组合、三重扣分封顶、夹紧保护（模型已给 1 分时规则不重复扣）、高质量 `next_question`、短回答双信号。
- **expected 由规则引擎实算生成**（临时生成脚本跑 `detect_adjustments → apply_adjustments → weighted_score` 取真值），杜绝手算误差；`weakest_dimension` 意图与实算不一致即拒绝写入。过程中实算纠正了 3 处手算偏差（长回答 2-gram 重叠超预期触发 `irrelevant_answer` 共火等），全部如实标注为多信号组合。
- 新增样本暂无 `baseline`（deepseek-chat 实然快照待 live 扫描标定）：live-LLM 抽检对无 baseline 样本自动跳过基线守护层、保留结构软断言，避免虚构基线让 live 层变脆。
- 测试数 40 通过（20 样本 × 确定性回归 + 引用字面子串两层断言）。

### 3. CI 接入（GitHub Actions）

- `.github/workflows/ci.yml` 双 job：后端（pip 依赖 → `run.py lint` 分层契约 → 全量 pytest，live-LLM 默认 skip）+ 前端（`npm ci` → `npm run build` 冒烟，导入/语法错误即红灯）。采集器测试导入前已 stub playwright，无需下载 Chromium。

---

## v7.2.0 动效体系 + 「墨夜纸墨」深色重构 + 市场页样式作用域修复（2026-08-30）

> 起因是 UI 评审发现「双主题审美割裂 + 面板零过渡 + 动效碎片化」三件拉低质感的事（评审全文见 `docs/UI评审_v7.2_动效与高级感升级.md`）。本轮只动表现层：后端、业务逻辑、DOM 结构与类名体系全部不变。

### 1. 动效基建 `src/css/motion.css`（新增层）

- 动效 token 扩展：`--dur-gesture(200ms) / --dur-reveal(500ms) / --ease-emphasized / --stagger(60ms)`，全站动效时长/缓动收编进 token，页面不得私写数值。
- **面板切换过渡**：`app.js switchTab()` 优先走 **View Transitions API**（旧页淡出 + 新页上滑），不支持时降级为 `.panel-enter` 入场动画；新面板同屏子元素按 `--stagger` 错峰入场（最多编排前 10 个）。
- **骨架屏**：`utils.js skeletonBlock()`（纸纹 shimmer 扫光）替代「廉价 spinner」——接入 report 加载、history `loadingIndicator`、recruiterInbox、shareReport 四处。
- **仪式感动效**：`stampIn()` 印章盖章（scale 落定 + 墨晕扩散，登录/注册成功落在登录卡上，650ms 后切视图）；`countUp()` 数字滚动（报告页评分环 0→总分滚动 + `.ring-draw` 环形描边绘制）；`shake()` 表单校验失败水平抖动；`.btn-press` 按压墨点涟漪；`.stream-box` 诊断流式框左侧朱砂流光。
- 全部动效挂 `prefers-reduced-motion` 降级（motion.css 自带 + 沿用 base.css 全局机制）。

### 2. 深色主题重构：赛博蓝紫 →「墨夜纸墨」

- **推翻 v7.1 的深色配色**（`#1C1F3B` 蓝紫渐变 + 青/粉/金/紫霓虹 + 四色语义切换器）：深色不再是另一套审美，而是同一枚印章在夜里的样子——炭墨纸底 `#161916→#1E221E`（墨绿灰调）、印章红提亮为朱砂 `#E06A52`、黄铜 `#C9A961`、墨青 `#5FA896`，与浅色纸墨同源。
- `themeToggle.js` 移除语义色切换器（给用户四种强调色选择是「不自信」的信号，高级产品替用户做决定）；`theme.css` 全量重写为墨夜覆盖层。
- 旧变量名（`--cyan/--pink/--coral/--accent-from` 等）保留为兼容别名、值重映射进墨夜色板，market.css 等旧引用自动跟随，零改名成本。

### 3. 信息架构与框架精修

- 侧边栏 11 入口平铺 → **四组分区**：面试域（模拟面试/历史/题库）、资产域（简历库/岗位库）、洞察域（报告/市场/记忆/职业规划）、招聘端（收件箱，按身份显隐）+ 账户；组标题随身份过滤联动（`applyRoleView` 扩展）。
- 修正 `<title>`（原「AI面试官与职业规划 v3.2」→「AI 模拟面试官」）与版本徽章 v3.2 → v7.2；品牌印章 hover「回正放大」微动效。

### 4. 修复：市场页整套设计系统从未生效（v7.1 遗留）

- **`market.css` 全部样式作用域写在 `#market-panel`，而真实面板 id 是 `#market-data-panel`**——约 600 条规则（含全部深色覆盖）自引入起就是死规则，市场页一直以「无设计系统」的裸状态渲染。全局替换修正作用域 id。
- 清理 market.css 深色段残留的赛博蓝紫硬编码（indigo/sky 径向光晕 + `#0F1226→#1A1030` 渐变 + 青色印章描边），统一并入墨夜纸墨色板。

### 5. 回归中发现并修复的存量 bug（实数据链路验证时暴露）

- **报告页「生成分享链接」报 `request is not defined`（v7.0 起）**：`report.js` 三处分享接口调用使用 `request()` 但未从 `api.js` 导入——分享功能自 v7.0 上线起实际不可用。补齐 import。
- **分享页/招聘端收件箱五维雷达图从未绘制（v7.0.1 起）**：`shareReport.js` 的 `mountRadar(scope)` 内部引用了不在作用域内的 `data` 变量，每次挂载抛 `ReferenceError` 被静默吞掉。改为 `mountRadar(container, data)` 显式传参；顺带把雷达硬编码 Indigo 蓝（canvas 不解析 CSS 变量）改为印章红色板。
- 面板入场动画兜底：动画时钟被冻结时（后台标签页节流），stagger 子元素会停在 `opacity:0`——`switchTab` 在 1.2s 后强制摘除 `panel-enter`，内容直接落到可见态。

### 6. 评分揭晓仪式感补全 + 导出页「同脸」（采纳外部方案，详见 docs/UI评审_v7.2 §五/§六）

- **动效纪律成文化**：时长上限（常规 ≤400ms、>1s 仅限揭示时刻）、JS 动效显式读 `prefers-reduced-motion`、一场面试最多 2 个 WOW 时刻——写入 docs/UI评审_v7.2 §五作为全站约束。
- **评分揭晓粒子爆发**：分数滚动落定瞬间从评分环径向爆出 16 粒（`utils.js burstParticles`），颜色随分数分级（≥4.0 墨青/黄铜/朱砂，3.0–4.0 黄铜/朱砂，<3.0 深红/黄铜）；实测 maxParticles=16。
- **报告页五维总览卡**：新增五张迷你卡（与分享页 share-dim 同脸，等宽大数字 + 分级色条），spring 弹入 stagger 110ms。
- **Quote 证据引用渲染（v7.0 字段首次上屏）**：`DimensionScore.quote` 在面试诊断卡中以黄铜左边条证据块呈现 + 首次黄铜扫描线（「AI 在审视你的原话」的视觉化）。
- **导出页纸墨皮肤（同脸）**：`/export.html` 模板从 GitHub 蓝换成米纸底 + 印章红衬线标题 + 黄铜 blockquote + 「面」字印章品牌眉标。
- **导出页 401 修复（v7.0 遗漏路径）**：导出页经 `window.open` 顶层导航打开带不了 Authorization 头——token 支持 query 参数兜底（与 `resolve_ws_user` 同一权衡），前端按钮登录态自动拼接。

---

## v7.1.0 全站 UI 统一为「纸墨印章」风格（2026-08-30）

> 起因是市场数据 Tab 的前端视觉与站内「纸墨印章」设计规格不一致；澄清后范围扩大为**全站 11 个 Tab 统一视觉语言**——功能布局与 DOM 结构保留，只重做视觉。因规格文档源自「采集 / 列表 / 详情」三类页面，其余 8 个 Tab 无现成模板，故以其**设计 Token + 组件规范**重新拼装，而非字面复制结构。

### 1. 设计基线（可复用资产）

- 新增 `docs/job-crawler-UI设计系统规格.md`：从既有页面源码（`base.html` / `theme-dark.css` / `theme-toggle.js` / `input.html` / `data.html` / `job_detail.html` / `collect.html`）一次性抽取的权威规格，含 12 个米色 Token、字体三件套、组件完整 CSS（navbar / card + `data-no` 角标 / stamp / eyebrow / btn 族 / interest-btn / form / table / alert / data-row / tag-chip …）、深色覆盖表、语义色四色值与页面骨架。**后续改造以此文档为唯一基线**，避免反复读源文件导致细节遗漏。

### 2. 改造策略：Token 重映射（而非逐行重写）

- `tokens.css` 重写：**变量名保持不变，仅重映射色值**。全站引用的 `--card` / `--primary` / `--indigo-*` / `--slate-*` 等自动切换为纸墨色（印章红 `#C44F3A` / 米纸 `#F4F2ED` / 墨色 `#1F2320` / 青绿 `#3A7A6A` / 黄铜 `#A08945`），1162 行 `style.css` 与各页 CSS 无需改名即整体换肤。
- 新增 `--primary-rgb` / `--success-rgb` / `--warning-rgb` / `--danger-rgb` / `--ink-rgb` 三元组：把 `style.css` 中约 50 处字面 `rgba(79,70,229,α)` 与 hex 字面色改为 `rgba(var(--primary-rgb), α)`，**双主题自动跟随**。
- 字体：`--font-family` 改 Noto Sans SC，新增 `--font-serif`（Noto Serif SC，标题/品牌）、`--font-mono`（JetBrains Mono）；`index.html` 引入 Google Fonts 三件套。

### 3. 双主题机制（对齐设计规格）

- 新增 `themeToggle.js` + `theme.css`：切换改为**手动切换 `html.theme-dark`**（原为跟随系统 `prefers-color-scheme`），localStorage 记忆、内联防 FOUC 脚本、派发 `theme:changed` 事件；深色下挂载**青/粉/金/紫语义色切换器**（写 `--accent-from/--accent-to`，sessionStorage 记忆）。
- 废弃 `pages/dark.css`：其 Indigo 时代的硬编码深色修正会覆盖变量驱动的正确取值、造成深浅割裂，已清空并注明原委。

### 4. 框架与各页

- `components.css`：品牌标识改**圆形印章**（`rotate(-6deg)`）、导航项改 22px 胶囊、侧栏/底栏深色毛玻璃。
- `base.css`：标题统一 Noto Serif SC / 900。
- 逐页清理字面色：`market.css`（`--mkt-*` 全部指向全局 Token，深色块选择器改 `html.theme-dark #market-panel`）、`auth.css`、`interview.css`、`history.css`。
- **JS 内联与图表配色**：`report.js`（21 处）、`careerPlan.js`、`liveRadar.js`、`interview.js`、`questionBank.js`、`marketData.js` 中，内联 style 颜色改 `var()`（自动跟随主题），Chart.js canvas 颜色改纸墨调色板（canvas 不解析 `var()`，必须给具体值）。
- `marketData.js` 移除自研主题逻辑（`applyTheme` / `applyAccent` / `toggleTheme` 与本地切换按钮），市场数据 Tab 主题统一由全局切换器控制，消除"Tab 内另有一套主题"的割裂。

### 5. 市场数据 Tab：DOM 结构与交互对齐规格文档

- **采集视图**（对齐 `input.html`）：Hero（`eyebrow「招聘市场数据分析」` + h1「招聘信息实时数据分析系统」+ subtitle）→ `card[data-no="查询与采集"]`；表单字段与文案沿用（岗位名称 / 排序方式 / 实时采集页数 1~5）。城市选择改为**省份 select → 城市 select →「＋ 添加城市」→ 已选 `tag-chip`** 级联（原为"选省份后点城市 chip"），交互与文案一致。
- **岗位列表视图**（对齐 `data.html`）：`eyebrow「数据展示」` + h2「招聘数据档案」；`card[data-no="共 N 条记录"]`（角标随筛选实时更新）+ 表格列沿用（职位 / 公司 / 城市 / 最低薪资(千元) / 最高薪资(千元) / 发布时间 / 感兴趣）；`.data-row` **整行悬停上浮 `translateY(-3px) scale(1.02)` 并变蓝、点击整行跳详情**；翻页改为「← 上一页 / 第 X / Y 页 / 下一页 →」。
- **岗位详情视图**（对齐 `job_detail.html`）：`eyebrow「岗位详情」` + h2「职位档案详情」→ 卡片左侧 4px 青绿描边 + 标题行（h3 职位 / 🏢公司 · 📍地区）+ 信息网格（薪资范围用等宽青绿大字 / 学历要求 / 经验要求 / 发布时间）+ 职位描述（限高 400px 可滚动）。
- **增强并存**（未因 1:1 而丢失）：行首多选框 → 跨岗位对比（勾选后行描边，点选框 `stopPropagation` 不触发整行跳转）；统计概览卡（岗位总量 / 平均薪资 / 热门技能 TOP5 / 样本城市）；学历 + 薪资区间筛选（原规格无，作为第二行扩展）；采集进度轮询条；详情页 Gap 分析卡。
- **「感兴趣」前端化**：原页面走后端 `/toggle_interest`(CSRF)，本项目无此接口——沿用 `.interest-btn` 视觉与「感兴趣 ⇄ 已收藏」交互，状态存 `localStorage['_mkt_interested']`，零后端改动。
- **一处必要取舍**：原页面文案为「选择城市（可选，不选则全国范围搜索）」，但本项目后端 `POST /api/market/crawl` 的 `cities` 是 `Form(..., min_length=1)`（强制非空），故文案改为「选择城市（可多选）」并保留必选校验，避免误导用户触发 400。

### 6. 后端配套改动（上一节两处取舍的收口）

- **放开「不选城市 = 全国搜索」**：`scrape_jobs` 底层本就支持（空列表 fallback 到 `("全国","000000")`），API 层的强制非空是后来加的保守限制。改 `main.py` 的 `cities` 为 `Optional[List[str]] = Form(None)` 并在函数内归一化，改 `tasks.validate` 去掉 `not cities` 判断（保留 >5 上限）。`api.js` 用 `cities.forEach` 传参，空数组时自然不传该字段，无需改动。前端文案恢复为「选择城市（可选，不选则全国范围搜索）」，未选城市时提示"将按全国范围采集"。
- **收藏持久化到 market.db**：新增 `job_postings.is_interested` 字段（含基于 `PRAGMA table_info` 的幂等迁移——“`CREATE TABLE IF NOT EXISTS` 改不动已存在的库”）+ `store.toggle_interest()` + `POST /api/market/jobs/{job_id}/interest`。采用与题库 `question_bank.is_favorited` **完全相同的模式：全局标记、不区分用户**（market.db 为单机单用户库，且项目支持免登录使用）。刻意不更新 `updated_at` —— 收藏是用户态，不应改写数据时间戳。前端 `isInterested(job)` 直接读接口返回的 `job.is_interested`，不再用 localStorage。
- **不覆盖收藏的保证**：`upsert_jobs` 的 INSERT 与 `ON CONFLICT DO UPDATE SET` 均不含 `is_interested`，故重新采集不会清空已有收藏。
- **测试**：全量 **982 passed + 1 skipped**，与改造前基线一致，零回归（`TestValidate` 原本未断言"空 cities 必须报错"，故放开不受影响）。

### 7. 验证

- `npm run build` 通过，lint 0 错误；接口实测：`TOGGLE true → false` 正确切换，列表返回 `is_interested` 字段，978 条数据完好；数据库迁移幂等（`HAS_FLAG: True`）。

### 8. 补齐遗漏组件 + 死代码清理（对齐规格 §7 检查清单）

> 上节改造后逐项核对规格文档 §7 的 13 项检查清单，发现 7 项未落实，本轮补齐。

**补齐的组件（market.css + marketData.js）**

| 组件 | 规格 | 落地 |
|---|---|---|
| `.stamp` 印章 | §4.3 | 64px 圆形、`rotate(-9deg)`、2px 印章红描边；用于详情页标题左侧（文案「档案」）；深色下转青描边 |
| `.alert` / `.alert-danger` / `.alert-info` | §4.8 | 采集结果用 `alert-info`（含「查看刚采集的数据 →」）、错误用 `alert-danger`；**取代原自研 `.mkt-error`**，显隐统一由 `.visible` 控制 |
| `.btn-detail` | §4.15 | 详情页「🔗 查看详情」加该类，橙色渐变 `135deg,#FF6B35,#F7931E`；深色下转语义色渐变 |
| `.fade-up` 入场动效 | §4.11 | `home-wrap` / `home-card` / `home-feature-grid` 三层递进；`prefers-reduced-motion` 下自动降级 |
| `.home-feature-grid` / `.home-feature-card` | §4.12 | 采集视图底部三张入口卡：📊 岗位档案（切岗位库视图）、🎯 职业规划、📚 岗位库（后两者复用全局导航项跨 Tab 跳转） |
| `.restored-badge` | §4.9 | 已补齐样式备用（当前无"恢复上次结果"场景，默认隐藏） |
| 深色卡片左侧 4px 渐变光条 | §5 | `html.theme-dark #market-panel .card::after`，用 `::after` 避开 `data-no` 的 `::before` 冲突 |

- **跨 Tab 跳转**统一走 `goToTab(tab)` → 触发 `.nav-item[data-tab]` 的 click，不重复实现路由。
- 三张入口卡用 `<button>` 而非 `<a>`（需执行 JS 跳转），CSS 已补 `cursor` / `text-align` / `font-family` / `width` 使其与 `a` 视觉等价。

**死代码清理（market.css 1877 → 1280 行，−597 行）**

改造时保留了旧的自研 `--mkt-*` 体系，其中一批类在 DOM 改造后已无人引用。逐个在 `frontend/src` 全目录验证"仅存在于 market.css"后删除：

- 采集视图旧体系：`.mkt-banner`（含 `::after` 水印）/ `.mkt-count-badge` / `.mkt-form-grid` / `.mkt-field` / `.mkt-input` / `.mkt-select` / `.mkt-city-row` / `.mkt-city-chips` / `.mkt-chip` / `@keyframes mkt-pop`
- 列表旧体系：`.mkt-table-wrap` / `.mkt-table` 全家桶 / `.mkt-cell-*` / `.mkt-salary` / `.mkt-date` / `.mkt-link-51` / `.mkt-row-check` / `.mkt-checkbox` / `.mkt-pagination` / `.mkt-page-btn`
- 详情旧体系：`.mkt-detail-back` / `.mkt-detail-head` / `.mkt-detail-company` / `.mkt-detail-title` / `.mkt-detail-badge` / `.mkt-detail-info` / `.mkt-info-cell` / `.mkt-info-value` / `.mkt-detail-grid` / `.mkt-desc`（含 `h3` / `.mkt-desc-text`）
- 主题切换旧体系：`.mkt-theme-zone` / `.mkt-theme-toggle` / `.mkt-accent-picker` / `.mkt-accent-dot` / `.theme-cyan|pink|gold|purple`（v7.1.0 已移交全局 `themeToggle.js`）
- 其它：`.mkt-error` / `.mkt-card-sub` / `.mkt-btn-block` / `.mkt-actions`，以及深色覆盖层与响应式断点中引用上述类的选择器

**保留**（仍在用）：`.mkt-topbar` 顶栏 / `.mkt-progress*` 进度条 / `.mkt-stats-row` 统计卡 / `.mkt-filters` / `.mkt-compare-bar` / `.mkt-gap-*` / `.mkt-dim-*` / `.mkt-rank-*` / `.mkt-loading` / `.mkt-empty` / `.mkt-btn*` / `.mkt-card*` / `.mkt-resume-ta` / `.mkt-info-label` 等增强组件。

### 9. 验证（本轮）

- `npm run build` 通过（4.33s），lint 0 错误；新增组件 JS/CSS 配对已逐项核对（`home-feature-card` / `fc-arrow` / `btn-detail` / `fade-up` 在两边均存在）。
- 其余 10 个 Tab 零改动：本轮仅改 `market.css` 与 `marketData.js`，且新增样式全部位于 `#market-panel` 作用域内。

---

## v7.0.3 测试策略 v2：行为化精简 + 黄金样本回归（2026-08-30）

> 按《测试用例审计与精简方案》执行（先评估修正口径，未盲追数字）。审计显示 ~45% 的测试"锁 prompt 文案"且"诊断准不准"零覆盖——本轮把**测错对象的测试**收拢为行为断言，并首次补齐**诊断准确性**缺口。评估与执行差异记录在方案文档 §八。

### 1. 行为化精简（删脆弱、保行为）

- **`test_security.py` 56 → 37 函数**：5 组同构案例 parametrize（8 条注入句式 / 3 条输出泄露 / 6 条非法质量 / 5 条记忆污染 / 2 条歧义词），每条保留独立 ids 与注释，case 数不减少。
- **borrowings 三文件行为化**：追问链断言改为"从配置取链断言"（等价改写 prompt 不再爆红）；收尾指令断言改配置派生；合并重复的"约束文本覆盖/注入"用例；删除低价值静态字符串断言。**未按原案砍到 50→20——实读发现这些文件 85% 是有效行为测试**（评分修正/压力题库/恢复红线/TTS 缓存/语音降级），硬砍会误删真实覆盖。
- **`test_data_support.py`**：空/未命中兜底案例 parametrize。

### 2. 黄金样本回归（新增，首次覆盖"诊断准不准"）

- `tests/fixtures/golden_answers.json`：4 类典型回答人工标注（量化充分但 STAR 欠缺 / 全篇口号 / STAR 完整且量化充分 / 甩锅避答），每份含人工诊断 JSON + expected 区间。
- `tests/test_diagnosis_golden.py` 两层：
  - **确定性回归**（默认跑，8 用例）：固定答案 + 固定标注 → 断言 `run_diagnosis → normalize_result` 链路的**总分区间 / 最弱维度 / 加扣分项命中 / 引用必须是原回答字面子串**。
  - **live-LLM 抽检**（`@pytest.mark.live_llm`，默认 deselect）：真实模型结构软断言，分数交人工比对。运行：`GOLDEN_LIVE_LLM=1 GOLDEN_LIVE_LLM_API_KEY=sk-... pytest tests/test_diagnosis_golden.py -v`。
- **方法论修正**：原案"FakeLLM 下断言 ±0.5 分"自相矛盾（诊断打分在 LLM 里）——落地为"确定性回归 + live 抽检"两层。

### 3. 测试

- 全量 **982 passed + 1 skipped**（live_llm 预期跳过），0 失败；函数级 903 → 890。
- 覆盖度不降：`security.py 97% / score_adjustments.py 91% / diagnosis_engine.py 76%`。

---

## v7.0.2 追认测评问题：追问跳过留痕 + JD 文件上传解析（2026-08-30）

> 全链路人工测评发现的两个产品问题（`docs/测评问题记录.md`）本轮收口：让"跳过追问"从零成本零痕迹变得**如实记录**；JD 输入从"只能手贴"变成"支持 PDF/TXT/DOCX 文件导入"。

### 1. 追问跳过留痕（测评问题 #1，方案 C）

- **不扣分、但留痕**：跳过追问时在本题诊断记录上打 `follow_up_skipped` 标记并留存被跳过的追问文本（`session.py` 新增 `mark_follow_up_skipped()`，由 `main.py` 跳过分支调用）。评分口径不变——追问补充本就"并入语境不重评"，现在"回避追问"也如实可见。
- **综合报告如实提及**：`report.py` 逐题拆解带出 `follow_up_skipped` / `skipped_follow_up`；新增 `follow_up_stats`（跳过次数 / 占比 / 题单，与 `assistance_stats` 同构）；有跳过时在建议末尾追加一条独立复盘信号（"⚠️ 本场有 N 次追问被跳过…"），不混入打分链路。
- **分享页同口径披露**：`share_access.py` 的 `_qa_details` 带出 `follow_up_skipped`，招聘端只看得到与求职者一致的诚实标注。

### 2. JD 文件上传解析（测评问题 #2）

- 新端点 `POST /api/upload-jd`：复用 `resume_parser`（PDF/TXT/DOCX），与 `/api/sessions/upload` 同款限流 / 10MB 大小硬限制 / 扩展名白名单 / 413·400 错误处理；解析失败（提取不到文本）返回 400。
- 前端：JD 文本框上方新增"解析文件"上传控件（`interview.js`），解析结果回填 textarea 并脱离岗位库关联；`api.js` 新增 `uploadJd()`。
- 解析结果不入岗位库——与"临时上传即开练"的简历上传同一语义。

### 3. 测试

- 4 passed（+4）：`mark_follow_up_skipped` 三态（标记/回退 pending/无诊断不崩）、`build_report` 带出 `follow_up_stats` 与建议提及、`/api/upload-jd` TXT 解析成功 + 非法扩展名 400 + 空文件 400、`_qa_details` 透传 `follow_up_skipped`。

---

## v7.0.1 统一登录 + 身份分流：招聘者收件箱（2026-08-30）

> 用户反馈：求职者与招聘者的登录界面应该是同一个，登录成功后按身份进入不同的系统。本轮补上"招聘者登录后的系统"——**收件箱**；A 模型数据流（求职者自主发起 + 分享）不变。

### 1. 后端

- `share_links` 加 `shared_with` 列（存收件招聘者**用户名**——分享者只知道对方用户名，输入即存储；本系统用户名唯一且无改名功能，等价于 id 且省一次联表）。建表语句同步更新；已部署的老表走 PRAGMA+ALTER 迁移。
- 分享接口加可选 `shared_with` 参数，签发时校验：目标用户**存在且 role=recruiter**。错误信息刻意不区分"不存在"与"不是招聘者"——两者同一句，防止用分享接口探测已注册用户名。
- 新端点（仅 recruiter 角色）：
  - `GET /api/recruiter/inbox`——收到的报告列表（摘要层：总分/完成时间/浏览次数）。
  - `GET /api/recruiter/reports/{token_hash}`——打开收件箱中的报告（完整脱敏载荷），仅发件指定的本人可见，他人一律 404。
- **两条通道刻意隔离**：免登录的 `/api/shared/{token}`（凭明文链接）与登录态的收件箱（凭身份）互不放大对方风险面。收件箱里只存 token 摘要，打开报告走归属校验而非明文比对。
- **链接过期 ≠ 收件箱消失**：过期只限制免登录链接通道；已投递到收件箱的报告仍可读（类比：邮件链接过期了，邮件还在收件箱里）。有专门测试钉住这个语义。

### 2. 前端

- **按身份分流导航**：招聘者登录后只看到「收到的报告」+「账户」两个面板，求职者面板全部隐藏（`nav-item` 加 `data-audience` 标记，`app.js applyRoleView` 过滤）；求职者/匿名看不到收件箱。
- 登录成功即分流：招聘者 → 收件箱；退出 → 回面试页。**页面刷新后分流保持**（`refreshAuthStatus` 启动时也派发身份事件——此前只刷新头部，会漏掉导航分流）。
- 新增 `recruiterInbox.js`「收到的报告」面板：卡片列表 + 内嵌打开报告详情（复用 `shareReport.js` 抽出的 `renderReportInto`，不跳出主应用）。
- 报告页分享区块加可选"招聘者用户名"输入：填了进对方收件箱，留空则仅生成免登录链接。

### 3. 测试

- 971 passed（+8）：`test_share.py::TestRecruiterInbox`——收件人校验（不存在/非招聘者）、收件箱按登录身份隔离、撤销即移出收件箱、非本人打开 404、**过期后收件箱仍可读**、HTTP 层角色拦截（匿名 401 / 求职者 403）。

---

## v7.0 双端平台化：认证与资源归属 + 三实体 + 报告分享 + 流程状态显式化（2026-08-29）

> 本轮把项目定位从"单端课程项目"转向"工程化平台"（DC-06）：求职者自主练习的产品命题**不变**，在外围加一层"身份与归属"，让同一套诊断内核可以服务"招聘者只读查看报告"这第二端。诊断链路（五维/双 Agent/追问）零改动。

### 1. 认证与资源归属（`backend/auth.py`，L2 新增）

- **分层落点**：认证刻意独立成 `auth.py` 而非塞进 `security.py`——后者定性是"面试回答内容的启发式检查"，与"密码哈希/JWT"是两种职责，混用会让 "security" 一词指两件事。已登记 `.importlinter` L2 行，`run.py lint` 强制。
- **可关闭开关（回滚承诺）**：`AUTH_ENABLED=false`（默认）时 `get_current_user` 恒返回匿名身份、所有归属过滤跳过，**行为与 v6.x 完全一致**——`tests/test_api.py::TestAuthIntegration::test_disabled_matches_legacy_behavior` 是这条承诺的回归底线。
- **安全设计**：bcrypt 哈希（自带盐，同密码两次哈希必不同）；JWT HS256，密钥优先取 `AUTH_SECRET` 环境变量，缺省生成并持久化到 `data/.auth_secret`（避免重启后所有 token 失效）；登录失败不区分"用户名不存在"与"密码错误"（防枚举），用户不存在时也执行一次哈希校验（防计时侧信道）；**越权一律 404 而非 403**——403 会暴露"该 id 存在"。
- **WebSocket 握手校验**：token 走 query 参数（浏览器 WS API 不支持自定义请求头），在 `accept()` **之前**校验，失败 `close(4001)`——消除 CHARTER 披露的"WS 无身份校验"局限。前端 `createInterviewWS` 在每次重连时重新读 token，收到 4001 停止重连。
- **归属语义**：会话/简历/岗位按 `owner_id` 归属；存量数据（owner=NULL）在认证开启后对任何登录者不可见，但**数据未丢**（关掉开关仍可查看）。
- **遗留坑记录**：slowapi 的 `@limiter.limit` 靠**参数名** `request` 注入请求对象——改名（如 `http_request`）会让全部限流端点在启动期抛 `No "request" argument`。

### 2. 简历库 / 岗位库（可复用输入资产）

- 简历此前**不落库**（每次开练重新上传、重新调 LLM 解析）；岗位 JD 每次重新粘贴。新增 `resumes` / `positions` 两张表（`CREATE TABLE IF NOT EXISTS`，老库自动生效），CRUD + 归属过滤沿用"一个可空 owner_id 参数"的统一约定。
- `sessions` 表加列走 `_ensure_owner_columns`（沿用 `_ensure_weakness_columns` 的 PRAGMA+ALTER 范式）。**SQLite 的 `ALTER TABLE ADD COLUMN` 不支持 `REFERENCES`**，owner_id 不带外键，完整性由应用层保证——这是硬限制，已在注释中写明。
- 上传入库走**新端点** `POST /api/resumes/upload`（不截断）：旧的 `/api/sessions/upload` 为兼容前端截断到 5000 字，入库场景沿用会静默丢失内容，且截断发生在用户看不见的地方。旧端点行为原样保留（有回归测试钉住）。
- 面试面板新增"来源切换"：库内选用 / 粘贴上传。**库只是填充器**——选中后把文本写进同一个编辑框，用户手改即脱离库关联（提交内容以编辑框为准，避免"选了 A 简历却发出去手改内容且仍标记成 A"）。

### 3. 报告分享（招聘端只读入口）

- **凭据模型**：token 为随机高熵串（`secrets.token_urlsafe`），**库里只存 SHA-256 摘要**——库泄露不等于链接泄露。明文只在签发响应中出现一次。
- **免登录只读**：`GET /api/shared/{token}` 无需鉴权（拿链接的是外部 HR）。"不存在 / 已撤销 / 已过期"对外**统一 404 与统一措辞**——响应差异会让攻击者枚举有效令牌。`share.html` 为独立入口（不套主应用外壳，HR 不应看到求职者的私人面板），页面带 `noindex`。
- **输出侧脱敏**：手机号/邮箱/身份证/QQ 微信号在**构建分享载荷时**打码（不可逆，故只能在给外人看的那一刻做；原始回答仍完整保留给本人复盘）。逐题问答**默认不公开**（`include_detail=False`）——逐字答案是夹带隐私风险最高的部分。
- **诚实标注**：分享载荷逐题明细带 `assisted` 标记（该题是否借助引导完成），让读者自己判断分数成色。
- **列表不含 token**（哪怕是摘要）：凭据不进列表接口；撤销只对"本次生成的链接"开放（持有明文的场景）。

### 4. 面试流程状态显式化（`backend/interview_engine/flow.py`，L3 新增）

- 把"接下来该做什么"从六个分散的实例方法（should_follow_up / has_more_questions_in_round / check_round_quality / should_add_extra_question / is_closing_round / advance_round）收敛为**纯函数 `decide_next(FlowSnapshot) -> FlowDecision`**：决策输入是不可变快照，输出是动作+目标状态+理由。分支判定第一次可以被纯函数级单测覆盖（`tests/test_flow.py`），不依赖会话对象/LLM 桩。
- 判定顺序即优先级，其中两条"看似显而易见实则踩过坑"的顺序被显式固化：连续不会答的保护性干预**排在追问上限之前**（否则恰好被第三次追问拦掉）；收尾轮强控**排在追问信号之前**。
- `InterviewSession.snapshot(**overrides)` 支持"预演"——临时改输入看会怎么决策，不动会话状态。
- **流程位置落库**：出题→`waiting_answer`、追问→`generating_follow_up`、推进→`advancing_round`、结束→`finished`，由 `_mark_flow` 统一封装（**吞异常只记日志**——进度可观测是锦上添花，绝不能因落库失败中断面试）。
- **明确不做断点续答**：那需要把 InterviewSession 全部字段序列化并从 DB 重建，改动面与风险远大于收益。当前保证"流程位置可追溯、答题进度不因重启归零"，恢复能力列入 README 已知局限。
- **顺手修正一处语义缺陷**：`check_round_quality` 的 passed 是纯数值比较，未答题时 avg=0 而部分轮次（破冰环节）threshold 也是 0，会得到"未答一题却判定通过"。快照里补上"必须有答题记录"的前提（只影响新决策，旧 `advance_round` 走另一条路径）。

### 5. 诊断评分强制引用原话（evidence 引用）

- 每个维度除 score/comment 外，必须输出 `quote`——从候选人回答中**原样摘录**的支撑片段（≤30 字，不得改写/概括/编造）。把主观打分锚定到文本证据，让"分数怎么来的"可复核。
- 字段名用 `quote` 而非 `evidence`：项目里已有"简历证据包（evidence package）"概念（注入给模型的素材），两者方向相反，同名会造成"证据"一词指两件事。
- 容错：模型未返回 quote 一律补空串——引用是增强项，缺失不阻断诊断（`tests/test_diagnosis_engine.py::TestQuoteEvidence`）。

### 6. 测试与文档

- 测试 **559 → 963**（+404）：test_auth（哈希/JWT/开关回退/归属隔离）、test_entities（三实体 CRUD/归属/上传完整性）、test_share（令牌/过期/撤销/脱敏/只读）、test_flow（纯函数分支 + 与既有逻辑一致性守护）。
- 全量 963 passed；`run.py lint` 分层契约通过。
- CHARTER：写入 DC-06；"无认证/WS 无身份校验"两条已知局限从"刻意取舍"改为"已解决"；范围纪律同步修订。

### 范围纪律

- 本轮新增：认证层、三实体（简历/岗位；题库已存在不动）、分享链接、流程状态化、quote 引用。
- 明确不做（与 DC-06 一致）：PostgreSQL / Kafka 异步评估 / 防作弊（切屏/眼神，与"自主练习"定位冲突）/ Python 版 LangGraph / 断点续答。

---

## v6.6 迭代专项七期：长期薄弱点衰减 + 面试技能状态机 + 动态难度（2026-08-29）

> 承接 v6.5 的两项改造，本轮继续补齐**三项能力缺口**。本轮的共性是：**三项都不是新功能，而是给既有能力补上"时间维度""状态维度""强度维度"**——v6.4 建成的长期记忆闭环里跑的是裸计数器，模式切换没有结束条件，出题难度恒定不变。

### 1. 长期薄弱点：EMA 衰减 + 30 天过期 + 中性区不动（`backend/weakness_memory.py`，L2）

把 v6.4 的 `_weakness_counts[t] += 1` 裸计数器升级为有强度的长期记忆：

- **阈值换算**：五维 1-5 分先映射为薄弱度 `(5-score)/4×100`，阈值 **<3.0 加重 / >4.5 减轻 / 3.0–4.5 中性**；加重用 EMA（α=0.4，10 次迭代残差 0.6%），减轻按比例衰减（×0.7），计数归零即删除。
- **岗位权重放大**：`weight/0.2` 夹 0.5–2.0 倍——岗位越看重的维度，同样失分越要命。复用 v2.6 的 JD 动态权重。
- **衰减靠时间而非练习次数**：中性区连 `last_seen` 都不续期 → "30 天没再暴露严重短板即视为已改善"。
- **存储分工**：`weakness_profile`=历史流水（图谱/建议），新增 `weakness_memory`=当前状态（每维度一行，新表用 `CREATE TABLE IF NOT EXISTS` 即可，无需 ALTER 迁移）。
- **升级兼容**：新表为空时回注入与复习建议**回退 v6.3 口径**——否则老库升级后首场面试会静默丢掉记忆回注入。
- 回注入 prompt 同步升级：从"历史均分 X"改为"最近得分 X，**累计失分 N 次**"，让模型区分"反复失分"与"一次失手"。

### 2. 面试技能状态机（`backend/interview_skills.py`，L3）

补上"临时插入、有步骤、有完成条件"的能力层——区别于既有 `switch_mode`（整场设定、无结束条件）：

- **接口**：`SkillBase{name/description/priority/can_activate/build_prompt/on_turn_end/is_complete}` + `SkillRegistry`（按 priority 降序，match 取首个命中；单技能判定抛异常不影响其它技能）。
- **两个关键的刻意选择**：
  - **触发**：纯关键词匹配（穷举 `"和…的区别"` 变体）会把普通回答误判为触发；因此**默认显式触发**（WS `skill` 消息），`can_activate` 仅在开启自动匹配时参与。
  - **结束**：技能完成不能只清字段而沉默结束——返回 `closing_message`，工程层推送"已回到正式面试"。
- **技能轮不进诊断**：测验答案（"B"）不是面试作答，打五维分只会污染报告 → 技能轮单独维护 `skill_history`，不写 `all_diagnoses`/`answer_history`。
- **内置 3 个**：`quick_quiz`（5 题即时判分，P80）、`concept_teach`（苏格拉底讲解 ≤4 轮，P70）、`tech_compare`（5 维度对比，P50）。曾考虑的第 4 个 `project_highlight` 未纳入——与 STAR 诊断 + `resume_anchors` 高度重合。

### 3. 动态难度调度器（`backend/difficulty.py`，L2）

- **只做轮内自适应，不接管阶段推进**：难度调度器不参与阶段流转——阶段推进是 v6.2 的工程强控，让难度信号反向决定阶段流转等于把已收敛的可控性交回统计信号。本模块只回答"这道题出多难"。
- **信号源纪律**：不能用"回复长度"这类代理指标充当评分（整套调度会退化成噪声），直接取 `diagnosis_engine` 加权总分，且**无效分数（None/0/非数字）一律忽略**——诊断失败不是"得 0 分"，误记会把难度一路降到底档。
- **归因披露（必须配套）**：难度改变出题分布但评分标准固定，分数变低时须能区分"变差了"与"难度升了" → `trace` 逐题记录档位进报告 `difficulty` 字段，变档时 WS 推 `difficulty_change`。
- 出题 prompt 同步修正：此前"第 1 题热身、最后 1 题深度挑战"与难度档指令自相矛盾，改为"有难度指令则按档位，否则按递进"。

### 4. 测试与契约

- 新增 `test_weakness_ema.py`（28 例）/ `test_interview_skills.py`（29 例）/ `test_difficulty.py`（26 例）；全量 **830 例通过**，`run.py lint` 通过。
- 契约：`weakness_memory` + `difficulty` 注册 L2，`interview_skills` 注册 L3。
- 需求文档：`docs/archive/week8_记忆衰减与技能难度_需求.md`（本地过程资料，未入库）。

### 范围边界（诚实披露）

- **AI Coding 专项题库不做**：与"诊断回答质量"命题距离远；做成无状态旁路（刷新即丢、无评估）没有价值，纳入则须连会话引擎与报告一起改。
- ~~**技能未接前端 UI**~~ → **已补齐（同轮追加）**：面试页诊断侧边栏新增「🛠 面试技能」条——三个技能按钮显式激活（不靠关键词猜测）；激活中禁用其它按钮并显示 `技能名 步数/总步数` 与「退出技能」入口；技能轮发言经 `follow_up` 消息回带 `skill/step/total` 刷新进度；`difficulty_change` 以 toast 提示，让用户看见难度在动（否则分数变化无法归因）。`npm run build` 通过。
- 难度**不影响**轮次推进与阶段判定，仅在出题 prompt 层生效。
- 前端为 Vite 构建产物（`frontend/dist`），源码改动后需 `npm run build` 才会生效。

---

## v6.5 迭代专项六期：公司风格配置层 + PDF 文本两阶段修复（2026-08-29）

> 本轮在协作迭代中针对两处工程缺口落地改进：(1) 目标公司风格此前写死在代码常量里，加一家公司就要改码；(2) PDF 简历提取的换行损伤让后续解析与追问点提取质量不稳。共同原则是**配置外置 + 纯函数可测**：新增能力一律落成可单测的纯函数或可热加载的配置，且新模块落地的同轮即补端到端断言测试——功能"写了"和"接上了"是两件事。

### 1. 公司风格配置层（`backend/company_profiles.py`，L2 + `backend/company_profiles/*.yaml`）

采用**扫目录热加载**的 YAML 配置层，**加 YAML 即加公司、零改码**：

- **字段三层**：`role_description`（公司人格：评判标准/追问清单）+ `rounds[].match+instructions`（轮次行为）+ `evaluation_rubric`（评估量表，进报告 `company_rubric`）。内置字节/腾讯/阿里三份种子配置（内容按本项目诊断驱动风格编写）。
- **轮次匹配改用关键词**：按 `1/2/3` 数字键索引只兼容"一面/二面/三面"一种结构；本项目改为**轮次名关键词匹配**（"技术广度"/"技术一面"同时命中"技术"），拟真 6 阶段与传统 5 轮两种模式通吃。新增 `match_keywords` 按 JD 关键词命中数自动选定。
- **解析优先级**：前端显式选择 > JD 自动匹配 > 不启用；`"none"` 哨兵值明确关闭；未知名称降级为自动匹配而非报错。
- **注入点与顺序**：`get_interviewer_role_prompt()` 前置「公司人格 > 本轮公司指令 > 风格角色卡」——公司是外层人格，风格卡是内层语气，两者正交（修复过程中发现并修正 `parts` 列表被重建覆盖公司块的 bug，公司块必须 append 不能重建）。
- **容错哲学**（与 v6.2 简历追问点同款）：pyyaml 缺失 / 目录不存在 / 单文件损坏 / 空壳配置 → 跳过或整体降级，**绝不阻断面试主流程**。
- API：`GET /api/company-profiles`（前端选择器）+ `SessionCreateRequest.company_profile`；前端面试设置 Step 2 新增"🏢 目标公司风格"下拉（自动匹配/具体公司/不启用），接口失败静默保留兜底选项。

### 2. PDF 文本两阶段修复（`resume_parser.py`）

针对 PDF 提取文本的两类损伤（列宽切碎的软换行 / 标题条目与正文粘连）设计两阶段启发式修复：

- **Phase 1 逆拼接**：只认两种硬断信号（编号列表项、≥6 字母全大写标题——避免 API/SQL 被误判），其余全部拼回，仅 ASCII 单词相邻补空格；
- **Phase 2 复原**：中文简历章节词表（22 词）前后插空行、`·` 前换行、`-` 后（允许隔空白）紧跟 CJK 换行（`2023-09` 日期与负数天然不含 CJK 不受影响）、嵌入正文的编号项前换行（`3.14`/`3.5` 小数排除）。
- **两处边界收紧**：行首 `N.` 判定额外排除点号后紧跟数字（`"3.5倍"` 不再被当编号拆行），与嵌入判定口径对齐；`-` 规则允许隔空白（只处理 `-中文` 会漏掉更常见的 `"- 负责xx"`）。
- 全部纯函数（`_rejoin_broken_lines` / `_restore_structure` / `_repair_pdf_text` 等），`parse_pdf` 尾部调用，PDF 库无关。

### 3. 明确不做（范围纪律）

- **多模态图片注入不做**：本项目后端无任何图片输入链路，没有可挂载的调用点，强行预埋就是不可达的死代码。
- 动态难度调度器 / 技能状态机 / 薄弱点 EMA：留待下一轮（见 v6.6）。

### 4. 测试与契约

- 新增 `tests/test_company_profiles.py`（25 例：加载/匹配/片段生成/会话角色卡集成/坏 YAML 与空目录降级）+ `test_resume_parser.py` 追加 45 例修复用例；全量 **747 例通过**。
- `company_profiles` 注册 L2 层，`.importlinter` 契约同步，`run.py lint` 通过；`requirements.txt` 新增 `pyyaml>=6.0`（缺失时该层整体降级，非硬依赖）。
- 需求文档：`docs/archive/week8_公司风格配置与PDF文本修复_需求.md`（本地过程资料，未入库）。

---

## v6.4 迭代专项五期：长期记忆闭环 + 前端成品感（2026-08-29）

> 本轮在协作迭代中做两件事：**让长期记忆真正闭环**（练 → 评 → 记 → 再练，且能看见收敛），以及**补齐前端成品感**（可视化记忆图谱、统一设计 token、状态机收敛）。八项落地中后端四项已随 v6.3 提交窗口先行入库，本节补记完整叙事；前端四项为本节新增。落地时主动规避三类常见工程债：去重键不稳、图谱 2D/3D 双轨并存、页面各自复制粘贴样式——本轮新增部分全部按统一口径处理。

### 后端（已随 v6.3 窗口入库，此处补记叙事）

1. **RAG 注入去重**：`content_hash()`（blake2b 8 字节，跨进程稳定——不能用内置 `hash()`，它受 PYTHONHASHSEED 随机化影响，重启即失效）；`resume_retriever.select_context_tracked()` / `knowledge_store.retrieve(exclude_hashes)` / `augment_prompt_tracked()` 贯通去重参数，返回值携带指纹；两条纪律：**先过滤再走字符预算**（被排除的名额不得白占预算）、**耗尽必须回退**（长会话后期所有块都已注入，不回退则证据包恒空，去重反致能力退化）。
2. **备选题 / 换题**：会话层登记已问题目台账（文本 + 指纹），出题时以【已问题目清单·严禁重复】负向约束传入 `question_gen`；模型无视约束吐出重复题时，**把那道重复题追加进排除清单重试一次**（给出具体反例比反复强调规则有效，但只重试一次——重试是完整 LLM 往返）。
3. **长期记忆闭环**：`weakness_profile` 幂等迁移补 `resolved` / `updated_at` 列（`CREATE TABLE IF NOT EXISTS` 不会给已存在的表补列，必须 PRAGMA 检查后 ALTER）；新增 `PUT /api/weakness-profile/{id}/resolve`、`GET /api/weakness-profile/{id}/suggestions`（静态段注册在 `/{session_id}` 之前防参数吞并）、`GET /api/weakness-profile/points`；首轮出题回注入历史未解决薄弱点（【历史薄弱点·优先考察】，仅首轮注入一次，后续轮次重复注入是纯 token 浪费）；拉取失败降级为"无历史记忆"，不阻断面试。
4. **测试**：新增 `test_injection_dedup.py`（19 例）/ `test_alternate_question.py`（10 例）/ `test_weakness_memory.py`（17 例），覆盖指纹稳定性、去重与回退、迁移幂等（含老库升级）、resolved 闭环语义、换题重试上限。

### 前端（本轮新增）

5. **Design token 补强**：`tokens.css` 补 `--shadow-xs/xl/inset` 六级阴影、玻璃态 `--glass-*`、`--ease-standard` 微交互缓动（与 `--ease-out` 的"入场"语义区分）；`style.css` 落地全局组件类 `card-hover / btn-press / stat-chip / glass-panel / empty-state 三件套 / confirm 弹窗 / btn-danger`——页面不得各自重写（避免"视觉统一、实现却各自复制粘贴"）。
6. **长期记忆页 + 2D SVG 记忆图谱**（新文件 `memoryGraph.js` + `pages/memory.css`）：中心"薄弱点图谱" → 维度环形分布 → 子节点确定性哈希散开（FNV-1a 种子，**刷新不跳位**）；节点颜色 = 严重度×未解决率（红/橙/蓝/灰四级，token 化深色自适应）；SVG 二次贝塞尔连线、hover 节点↔明细项双向联动、点击节点滚动定位明细；平移缩放走 transform 合成层（缩放不重算路径）；每维度最多渲染 6 个子节点（超出聚合 +N）；**只做 2D 一套**（2D/3D 双轨并存是维护负担）。标记已解决即退出回注入与建议口径——闭环收敛动作。
7. **面试页状态机收敛 + 语音真打断**：`interview.js` 收敛为 `PHASE` 四态 + `setPhase()` 单一入口（副作用如状态灯统一驱动），锁定/恢复 4 条路径统一走 `setInputLocked()`（保留"超时保留草稿 / 拦截清空聚焦"等语义差异）；删除三个死状态（`pendingFollowUp` 无读取、`currentInterviewerName` 无读取、`autoReadEnabled` 无写入恒真）；修复 `connectWS` 重置不全（补 voiceState/计时器/思考计时，防第二场面试继承污染）与 `finishInterview` 后 `ws` 未置空（旧 socket 静默吞消息）。`voice.js` 引入语音世代号：`stopSpeaking()` 先摘 `onended` 回调再 pause，修复 `browserSpeak` 对 canceled/interrupted 也触发 `onEnd`、以及打断后 MiMo 失败误降级续播；`autoReadQuestion` 打断时仅复位 UI 不触发连锁动作。
8. **Onboarding 细节**：题库页"📄 模板"一键下载（内联字段说明 + 真实示例题，Blob 触发）、空状态三件套接入题库页与记忆页、全局 Promise 化确认弹窗（删除薄弱点等不可逆操作二次确认）。

### 工程化
- 全量 **655 例通过**、`run.py lint` 分层契约通过；前端零新依赖（图谱为原生 SVG/DOM）。

### 范围与约束（诚实披露）
- `knowledge_store` 的 tracked 去重接口仍是**前向储备**：业务检索当前只走 `ResumeRetriever` 一线，`augment_prompt_tracked` 暂无生产调用方（接口就绪，待职业规划/出题知识注入接线）。
- 图谱子节点每维度最多 6 个（超出聚合 +N）；<768px 收起图例、双击复位代替滚轮缩放。
- **端到端 Realtime 语音明确不做**：实时音频流会让 `output_sanitizer` 与结构化评分无处挂载，与 v6.2 以来的核心优势冲突，如需引入应单独立项并配"转录后离线评分"兜底。

---

## v6.3 迭代专项四期：面试官角色卡 + 简历锚点分类 + 规则化评分七项能力（2026-08-28）

> 与前三期最大的不同：前三期补的是**工程模式**（状态机、收尾强控、输出净化、JSON 容错），本轮补的是**内容资产**——面试官角色卡、锚点分类、追问范式、压力题库、评分 rubric。因此本轮改动以「数据结构 + Prompt 注入 + 确定性规则」为主，引擎控制流基本未动。新增测试 50 例，受影响面 326 例全绿，分层 lint 通过。

### P0：内容资产结构化（改动小、收益直接）

1. **面试官角色卡三件套**（P0-1）
   - `config.INTERVIEWER_STYLES` 7 种风格各新增三字段：`perspective`（视角独白：这个角色真正在评判什么）、`followup_chain`（追问链，3-4 环）、`never_ask`（**不会问**负向清单，≥3 条）。
   - 为什么必须有 `never_ask`：正向描述只能引导、模型会创造性发挥，负向清单才能划硬边界——没有它，友好型面试官会去聊宏观战略，角色立刻失真。
   - `session.current_interviewer()` 透出三字段；新增 `get_interviewer_role_prompt()` 拼装完整角色卡（语气 + 视角 + 追问路径 + 不问什么）。**刻意不改动 `get_interviewer_system_prompt()` 的返回语义**（既有契约，前端与测试按"原始语气指令"取用），两种语义分开。

2. **追问范式绑定角色**（P0-2）
   - 追问的两个自由度此前被混为一谈，导致 7 种风格"语气不同、结构同构"。现显式拆开：**问什么** ← 薄弱维度（来自诊断）；**怎么问** ← 角色追问链（来自角色卡）。
   - 落点两处：`generate_follow_up()` 独立生成路径注入角色卡；`_build_diagnostician_system(..., interviewer_role=)` 注入诊断侧——**追问主要由诊断 prompt 产出**，只改前者覆盖不全。注入时显式声明"不影响五维评分标准"，避免角色设定污染评分。

3. **简历锚点五分类**（P0-3）
   - 新增 L2 模块 `backend/resume_anchors.py`：五类锚点（技术选型 / 量化数据 / 架构设计 / 业务决策 / 团队管理），每类绑定一条追问方向。原有 `deep/vague` 二分只能定位"哪里值得问"，五分类才回答"该往哪个方向问"。
   - 一条高性价比判断：**简历中出现的每个数字都是高价值追问点**（metric 类对数字加权）。
   - 双路径互为兜底：① `resume_parser` prompt 新增 `anchors` 输出（LLM 分类，质量高）；② `classify()` 关键词规则兜底（确定性，零成本）。LLM 未产出或格式不符时自动回落 ②，功能不退化。
   - 两条刻意的取舍：数字权重只 +1（+2 会让"带领 5 人团队"常与 team 打平）；**并列即弃权**（宁可不分类，也不注入错误的追问方向）。

### P1：新增能力（工程量中等）

4. **评分规则化加减分项**（P1-1）
   - 新增 L2 模块 `backend/score_adjustments.py`：10 条确定性规则（6 扣 4 加），全部用正则判定，**每条修正都带 evidence（命中原文片段）**——解决纯 LLM 评分"不可解释、不可复现"两大缺陷，候选人问"为什么扣这分"时能给得出依据。
   - 扣分：数据前后矛盾 -2（同动词 + 不同比例值）、成果未量化 -1、名词堆砌 -1、答非所问 -1、甩锅 -1、回答过短未展开 -1。加分：量化充分 +1、跨项目串联 +1、坦诚不足并给学习方向 +1、失败案例与反思 +1。
   - 三重封顶：单条回答总扣分 ≤3、总加分 ≤2、单维度绝对值 ≤2；调整后夹紧 [1,5]，且**只作用于已评分（>0）的维度**（0 分表示未评分，规则无权抬升）。
   - `normalize_result()` 新增 `raw_dimensions`（模型原始分）与 `score_adjustments`，与 `dimensions`（修正后）并存可对照。

5. **JD gap 出题优先级显式注入**（P1-2）
   - `main.create_session` 调 `gap_analyzer.analyze_gap()`（`use_market=False`，避免重复查库）取低于 `JD_GAP_SCORE_THRESHOLD=3.5` 的维度作为缺口，注入 `InterviewSession(jd_gaps=...)`；出题 prompt 新增【JD 匹配缺口 · 优先考察】段，显式声明优先级链：**JD gap 区域（必问）> JD 强匹配区域（验证深度）> 简历锚点（补充探测）**。
   - 为什么不声明不行：模型会顺着简历走（简历内容在上下文里更"显眼"、更好写出具体问题），而真实面试官手里拿的是 JD。这个偏差靠模型自觉纠不回来。
   - 缺口可能对应候选人没有的经历 —— prompt 已要求改用「假设场景 / 迁移能力」问法，不得追问不存在的事实细节。

6. **压力题库随机注入**（P1-3）
   - 新增 L2 模块 `backend/pressure_bank.py`：5 类（方案被否 / 故障场景 / 反转 / 竞品对比 / 自我认知）共 16 道。**刻意不绑定任何简历与 JD 内容**——绑定了就失去"不可预测"的意义。
   - 补的是**内容层的压力**：此前压力只体现在语气（pressure 风格 / hardcore 模式），题目仍全部来自候选人准备过的范围；真实面试的压力很大一部分来自被问到没准备过的题。
   - 三道闸门：① 全局开关 `PRESSURE_QUESTION_ENABLED` + 整场限量 `PRESSURE_MAX_PER_SESSION=1`；② 破冰轮与收尾轮不注入（前者要放松，后者由 CLOSING_INSTRUCTION 强控收束）；③ 按 `attack_level` 抽签（`PRESSURE_PROB_BY_ATTACK_LEVEL`，友好/鼓励型概率为 0——否则人设撕裂）。
   - 按类别**轮转取题**（每类先取 1 道再取第 2 道），避免连着问两道同类题。注入即登记进 `asked_questions`，与既有换题去重机制共用。

7. **恢复态红线 + 3 次阈值 + assisted 标记**（P1-4）
   - **绝不给答案**：`COACHING_RECOVERY_INSTRUCTION` 新增红线（禁"参考答案/正确答案/应该这样回答"等，只给"怎么想"与"从哪说起"）；`output_sanitizer` 新增 `contains_answer_leak()` 做工程兜底，命中则确定性替换为引导话术。边界说明：系统的「回答改写」是另一条独立通道（前端单独展示），不属于面试官话术。
   - **连续 3 次触发主动建议跳过**：`recovery_streak` 连续计数（正常回答归零），达阈值时由工程层用确定性话术覆盖模型追问，且**允许突破 `FOLLOW_UP_MAX_COUNT`**——否则这条保护恰好会被"第 3 次追问"拦掉，在最需要它的时刻失效。
   - **assisted 标记**：**不做不计分**（评分是连续诊断链路的一部分，剔除会打断数据流），改为**标注**：分数照记，报告 `assistance_stats` 披露"全场有多少题是在提示下完成的"。占比过高本身就是诊断信号——说明当前难度/方向与该候选人不匹配。

### 工程化
- **测试**：新增 `tests/test_mock_interviewer_borrowings.py`（50 例，覆盖角色卡完整性/追问 prompt 双自由度/锚点分类与兜底/加减分项各规则与封顶夹紧/JD gap 注入/压力题三道闸门与去重/恢复红线与阈值/assisted 标记与报告统计）；受影响面 326 例全绿，`run.py lint` 分层契约通过。
- **配置**：新增 `JD_GAP_SCORE_THRESHOLD`、`JD_GAP_MAX_ITEMS`、`PRESSURE_QUESTION_ENABLED`、`PRESSURE_MAX_PER_SESSION`、`PRESSURE_PROB_BY_ATTACK_LEVEL`。
- **契约**：`.importlinter` L2 层补登 `output_sanitizer`（此前遗漏）、`resume_anchors`、`pressure_bank`、`score_adjustments`。

### 修复
- `tests/test_weakness_memory.py` 9 例失败修复：`weakness_profile.session_id` 有外键指向 `sessions(id)`，而测试的 `_seed()` 直接写子表未落父记录，导致 `FOREIGN KEY constraint failed`。新增 `_ensure_sessions()` 补齐父记录并开启 `PRAGMA foreign_keys`。属**既有缺陷**（v6.3 长期记忆闭环引入），与本轮改动无关，修复后 17 例全绿。

### 范围与约束（诚实披露）
- **维度映射是近似的**：「表达结构」「应变能力」这类维度在本项目五维体系（宪章约束 3）中没有对应项，故「甩锅」「过度防御」等应变类信号只能就近映射到 STAR 完整度 / 逻辑连贯性，语义上并非严格等价。
- **存在双重惩罚风险**：模型若已因"没有数据"把量化程度打到 3 分，规则再 -1 即构成"模型与规则各扣一次"。缓解手段是封顶机制（非消除），换取的是可解释性；若模型已打到 1 分则夹紧后无额外惩罚。
- **压力题前端标识**：`question` 消息透传 `is_pressure` / `pressure_topic`，前端 `showQuestion` 渲染「⚡ 压力题 · 类别」徽章（红色系但克制——提示"这是一道意外的问题"，不是警告用户答错了）。
- `jd_gaps` 使会话创建多一次 LLM 往返（仅当有 JD 时）。失败静默降级为无缺口模式，不阻断会话创建。

---

## v6.2 迭代专项三期：收尾强控 + 简历追问点 + 输出净化 + 任务级模型绑定 + 报告逐题拆解 + 语音链路（2026-08-28）

> 本轮在协作迭代中定位到六处"能力已具备、工程约束缺失"的缺口并逐项补齐，原则：**只补工程模式，不动技术栈**——不引入桌面壳（本项目定位 Web 服务平台），全双工语音不引入 WebSocket 音频流（MiMo 云端 ASR 为请求-响应协议，改造为流式需自研网关），改为在半双工链路上补齐 VAD 节流与"TTS 结束自动切回文字"这两个体验缺口。新增测试 50 例，全量 **559 例通过**、分层 lint 通过、前端 `vite build` 通过。

### 新增（功能线）

1. **面试状态机 closing 收尾强控**
   - `config`：`INTERVIEW_ROUNDS` 末轮「反问收尾」与 `TRADITIONAL_ROUNDS` 末轮「自定义环节」新增 `closing: True`；新增 `CLOSING_INSTRUCTION`（内部收尾指令）与 `CLOSING_MESSAGE`（收束语文案，工程层确定性输出，不额外消耗 LLM 调用）。
   - `session`：`is_closing_round()`（轮次计数判定：显式 closing 标记或已推进到末轮）+ `closing_instruction()`；**工程强控** —— 收尾阶段 `should_follow_up()` 恒为 False（连"回答过短强制追问"一并强控）、`generate_extra_question()` 恒为 None。
   - `question_gen.generate_round_questions()` 新增 `closing_instruction` 参数并注入出题 prompt；`main.py` 末轮答完推送 `interview_closing` 事件，前端 `showClosingMessage()` 渲染收尾卡片。
   - 价值：收尾不再依赖模型自决，杜绝最后一题被无限追问拖住。

2. **简历解析前置追问点 deepDivePoints / vaguePoints**
   - `resume_parser` 新增 `extract_interview_points(resume_text, llm_client, jd_text)`：简历解析阶段一次性产出「值得深挖的点」（写了但细节不足，需考真伪与深度）与「可疑/模糊的点」（表述含糊、缺时间或量化）；输出经清洗（去空/去重/去列表符/丢弃超长项/每类上限 5 条）；**全流程降级** —— LLM 异常、正文过短（< `MIN_RESUME_CHARS=50`）、无可用线索一律返回 `{}`，不阻断会话创建。
   - 复用链路：`main.create_session` 提取 → `InterviewSession(resume_points=...)` → ① 出题时经 `build_resume_points_block()` 注入 prompt（补强题不注入，避免上下文冲突）；② 经 `_evidence_for()` 并入诊断证据包，使 `follow_up_question` 也有据可依。

3. **Prompt 输出约束 + 工程净化兜底**
   - 新增 L2 模块 `backend/output_sanitizer.py`：
     - `OUTPUT_CONSTRAINTS`（禁 Markdown / 禁括号动作 / 禁垫词开头 / 纯文本平铺 / 术语保留原样），已注入出题、诊断、改写、追问四处 prompt。
     - `sanitize_spoken_text()` 确定性净化：**先去舞台提示再去 Markdown**（关键顺序——若先剥斜体标记，`*停顿*` 只剩"停顿"二字留在正文）；舞台提示支持括号形式 `（微笑）` 与强调形式 `*停顿*`，用动作词表命中，**不误删 `Redis（缓存）` 这类术语括号**；垫词剥离要求后随标点才生效，避免误伤"好问题，值得展开"。
   - 落点：题目 `question/intent`、诊断 `follow_up_question/overall_comment/real_interview_impact`、`rewritten_answer` 全部净化后再进 TTS 与前端渲染。

4. **任务级模型绑定 + 面试禁思考**
   - `config`：新增 `LLM_TASK_MODELS`（`JSON` 环境变量，值支持 `"model"` 或 `"provider:model"`）、任务枚举 `LLM_TASKS`（parse/question/interview/diagnosis/rewrite/report/career/market）、实时链路集合 `REALTIME_TASKS`、`INTERVIEW_DISABLE_REASONING`（默认开）。解析失败/未知任务/未知 provider 一律跳过并告警，向后兼容（不配即无变化）。
   - `llm_client`：新增 `is_reasoning_model()`、`task_candidates(task)`、`resolve_task_model(task)`；`chat/chat_json/chat_stream/chat_stream_async` 新增可选 `task` 参数，内部候选池按任务解析（绑定模型置顶 → 全局池）。实时链路剔除推理类模型；**若剔除后无候选则保留原池并告警**（宁可慢，也不能无候选导致调用直接失败）。
   - 已接入：question / diagnosis / rewrite / interview（追问）/ parse（简历追问点、JD 权重）/ market（Gap、岗位画像）/ career（职业规划）。

5. **报告结构：qaBreakdown + realInterviewImpact + thinkingSeconds**
   - 诊断 prompt 新增 `real_interview_impact` 字段（"这段回答放到真实面试里会发生什么"），`normalize_result()` 透出；模型未产出时由 `report._fallback_impact()` 按"分数 × 思考时长"确定性兜底（措辞明确为规则结论，不伪装成面试官原话）。
   - `thinking_seconds`：前端记录题目/追问展示到提交的秒数（`elapsedSeconds()`），随 `answer` 上报；后端 `_normalize_thinking_seconds()` 规整（非法值/超 600s 归零），写入 `answer_history` 与诊断记录；追问补充**累加**到本题。
   - `report.build_report()` 新增 `qa_breakdown`（逐题：分数/五维/最薄弱维度/评语/真实面试影响/思考时长/风险点/是否含改写）、`thinking_stats`（均值/最大/最小/总时长/采集题数）、`resume_points`；`detailed_qa` 同步补齐同名字段，前端可复用一套渲染。
   - 前端 `report.js` 新增「📊 逐题拆解」与「🔎 简历追问线索」两张卡片。

6. **语音链路：VAD 节流 + TTS 结束自动切回文字**
   - `voice.js` 新增 VAD：`AnalyserNode` 按 100ms 采样 RMS，连续静音 `silenceMs=2500` 且已采集到 ≥ `minSpeechMs=800` 语音 → 自动停录并转写；`maxDurationMs=120000` 硬上限兜底；Key 缺失/浏览器不支持时静默回退为手动停止。自动停止与手动停止共用同一 `stop()`，`cancelled` 标志保证只执行一次。
   - `autoReadQuestion()` 新增 `onEnd` 回调；题目与追问朗读结束后 `refocusAnswerInput()` 聚焦输入框、恢复占位提示，用户始终落回可打字状态（追问此前无自动朗读，本轮补齐）。
   - 说明：二进制音频直透已天然满足（TTS 返回音频 Blob → ObjectURL 直放，ASR 直传音频 Blob，均不经文本中转）；真正的全双工（边说边识别）受限于 MiMo 的请求-响应协议，未改造。

### 工程化
- **测试**：新增 `tests/test_grillmind_borrowings.py`（50 例，覆盖 closing 强控/追问点提取与清洗/净化规则（含术语括号保护与垫词误伤）/任务绑定解析与推理模型剔除/思考时长规整与累加/报告 qaBreakdown 与兜底文案）；全量 **559 例通过**（原 509 + 新增 50），`run.py lint` 分层契约通过，前端 `vite build` 通过。
- **配置**：新增 `LLM_TASK_MODELS`、`INTERVIEW_DISABLE_REASONING` 两个可选环境变量（均默认关闭/向后兼容）。

### 范围与约束
- closing 强控使收尾轮**完全不追问**：反问收尾轮本就不需要追问；传统模式「自定义环节」若用户期望继续深挖，需将该轮 `closing` 置为 False。
- `LLM_TASK_MODELS` 为 opt-in：不配置时所有任务沿用 `LLM_MODEL`，行为与 v6.1 完全一致。绑定模型的 Key 无效时自动回退默认池（不构造必然失败的候选）。
- 思考时长由前端计时上报，可篡改、可因切后台而失真；统计仅用于自我复盘，不参与评分计算。未采集到时长时 `thinking_stats.tracked_count=0`，相关展示自动隐藏。
- VAD 只做"何时停止录音"的节流判断，**不做端点检测**（不裁剪已录音频），因此语义上仍是半双工——这是 MiMo ASR 请求-响应协议下的现实边界。

---

## v6.1 迭代专项二期：ASR 容错评分 + 追问引用原话 + 结束面试口令 + 语音 Provider 抽象/缓存预取 + 报告 HTML 导出（2026-08-28）

> 本轮在协作迭代中补齐五处影响真实可用性的缺口。两条约束贯穿全程：**不引入新的编排框架**——"外部编排框架 + REST 状态机驱动"的核心价值在于"人类语音输入门控下不做全自动 Agent"，本项目 WebSocket 状态机已满足，无需另起一套；**不引入重量级原生依赖**——PDF 报告不用 weasyprint（GTK/Pango 在 Windows 部署成本高），降级为"HTML 打印模板 + 浏览器 Ctrl+P 即 PDF"。新增测试 18 例、受影响面 127 例全绿、分层 lint 通过。

### 新增（功能线）
- **ASR 转写容错评分**：`diagnosis_engine` 新增 `VOICE_TRANSCRIPTION_NOTE`——回答来自语音输入时注入评分 prompt，要求按语义意图理解（"SaaS"→"SARS" 类同音误写不计入专业深度失分、口语停顿词不视为表达混乱、涉及转写误差在评语中注明）。全链路贯通：前端 `answer` 消息新增 `source`（voice/text，`interview.js` 跟踪最近一次输入来源，手动键入自动重置）→ `main.py` WS 解析 `from_voice` → `session.stream_answer()/handle_answer()` 透传 → `_build_diagnostician_system(weights, from_voice)` 注入。
- **追问"引用原话"硬约束**：`DIAGNOSTICIAN_SYSTEM_PROMPT` 追问要求新增"必须显式引用候选人回答里的具体词汇/数字/项目名，严禁套路式追问"；`session.generate_follow_up()` 的独立生成路径同步加约束。
- **结束面试退出口令**：`session.py` 新增 `END_INTERVIEW_KEYWORDS + is_end_signal()`（中英文、大小写不敏感子串匹配，确定性规则不依赖 LLM）；`main.py` WS 在安全检查**之前**检测（口令文本过短会被质量校验拦截），命中后不诊断、不计分，推送 `interview_end_signal` 事件并优雅收束，照常生成部分报告（`user_ended` 标志贯穿三层循环）；前端监听该事件 toast 提示。
- **语音 Provider 协议抽象 + TTS 缓存**：`voice_service` 新增 `TTSProvider/STTProvider`（`runtime_checkable Protocol`）+ `get_tts_provider()/get_stt_provider()` 工厂（`VOICE_TTS_PROVIDER/VOICE_STT_PROVIDER` 配置选择，未知值回退 mimo 并告警）；`VoiceService.synthesize` 新增 **LRU 缓存**（`TTS_CACHE_MAX=32`，仅缓存成功结果，线程安全）——重听题目、追问预取、探测包不再重复付费合成。
- **TTS 预取**：`voice.js` 新增 `prefetchTTS()`（静默失败，不播放），新题/追问到达即后台合成预热缓存，用户点朗读/开自动朗读时零等待；`report.js` 新增「🖨 打印 / 存为 PDF」按钮。
- **复盘报告 HTML 导出**：`main.py` 新增 `GET /api/reports/{session_id}/export.html`——`markdown` 库渲染（tables/fenced_code 扩展）+ 内置打印样式模板（中文字体栈、表格/引用样式、`@media print`），浏览器打开后 Ctrl+P 即得 PDF；依赖新增 `markdown>=3.5`。

### 工程化
- **测试**：新增 `tests/test_offer_master_borrowings.py`（18 例：退出口令/prompt 注入与约束/TTS 缓存命中·音色隔离·LRU 淘汰·失败不缓存/Provider 协议与回退/HTML 导出 404 与渲染）；`test_voice_service` 等既有用例零破坏。

### 范围与约束
- 结束口令仅检测**主回答位**（追问补充位不检测）；命中即收束，当前轮未答题不计入报告。
- 语音 Provider 注册表当前仅 `mimo` 一个实现，工厂为前向接缝（接入火山/豆包等只需登记实现类）。
- TTS 缓存按"文本+音色"为键，命中依赖文本完全一致；`MIMO_TTS_STYLE` 变更不会使缓存失效（风格仅影响首条 user 消息，实际可忽略）。

---

## v6.0 迭代专项：Prompt 硬约束 + 评分同轮三态决策 + JSON 四级容错 + Provider 自动探测 + 命名空间知识库 + 音色映射表（2026-08-28）

> 本轮在协作迭代中集中补齐六处"依赖模型自觉、缺工程兜底"的缺口。原则：**只补工程模式，不引入托管依赖**——向量检索按"零托管依赖"宪章降为本地关键词实现；市场数据实时性、真实流式、语音实时性三项此前已具备，不在本轮范围。全量测试 491 例全绿、分层 lint 通过。

### 新增（功能线）
- **出题/诊断 Prompt 硬约束**：`question_gen.get_question_gen_system_prompt()` 新增 4 条约束——只出题不替答、`question_type` 枚举（knowledge/project/behavior）、easy→mid→hard 难度递进、5-8 轮整场意识；`DIAGNOSTICIAN_SYSTEM_PROMPT` 补"连续追问不得超过 2 次"（与 `FOLLOW_UP_MAX_COUNT=2` 双保险）。
- **评分同轮三态决策**：Diagnostician JSON schema 新增 `next_action`（`follow_up` / `next_question` / `complete`），评分与"追问/推进/收束"一次调用产出；`normalize_result()` 规整三态（非法值由追问文本推导，空值交会话层兜底）；`session.should_follow_up()` 采信模型推进决策——`next_question/complete` 且无追问文本时低分不再强制追问，但**回答过短仍强制追问**（防敷衍被放行），未声明时走原阈值规则（向后兼容）。
- **JSON 四级容错提取**：`llm_client.safe_json_extract()`——L1 直接解析 → L2 字符串感知提取配平 `{}` 块（兼容围栏/前后缀文本）→ L3 字符级修复（字符串内裸换行/未转义引号启发式判定/截断补闭合引号与括号）→ L4 宽松解析（尾逗号/值位单引号/True-False-None-undefined 字面量），并规避 `it's` 类正文撇号误伤。`chat_json` 的候选可用性判定与最终解析均走四级容错（轻微畸形输出就地修复，不再浪费一次 fallback 候选）；`diagnosis_engine._extract_json` 委托同源实现。
- **Provider 注册表自动探测**：`validate_api_key` 下沉 `config`（`llm_client._api_key_issue` 保留别名兼容测试）；新增 `AI_PROVIDER=auto`——按 `AI_PROVIDERS` 注册顺序探测第一个 Key 有效的后端，未知值回退 deepseek；`LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_FALLBACK_CHAIN` 全部跟随 `AI_PROVIDER_RESOLVED` 解析；`switch_provider` 支持 `auto` 并在目标 Key 无效时告警。默认值 `deepseek` 不变，零行为破坏。
- **命名空间知识库**：新增 L2 模块 `backend/knowledge_store.py`——`rag:interview / rag:career / rag:resume` 命名空间隔离，复用 `resume_retriever` 分块 + 关键词加权评分（零第三方检索依赖），`augment_prompt()` 把检索块以【参考知识库相关内容】注入 System Prompt（附反幻觉约束，与简历证据包同一口径）；已纳入 `.importlinter` L2 契约（顺带补上此前遗漏的 `voice_service` 与 `resume_retriever` 契约登记）。
- **音色别名映射表**：`voice_service.VOICE_ALIASES`——OpenAI 风格音色（alloy/echo/fable/onyx/nova/shimmer）与性别简称（male/female）统一映射到 MiMo 预置音色；解析顺序 = 预置音色 → 别名（大小写不敏感）→ 配置默认音色。

### 工程化
- **测试**：新增 `test_json_utils`（19 例）/ `test_knowledge_store`（14 例）/ `test_provider_registry`（18 例，chat_json 容错用例直接替换 `_candidates` 为 mock 候选，**绝不发起真实网络请求**）/ `test_prompt_constraints`（2 例），扩展 `test_session`（next_action 决策 1 例）/ `test_diagnosis_engine`（三态规整 4 例）/ `test_voice_service`（音色别名 4 例），共 62 例；全量 **491 例通过**。
- **配置**：`.env.example` 新增 `AI_PROVIDER=auto` 说明。

### 修复
- `.importlinter` L2 契约清单滞后：v5.0 的 `resume_retriever`、v4.2 的 `voice_service` 未登记（因不在契约内而未被 lint 检查），本轮补齐并新增 `knowledge_store`。
- 测试副产物修复：新增的 `chat_json` 容错测试最初 mock 打在 `self.client` 上，而 `_call_with_fallback` 走候选池 `cand.client`，导致测试发起**真实 API 调用**（消耗配额）；改为整体替换 `_candidates` 为 mock 候选，从机制上杜绝。

### 范围与约束
- `next_action` 采信模型推进决策存在"模型误判放行"风险：已用"回答过短仍强制追问"硬兜底 + 未声明时回退阈值规则，且 `FOLLOW_UP_MAX_COUNT=2` 上限不受影响。
- `KnowledgeStore` 为**本地关键词检索**（非向量）：同义/模糊表述可能漏命中，适合知识条目 < 数千条的原型规模；当前为 L2 通用能力，尚未接入任何业务流（简历证据包仍走 `ResumeRetriever`），属前向储备。
- `AI_PROVIDER=auto` 为**选择加入**（opt-in），显式指定后端时行为与 v5.0 完全一致。

---

## v5.0 简历证据检索 + 不会答恢复 + 薄弱点累计 + 会话中多模式切换（2026-08-28）

> 本轮在协作迭代中补齐三块硬短板：(1) **简历证据检索**——新增 `resume_retriever.py` 轻量检索器，为追问与诊断实时产出「本轮证据包」，并用证据硬规则约束诊断模型**只依据简历证据或候选人亲述评价**、严禁编造经历，从机制上杜绝"AI 凭空捏造候选人做过的事"；(2) **不会答恢复**——检测到候选人示弱（不会/不懂/没思路…）时切换辅导式引导，而非机械继续拷打；(3) **薄弱点跨轮累计**——把各轮诊断的薄弱标签跨轮聚合，实时面板 + 报告沉淀「今日弱点」。另支持会话中动态切换模式/阶段（simulation / traditional / coach / hardcore / interview_only × phone_screen / tech_round_1 / tech_round_2 / hr）。新增/重写测试 61 例（session 状态机 + resume_retriever），分层 lint 通过。

### 新增（功能线）
- **简历证据检索器（`resume_retriever.py`，L2）**：本地关键词 + 文件名优先级加权（`FILE_PRIORITY`，`score = priority + 命中词数×8`），无向量库/无托管依赖；`_chunk_text` 按 `CHUNK_SIZE=2000` 分块、`CHUNK_OVERLAP=250` 保相邻块语义；`_score_chunks` 仅在前 `SEARCH_HEAD_CHARS=800` 字符内匹配，且**只选命中≥1 关键词的块**（修复"无命中块也当选证据"缺陷）；`select_context` 施加单源 `MAX_CHUNKS_PER_SOURCE=2` / 总块数 `MAX_CONTEXT_CHUNKS=4` / 总字符 `MAX_CONTEXT_CHARS=6000` 三重硬预算防 token 膨胀；单文档纳入 `MAX_CHARS_PER_FILE=120_000`；无证据返回 `_NO_EVIDENCE_MESSAGE` 兜底；`trace_retrieval()` 逐块溯源（chunk_id/source/matched_terms/score/selected/reason）。
- **诊断注入证据包 + 证据硬规则**：`diagnosis_engine` 的 `diagnose()/stream()/run_diagnosis*()` 新增 `evidence_package` / `mode` / `recovery_requested` 参数；新增 `EVIDENCE_USE_HARD_RULES`（只能依据证据或亲述评价、严禁编造、证据不足需明确澄清式追问、与简历矛盾需指出）、`COACHING_RECOVERY_INSTRUCTION`（不会答恢复）、`_MODE_INSTRUCTIONS`（五模式指令）、`WEAKNESS_KEYWORDS + _extract_weakness_tags`（薄弱点标签提取，限 6 个）；`normalize_result()` 新增返回 `weakness_tags`。
- **会话状态机（`interview_engine/session.py`）**：`UNCERTAIN_ANSWER_MARKERS + needs_recovery()` 检测不会答信号；`_evidence_for()` 惰性构建 `ResumeRetriever` 生成证据包；`accumulate_weaknesses()/weakness_payload()` 跨轮累计薄弱点（返回 `tags/counts/recovery_active`）；`switch_mode(mode, stage)` 会话中切模式/阶段（切 `traditional` 于下一轮重建轮次结构）；`advance_round()` 在 `mode_changed` 时按新模式重建轮次；`stream_answer()/handle_answer()` 注入证据/模式/恢复信号。
- **多模式/多阶段协议**：`schemas.py` 新增 `InterviewMode`（simulation/traditional/coach/hardcore/interview_only）与 `InterviewStage`（phone_screen/tech_round_1/tech_round_2/hr）枚举；`SessionCreateRequest` 新增 `mode`/`stage`；新增 `ModeSwitchRequest/ModeSwitchResponse` 响应模型；`DiagnosisResult` 新增 `weakness_tags`。
- **后端端点**：HTTP `POST /api/interview/{session_id}/mode`（`switch_interview_mode`）；WS `/ws/interview/{session_id}` 新增 `switch_mode` 消息、`mode_change` 事件、`weakness_update` 事件（每题诊断后推送）、`interviewer_info` 含 `stage`。
- **报告沉淀**：`report.py` 新增 `detailed_qa`（逐题标准答案，含 rewritten_answer/key_changes/weakness_tags，修复"参考答案恒为空"缺陷）与 `weakness_tag_summary`（跨轮薄弱点标签）；`generate_review_markdown()` 新增「薄弱点标签（跨轮累计）」章节。
- **前端**：`interview.js` 新增 🔥拷打/🤐只面试两个模式卡片、会话中模式下拉切换、`weakness_update` →「⚠️ 薄弱点（跨轮累计）」面板 + `recovery-banner`「🛟 已进入不会答恢复辅导」、`mode_change` 徽章刷新、侧栏模式+阶段徽章；`report.js` 新增「🏷 薄弱点标签（跨轮累计）」标签云。

### 修复
- `resume_retriever.py` 初始化顺序：`_chunk_id` 在 `add_document()` 之后才赋值导致分块抛 `AttributeError`（改为先初始化）。
- `resume_retriever.py` 命中过滤：无关键词命中的块也会凭 priority 入选，与"无匹配返回兜底提示"语义冲突（改为仅选命中块）。
- `tests/test_session.py` 重写：旧草稿按臆测接口断言（`market_keyword`/`current_round_index`/四维 technical_depth），与 v5.0 实际实现完全脱节、必挂；重写为对齐真实接口（含五维 `professional_depth`、`config` 单例常量、`switch_mode` 事件、证据/恢复/薄弱点等 v5.0 能力）的可用测试。
- `llm_client.py` 模块级全局单例导入即崩溃：`.env` 的 `LLM_FALLBACK_CHAIN` 含未配置 key 的备用 provider（如 `qwen:qwen-plus` 但 `QWEN_API_KEY` 为空）时，`_init_client` 在构建 fallback 候选 `OpenAI(api_key="")` 直接抛 `OpenAIError`，导致所有 import 它的测试在 collection 阶段失败（4 个 LLM/环境类测试无法收集）。修复：fallback 候选构建时对 key 做 `_api_key_issue` 校验，**无效 key 的候选直接跳过**（符合 fallback「备用缺失应降级而非致命」语义），主候选不受影响。修复后整套测试（含 LLM 类）438 例全绿。

### 工程化
- **测试**：新增 `tests/test_resume_retriever.py`（分块/命中/预算/溯源/证据包共 12 例）+ 重写 `tests/test_session.py`（状态机/追问/权重/轮次/薄弱点/恢复/多模式共 49 例），共 61 例；完整套件约 438 例（含依赖 API Key 的 `test_career_planner`/`test_gap_analyzer`/`test_llm_client`/`test_llm_fallback`），本机缺 Key 时其中 4 个 LLM/环境类测试无法收集、其余通过。

### 范围与约束
- 检索为**本地关键词启发式**，非语义向量检索：中文分词粒度受限，同义/模糊表述可能漏命中；仅作证据提示，不替代向量库。可调参数目前为代码级常量（`resume_retriever.py`），未下沉 `.env`。
- 证据硬规则依赖 `evidence_package` 注入，仅约束诊断/追问阶段；**前端参考答案沉淀面板（`detailed_qa`）尚未渲染**，报告已产出字段，属前后端待对齐项。
- 会话中切换 `traditional` 需下一轮生效；模拟模式内部（simulation/coach/hardcore/interview_only）可即时切换。

## v4.3 模型调用优雅降级（fallback）（2026-08-28）

> 在 L1 基础设施 `LLMClient` 新增配置驱动的模型 fallback 降级链：主模型调用失败（异常/限流/超时/返回不可用内容）时按 `LLM_FALLBACK_CHAIN` 自动切换备用 provider:model，覆盖非流式与流式（WebSocket 主流程）；调用方零改动，全局单例语义不变。新增 11 例 fallback 单测，分层 lint 通过。

### 新增（功能线）
- **fallback 候选池**：`llm_client.py._init_client` 按 `LLM_FALLBACK_CHAIN` 预构建有序候选（各自独立 api_key/base_url/model），主候选（当前 provider/model）始终在首位；`LLM_FALLBACK_MAX_RETRIES` 限制最大尝试数。
- **降级包装器**：新增 `_call_with_fallback`（非流式，含 `success_pred` 软失败判定，JSON 解析失败自动重试下一候选）与 `_stream_with_fallback`（异步流式：`yield` 前失败无缝切换、已产出半截则停止并报错不拼接）。
- **调用方零改动**：`chat / chat_json / chat_stream / chat_stream_async` 签名不变、内部自动 fallback；`question_gen / diagnosis_engine / career_planner / gap_analyzer / dimension_weights / web_research` 等全部汇聚到 `LLMClient` 的模块自动获得降级（不含 v4.2 MiMo 语音，其走独立降级通道）。
- **配置**：`config.py` 新增 `LLM_FALLBACK_CHAIN` / `LLM_FALLBACK_MAX_RETRIES`；`.env.example` 新增 fallback 配置块。

### 工程化
- **测试**：新增 `tests/test_llm_fallback.py`（非流式/流式/配置解析共 11 例）；LLM 相关测试 18 例通过。
- **可观测**：`get_provider_info` 暴露 `fallback_count`；fallback 命中与软失败均有日志标注。

### 范围与约束
- 单候选（未配置 `LLM_FALLBACK_CHAIN`）行为完全退化为现状，向后兼容。
- fallback 不改变双 Agent 诊断客观性（评分与改写仍按既定顺序/prompt 隔离），仅解决单点 provider 故障；需为备用 provider 配置独立密钥方可生效。

## v4.2 小米 MiMo 云端语音接入（2026-08-28）

> 将面试语音交互从"浏览器原生 Web Speech API"升级为"**MiMo 云端语音优先 + 浏览器原生降级**"双引擎：TTS 朗读用 mimo-v2.5-tts，语音输入用 mimo-v2.5-asr（MediaRecorder 录音上传）。**诊断内核零变更**，语音仍是输入/输出替代层；320 测试全绿（新增 29 例）、分层 lint 通过。

### 新增（功能线）
- **后端语音代理**：`backend/voice_service.py`（L2/L3）封装 MiMo 官方 `chat/completions` 协议（认证头 `api-key`）；`config.py` 新增 `MIMO_API_KEY / MIMO_BASE_URL / MIMO_TTS_MODEL / MIMO_ASR_MODEL / MIMO_TTS_VOICE / MIMO_TTS_STYLE / MIMO_ASR_LANGUAGE / MIMO_TIMEOUT / RATE_LIMIT_VOICE`；新增路由 `POST /api/voice/tts`（文本→合成音频 Base64）与 `POST /api/voice/asr`（上传音频→转写文本），密钥仅存后端 .env。
- **前端双引擎**（`frontend/src/js/voice.js`）：`voiceSupport.mimo` 能力检测 + `probeMimo()` 后台探测；`speak()` 改为 MiMo 优先、失败自动降级 `speechSynthesis`；新增 MediaRecorder 录音采集（`startRecording/stopRecording`）与 `transcribeRecording()` 上传 ASR；新增 `voiceFillWithASR()`（录音→识别→填入回答）。
- **语音对话链路**（`interview.js`）：主回答区与追问区麦克风改用 MiMo ASR 优先；按钮显示条件放宽为"STT 或录音都可用"；新增 `processing` 状态与语音引擎角标（MiMo / 浏览器降级）。
- **api.js**：新增 `requestVoiceTTS / requestVoiceASR` 接口。

### 工程化
- **依赖**：`httpx` 从测试段移入生产依赖（运行时语音代理所需）。
- **环境变量**：`.env.example` 新增 MiMo 配置块（不配置则自动降级浏览器原生语音，功能不中断）。
- **测试**：新增 `test_voice_service.py`（key 校验/音色映射/错误处理/超时/mock 调用）与 `test_voice_api.py`（路由降级/400/成功/失败路径），共 29 例；全量 320 用例通过。

### 范围与约束
- **MiMo-Audio 7B 开源模型不采用**：需 NVIDIA GPU≥24G + Linux，当前 Windows 环境不可行；选用云端 API（MiMo-V2.5-TTS 限时免费，ASR 0.5 元/小时）。
- 语音仍作为输入/输出替代层，**不参与诊断内核**（与 CHARTER.md v2.3 定位一致）。
- 未配 Key / 网络失败 / 超时 / 限流均自动降级浏览器原生语音，功能不中断。

### 修复（v4.2 协议对齐，真实 Key 实测）
- **问题**：首版按 OpenAI `/audio/speech`、`/audio/transcriptions` 协议编写，域名误用 `api.mimo.ai`，与 MiMo 官方协议不符，配置 Key 后调用失败（SSL/404）。
- **修正**（以 mimo.mi.com 官方文档与开源实现 ppy-web/tts-mimo 核实为准）：
  - 端点统一为 `POST {base}/chat/completions`（TTS/ASR 均如此）；认证头 `api-key`（非 Bearer）。
  - 域名改为 `https://api.xiaomimimo.com/v1`（sk- 按量付费集群）；模型名统一小写 `mimo-v2.5-tts` / `mimo-v2.5-asr`。
  - TTS 请求体 `messages[user=风格提示, assistant=待朗读文本] + audio{format:wav, voice}`；响应解析 `choices[0].message.audio.data`（Base64 WAV，兼容 data URL 前缀）。
  - ASR 请求体 `messages[user.content[0].input_audio.data=音频 data URL] + asr_options{language}`；响应解析 `choices[0].message.content`（兼容字符串与 `[{"text":...}]` 列表）。
  - 新增 `MIMO_TTS_VOICE`（默认冰糖）/ `MIMO_TTS_STYLE` / `MIMO_ASR_LANGUAGE`；非法音色名自动映射默认音色。
- **端到端实测（真实 Key）**：TTS 合成成功，返回 WAV 校验头 `RIFF/WAVE/fmt` 正确；ASR 协议链路正确（服务器返回 402 余额不足，属账户计费问题而非协议错误，充值后可用；前端失败自动降级浏览器 STT，不阻塞）。

---

## v4.1 市场数据 Tab：B 档内嵌实时采集（2026-08-27）

> 按用户定案 B 档（子模块内嵌），将既有采集项目的 Playwright 采集核心整合进本系统，新增第 6 个"市场数据"Tab，沿用「纸墨印章」设计语言（米色纸张 + 衬线 + 印章红）。**后端其余契约零变更**；291 测试全绿、分层 lint 通过。

### 新增（功能线）
- **实时采集**：关键词 + 省份→城市级联多选（≤5 城市）+ 排序（相关性/最新发布）+ 页数 1~5；后台线程执行 `scrape_jobs()`，前端 1.5s 轮询进度（当前城市/页数/累计条数/进度条）；采集结果经 `adapters.to_standard_job()` 直通 `store.upsert_jobs()` 回灌 `market.db`。
- **岗位库**：统计概览（岗位总量/平均薪资/热门技能 TOP5/样本城市）+ 筛选（关键词/城市/学历/薪资区间）+ 纸感表格（编号角标/悬停浮起/行勾选）+ 分页。
- **岗位详情**：全屏独立视图（沿用既有岗位详情页结构），展示完整描述/标签/薪资/经验/学历/发布时间，**支持跳转 51job 原文**，可一键用本岗位做 Gap 分析。
- **岗位分析**：单选 Gap 分析（复用 `/api/gap-analysis`，含市场基准注入）；多选 2~5 个跨岗位对比（复用 `/api/cross-job-compare`，排名卡 + 风险等级）；简历文本可一键复用面试 Tab 内容。
- **两套 UI 风格自由切换**：浅色公文风（米纸墨印）↔ 深色 SaaS 风（深墨底），顶部语义色切换器（青/粉/金/紫），localStorage 记忆；作用域严格限定 `#market-panel`，不影响其余 Tab 的 Indigo 设计体系。

### 工程化
- **crawler 子包**（`backend/market/crawler/`，随 `backend.market` 同属 L2，不越层）：`python_job_scraper.py`（相对导入改造、删 `__main__`、日志改名）+ `salary_parser.py` + `adapters.py`（字段映射/JD 组装）+ `tasks.py`（线程安全任务表、单实例互斥、TTL 10 分钟惰性清理）。
- **新路由**：`POST /api/market/crawl`（Form 校验 + `3/minute` 限流）、`GET /api/market/crawl/status/{task_id}`、`GET /api/market/city-map`（省份→城市级联数据源，复用 scraper 的 388 城市表）、`GET /api/market/jobs/{job_id}`（岗位详情 + 组装 JD 文本供 Gap 分析）。
- **依赖**：新增 `playwright>=1.40`、`playwright-stealth`；README 补充 `playwright install chromium` 安装步骤；未安装 playwright 时路由返回明确错误与安装指引。

### 治理
- **决策记录卡 DC-04**（CHARTER.md）：推翻 DC-02"不再用 Playwright 采集"决策，改以 B 档内嵌方式整合采集核心，以真实采集工作量补足"数据资产≠代码复现"缺陷；`data.db` 导入管道保留兜底，两者并存。
- **测试**：新增 `test_market_crawler_adapters.py`（字段映射/薪资解析/描述截断/JD 组装）与 `test_market_crawler_tasks.py`（参数校验/单实例互斥/状态机/TTL 清理），共 23 个用例；全量 291 用例通过，`python run.py lint` 分层契约通过。

---

## v4.0 前端 UIUX 重构落地（2026-08-27）

> 按 v3.3 方案（`docs/前端设计方案_UIUX重构.md`）分 5 阶段实施完毕。**后端契约除历史详情端点外零变更**；268 测试全绿。

### 工程化（阶段 1-2）
- **Vite 5 构建**：`npm run dev`（:5173 代理 `/api` `/ws` `/upload` → :8000）开发 / `npm run build` 产出 `dist/` 由 FastAPI 托管；Chart.js 转 npm 依赖。
- **Design Tokens 四层拆分**：`tokens.css`（语义 Token + 深色预留）/ `base.css`（reset+排版）/ `components.css`（框架组件）/ `pages/*.css`（领域样式）。新视觉系统：Indigo 品牌主色 + Slate 中性 + 琥珀点缀（仅鼓励/里程碑/成长）。
- **导航三态自适应**：桌面左垂直导航 / 平板图标栏 / 移动端底部 Tab。

### 核心体验重构（阶段 3）
- **Setup 三步引导**：简历与岗位 → 面试偏好（模式/自我介绍）→ 题型与风格；右侧实时配置摘要卡，含步骤切换即时校验、一键均衡题型。
- **Session 双栏工作台**：左侧对话流 + 右侧固定诊断面板（阶段进度/维度权重/实时雷达）；回答输入条 sticky 浮起，始终可见。
- **Diagnosis 复盘态**：ScoreRing 环形总分 Hero + 五维条形图 + 最弱维度高亮徽章 + 原文/示范改写对照 + 回答风险点列表。
- **动效**：对话流卡片 fade-up 进场（消息逐条天然 stagger）、弱项脉冲、环形填充过渡、tag 呼吸动画。

### 其余模块重构（阶段 4）
- **报告 Dashboard**：环形总分 Hero + 关键指标条（轮数/已答/强项/待提升）+ 雷达图与轮次时间线双栏。
- **历史**：列表项增强（风格/状态/JD 徽章 + 评分跳转）；新增**详情抽屉**（问答记录逐题评分 + 综合评分 + 轮次汇总）。修复 `GET /api/sessions/{id}` 仅返回 session 导致详情实际不可用的缺陷（现附带 `qas` + `report`）。
- **题库**：新建/编辑由行内表单改为**居中 Modal**，删除遗留的 `editingId` 行内编辑状态机。
- **职业规划**：沿用 v3.2 时间轴/技能曲线，纳入新布局。

### 打磨（阶段 5）
- **深色主题**：跟随系统 `prefers-color-scheme`，变量层覆盖 + `pages/dark.css` 组件级微调（Hero 渐变/徽章/时间线/表单焦点环等）。
- **无障碍**：`focus-visible` 焦点环、`prefers-reduced-motion` 动效降级、ScoreRing/Drawer/Modal `role/aria` 语义。
- **验证**：前端构建零错误、lint 零告警、268 测试全绿（含新增详情端点断言）。

---

## v3.3 前端设计方案评审稿（2026-08-27）

> 详见 `docs/前端设计方案_UIUX重构.md`。本轮为**方案评审稿**：只产出设计文档，不修改代码；评审确认后按文档第 10 章分阶段实施。

- **设计定调**：现代专业·简洁留白（Indigo 品牌延续）+ 教练式温暖（暖琥珀点缀）+ 克制 AI 反馈（流式/光晕仅用于状态表达）。依据：高压求职场景需要专业可信与焦虑安抚并存。
- **信息架构**：5 功能模块按"准备→实战→复盘→规划"用户旅程重组；导航从顶部 Tab 改为左垂直导航，桌面 220px / 平板图标栏 / 移动底部 Tab 三态自适应。
- **视觉系统**：Design Tokens 四层拆分（tokens / base / components / pages），替代单文件 style.css（1061 行）；新增 Indigo/Slate/琥珀阶梯与三级卡片层次（白卡/浅底卡/描边卡）。
- **组件体系**：基础 / 数据 / 领域 / 状态四类组件规范 + 四态设计（空/载/成/错），核心领域组件（ScoreRing / StreamBox / DiagnosisCard / RadarCard 等）给出交互规格。
- **工程化**：引入 Vite 5（用户批准）+ Chart.js 转 npm 依赖；开发态 `dev-front`（:5173 代理 `/api` `/ws` `/upload` → :8000），生产态 `dist/` 由 FastAPI 托管；迁移阶段零 UI 变更、逐阶段验收。
- **实施路线**：5 阶段（Vite 迁移 → Token 与全局框架 → 核心体验重构 → 其余模块 → 动效/响应式/无障碍打磨），每阶段含交付物与验收标准，后端契约全程零变更。
- **范围边界**：深色模式、用户认证、云端语音、PDF 导出本期不做（Token 预留 `data-theme` 扩展位）。

---

## v3.2 宪章治理 + 职业规划补全（2026-08-13）

> 详见 `docs/week7_诚实披露与代码整改_需求.md` 及其后续决议。本轮两条主线：

### 宪章治理
- **CODEBUDDY.md 拆分为三份**：CHARTER.md（不变硬约束）+ CHANGELOG.md（版本叙事）+ CODEBUDDY.md（索引入口）。解决"宪章与变更日志混写导致硬约束淹没在版本叙事中"的问题。
- **import-linter 工具强制分层**：新增 `.importlinter` 契约文件（L1-L4），以 `python run.py lint`（= `PYTHONUTF8=1 python -m importlinter.cli lint`）确定性检查所有 import 越层，取代"随机抽查 2-3 条"的文字纪律。踩坑记录：裸 `python -m importlinter` 只打印帮助不执行检查（假阳性 RC=0）；Windows 下不设 PYTHONUTF8 时 grimp 按 GBK 读 UTF-8 源码崩溃漏检。
- **分层契约按代码现状校准**：`market/*` 从 L3 调整为 L2（`gap_analyzer` 已依赖它做市场基准注入，否则构成 L2→L3 越层）。
- **决策记录卡机制**：CHARTER.md 新增强制决策记录卡模板，并补写 3 张决策卡：DC-01 双 Agent 不可合并（补录论证依据）、DC-02 推翻不复用约束（v3.0 决策复盘）、DC-03 补建职业规划功能线（v3.2）。取代"事后从对话提炼批判性思维信号"的注水机制。

### 职业规划功能线（补齐产品命题）
- **修复缺口**：产品全名"AI 模拟面试官**与职业规划**"后半段长期未落地（全文搜索仅命中出题提示词两处）。本轮补建真正的时间轴路径规划模块，而非横截面打分。
- **`backend/career_planner.py`（L3 新增）**：`plan_career()` 以 `gap_analyzer.analyze_gap()` 六维快照为现状基线，调用 LLM 做多步路径推理，输出结构化 `CareerPlanResponse`（多阶段时间轴：阶段/需补技能/里程碑/岗位跃迁/顺序理由）。
- **`backend/schemas.py`**：新增 `CareerStage` / `CareerPlanRequest` / `CareerPlanResponse` Pydantic 模型。
- **`backend/main.py`**：新增 `POST /api/career-plan`（限流 `RATE_LIMIT_CAREER`，默认 10/分钟），错误统一转 `HTTPException(500)`。
- **前端**：新增"职业规划"Tab（`careerPlan.js`），竖向时间轴 + 阶段卡片 + 现状基线六维横条 + 技能进度 Chart.js 图 + 总结/风险徽章。
- **测试**：`test_schemas.py` 新增 CareerPlan 模型约束校验；`test_api.py` 新增 `/api/career-plan` 集成测试（mock LLM）。
- **已知局限新增**：职业规划路径推理稳定性未经 A/B 验证（见 CHARTER.md 已知局限）。

---

## v3.1 工程加固（2026-08）

> 缺陷修复 (#5)：此前无文件持久化，出问题无法追溯历史。详见 `docs/week6_*_需求.md`。

### 集中日志配置（logger.py）
- `RotatingFileHandler`：单文件 5MB，保留 3 个备份 → `data/app.log`
- 控制台同格式输出（开发时可实时查看）
- 抑制第三方库噪讯（httpx/httpcore/websockets/asyncio urllib3）
- `main.py` 入口处调用 `setup_logging()`，其余模块沿用 `logging.getLogger(__name__)`
- `run.py` 的 `print()` 替换为 `logging.info/warning`
- `.env.example` 新增 `LOG_LEVEL`/`LOG_FILE`/`LOG_MAX_BYTES`/`LOG_BACKUP_COUNT`

### Gap 分析（gap_analyzer.py）[v3.1 NEW]
简历-岗位六维度透明匹配评分（缺陷修复 #2）：
1. **技能匹配** (35%) — 技能栈 vs JD 需求
2. **城市/地点** (15%) — 期望城市 vs 岗位所在地
3. **学历匹配** (15%) — 学历层次 vs 岗位要求
4. **经验年限** (15%) — 工作经历 vs 岗位年限
5. **薪资预期** (10%) — 期望 vs 市场范围
6. **可信度** (10%) — 简历信息一致性

**市场基准交叉参考**：当 market.db 有对应岗位数据时，自动注入薪资分位、学历分布、热门技能作为"你在这个市场中的位置"参照。

- API: `POST /api/gap-analysis`（免 session）、`GET /api/gap-analysis/{session_id}`
- 面试报告页自动展示，六维度横条 + 风险等级 + 补强建议
- DB: `sessions` 表新增 `resume_text` 列（迁移兼容旧库）

### 自动化测试（tests/）[v3.1 NEW]
缺陷修复 #4：50 个测试用例覆盖核心路径。

```bash
pytest tests/ -v
pytest tests/ --cov=backend --cov-report=term-missing  # 覆盖率报告
```

测试结构：
- `tests/conftest.py` — 共享 fixtures（App/DB/测试数据）
- `tests/test_schemas.py` — Pydantic 模型字段约束验证（11 测试，含跨岗位对比）
- `tests/test_gap_analyzer.py` — 维度规范化 / 加权计分 / 降级 / 关键词提取（21 测试）
- `tests/test_api.py` — HTTP 路由集成测试（18 测试）：基础/会话/Gap/市场/题库/反馈/安全限流/预热

**修复的既有缺陷**：
- `resume_parser.py`：内联文本（str）传参时原代码仍调用 `.decode()` 导致崩溃 → 加 `isinstance(file_bytes, str)` 短路返回
- `db.py`：`:memory:` 模式下 `os.makedirs("")` 在 Windows 报错 → 加空目录跳过

### Web 层加固（#6）[v3.1 NEW]
基于既有采集项目的安全实践补充：
- **slowapi 频率限制**：全局 100/分钟，上传 10/分钟，Gap 分析 20/分钟，岗位研究 10/分钟，市场导入 5/分钟，预热 1/分钟
- **安全响应头**：x-content-type-options / x-frame-options / x-xss-protection / referrer-policy
- **请求体限制**：上传 10MB，普通请求 1MB，防止大包攻击
- 新增 6 个安全测试用例（`TestSecurityMeasures`）

### JD 权重缓存（#7）[v3.1 NEW]
- 新增 `jd_weights_cache` 表，以 JD 文本的 SHA256 作为主键
- `analyze_jd_weights()` 流程：查缓存 → 命中则直接返回（source="cache"）→ 未命中才调 LLM → 写入缓存
- 避免同一 JD 重复调用 LLM 分析权重，减少 token 消耗和响应延迟

### 数据预热（#8）[v3.1 NEW]
- `POST /api/warmup`（1/分钟限流）：收集历史会话中所有不重复的 JD 文本
- 对未缓存的 JD 逐一调用 `analyze_jd_weights()` 预计算维度权重
- 返回 `{precomputed, skipped, total_jds}` 统计信息

### 分层依赖约束（#9）[v3.1 NEW]
在架构约束章节中明确 L1-L4 逻辑分层及导入方向规则（v3.2 起升级为 import-linter 工具强制，见上）。

### 市场数据注入出题（#10）[v3.1 NEW]
- `question_gen.py` 新增 `_extract_keyword_from_text()` + `_build_market_context_block()`
- 查 market.db 获取该岗位的市场数据（热门技能、常见公司、学历分布、薪资范围）
- 作为 `market_block` 注入各阶段/轮次出题的 user prompt，使题目更贴近真实市场

### 跨岗位对比（#11）[v3.1 NEW]
- 新增 `POST /api/cross-job-compare`（5/分钟限流）：一份简历同时对比多个 JD
- 并行 Gap 分析每个 JD，按 overall_score 排名，自动生成择岗建议
- 前端：报告页动态表单 + 柱状图 + 排名列表 + 各岗位补强建议

### Gap 分析市场基准参照（#12）[v3.1 NEW]
- `schemas.py` 新增 `MarketReference` 模型：keyword / 样本数 / 平均薪资 / 热门技能 / 城市分布 / 学历分布
- `gap_analyzer.py` 新增 `_build_market_reference()`，当 market.db 有匹配数据时自动注入
- 前端报告页渲染"市场参照"卡片，展示"你在这个市场中的位置"

---

## v3.0 市场数据层深度改造（2026-08）

> 详见 `docs/week5_v3数据层_需求.md`

### 推翻"不复用约束"
原决策"不能复用 job-crawler data.db"被推翻：导入数据资产不等于复现代码，Playwright 重复采集纯粹浪费。（决策复盘见 CHARTER.md DC-02）

### 数据管道：job-crawler → market.db
```
job-crawler data.db → importer.py (字段映射) → store.upsert_jobs() → market.db
```
- `importer.py`：读取 job-crawler `data.db`，字段映射后批量写入 `market.db`
- `service.py`：简化，只保留 `import_and_store()` + `find_relevant_snapshot()`
- `config.py`：`IMPORT_TOKEN/RATE/MAX_PAGES` → `JOB_CRAWLER_DB_PATH`
- `main.py`：`POST /api/market/import` 简化为同步端点
- `requirements.txt`：移除 `playwright>=1.44.0`、`playwright-stealth>=1.0.6` (~200MB)
- 删除 `collector.py`

---

## v2.6 深化诊断核心（2026-07）

> 详见 `docs/week4_深化诊断核心_需求.md`。本次不新增功能面，而是纵向加深核心诊断能力。

### 诊断维度权重按 JD 动态化（dimension_weights.py）
- **维度数量由架构约束定义**（见 CHARTER.md），此模块只调整各维度的**权重**
- `analyze_jd_weights()` 用 LLM 分析 JD → 输出五维权重 + 理由
- 权重裁剪到 `[0.10, 0.40]` 并归一化到和为 1.0；任何失败路径退化等权
- 贯穿全链路：注入 Diagnostician/Rewriter Prompt → 加权 `overall_score` → 轮次推进判定 → 报告总分 → 前端权重条
- WebSocket 建立后推送 `dimension_weights` 事件

### 追问与诊断流式合并
- WebSocket 主流程改用 `run_diagnosis_streaming()`（此前已实现但从未接入）
- Diagnostician 输出 JSON 新增 `follow_up_question` + `weakest_dimension`，
  追问随诊断一次产出 → **省掉一次 LLM 调用**
- `_astream()` 把同步 `chat_stream` 经 `asyncio.Queue` 桥接为异步生成器，避免阻塞事件循环
- 新增消息：`diagnosis_status` / `diagnosis_chunk` / `rewrite_chunk` / `follow_up_received`
- **双 Agent 仍是两次独立调用，未合并**（遵守架构约束，见 CHARTER.md DC-01）
- 追问补充**并入上一题**，不计为新题（避免扭曲轮次进度与均分）
- 后端显式支持 `skip_follow_up`，修复此前跳过追问导致流程卡死

### 雷达图实时更新（liveRadar.js）
- 面试进行区实时雷达卡片，每题诊断后由 `radar_update` 事件驱动
- 双数据集：累计平均（实线）+ 本题得分（虚线）
- `chart.update()` **原地更新**，不销毁重建（避免闪烁）

### 弱项自动追加针对性题
- `round_weak_dimension()` 按**加权失分** `(5 - 均分) × 权重` 定位薄弱维度
- `generate_round_questions(focus_dimension=..., weak_evidence=...)` 定向出题
- 各个维度各有专属出题策略，并注入该维度的**具体失分评语**
- 追加题携带 `focus_dimension`，前端显示"🎯 补强"标记

### v2.6 同步修复的既有缺陷
1. `main.py` ↔ `session.py` **6 处接口断裂**（v2.5 拆分遗留，WebSocket 流程运行即崩）
2. `security.full_check()` / `check_output()` 返回 `(bool, str)` 元组被当 dict 用
3. `session.py` 误用 `from .. import config`（应为 `from ..config import config`）
4. 前端 API 路径错误（`/api/upload-resume`、`/api/report/{id}`）
5. WS 消息体结构不一致（前端展开到顶层，后端读 `msg.data`）
6. 诊断结果字段不匹配（`dimension_details` / `rewritten_answer`）
7. `question_gen.py` 同步 `chat_json` 阻塞事件循环 → 改 `asyncio.to_thread`

---

## v2.5 岗位画像研究 + 引擎模块化（2026-07）

> 详见 `docs/week3_三个模块差距分析与阶段结论_需求.md`

### 岗位画像研究（web_research.py）
- 创建会话时自动搜索岗位相关信息（DuckDuckGo API，免费无 Key）
- LLM 分析搜索结果，输出：丰富后的 JD、核心技能列表、热门面试话题
- 搜索结果自动注入 JD，使面试问题更贴合真实岗位需求
- 提供 `POST /api/research-position` 端点供手动触发

### 诊断反馈 👍/👎
- 每轮诊断面板底部新增 👍/👎 反馈按钮
- 提交反馈写入 `diagnosis_feedback` 表，追踪会话级反馈
- API: `POST /api/feedback`、`GET /api/feedback/{session_id}`
- 反馈按钮提交后显示 ✓ 确认，2秒恢复

### 引擎模块化
`interview_engine.py` 拆分为子包：
```
interview_engine/
├── __init__.py    # 导出 InterviewSession + build_report
├── session.py     # 核心状态机（Init/轮次控制/题目生成/追问/报告委托）
└── report.py      # 报告生成（各维度趋势/强项弱项/建议）
```
向后兼容：`from .interview_engine import InterviewSession` 保持不变。

---

## v2.4 双模式面试 + 面试官切换（2026-07）

### 双模式
- **拟真模式**：原有 6 阶段大厂面试流程
- **传统模式**：笔试→技术一面→技术二面→综合面试→自定义环节（每轮独立面试官）

### 7 种面试官角色（含 attack_level 1-5 / interrupt_prob）
1. 友好型 (attack:1) | 2. 严格型 (attack:3) | 3. 压力型 (attack:5)
4. 专业型 (attack:2) | 5. 好奇型 (attack:1) | 6. 质疑型 (attack:4) | 7. 鼓励型 (attack:1)

### 自动切换机制
- 传统模式：每轮配有固定面试官风格，轮次切换时自动切换
- 拟真模式：可从配置指定每阶段面试官
- 切换时通过 WebSocket 发送 `interviewer_change` 事件
- 前端显示切换动画 + 面试官信息卡片（自动4秒淡出）

---

## v2.3 语音交互（2026-07）

基于浏览器内置 **Web Speech API**，无需后端支持：
- **TTS（文字转语音）**：面试官题目自动朗读，可点击 🔊 按钮重播（优先中文女声，语速 0.9x，朗读时脉冲动画）
- **STT（语音转文字）**：点击 🎤 按钮语音输入回答（实时转写 continuous + interimResults，追加模式自动拼接，录音时输入框边框变红 + 脉冲动画）
- 追问也支持语音输入；提交回答时自动停止所有语音

---

## v2.2 题库管理系统（2026-07）

- DB 表 `question_bank`：含阶段类型、题目文本、考察意图、标签、难度、来源、收藏、使用次数
- API 端点：
  - `GET /api/question-bank` — 列出题目（支持过滤：阶段/难度/收藏/搜索/来源）
  - `POST /api/question-bank` — 创建题目
  - `PUT /api/question-bank/{id}` — 更新题目
  - `DELETE /api/question-bank/{id}` — 删除题目
  - `POST /api/question-bank/{id}/favorite` — 切换收藏
  - `POST /api/question-bank/import` — 从会话导入题目
- 前端：独立的"题库"Tab 页面，含过滤栏、题目列表、新建/编辑表单、导入功能

---

## v2.1 质量驱动推进 + 安全层深化（2026-07）

### 质量驱动推进
阶段平均分未达阈值自动追加题目（每阶段可配置 min_questions / advance_threshold / max_extra）

### 安全防护（security.py）
**4 类启发式内容检查（课程项目级，非安全边界）**：
1. **输入检查（硬）**：高置信注入模式（角色逃逸/Prompt盗取/越狱/特殊token）正则拦截；可被换说法/编码绕过
2. **输入检查（软）**："从现在开始""你必须输出"等易误伤句式仅告警、不阻断
3. **输出检查**：检测 System Prompt 片段泄漏（仅记录，不阻断）
4. **状态/记忆校验**：重复回答（Jaccard）+ 质量校验 + 记忆污染检测（启发式）

> 诚实定性：以上是"内容护栏"而非安全边界。系统无认证/授权，session_id 仅防猜测、不是访问控制。

### 多 AI 后端（config.py + llm_client.py）
- 支持 DeepSeek / 通义千问 / 智谱 GLM / OpenAI 四后端切换
- API: `GET /api/providers` 列出可用后端，`POST /api/switch-provider` 运行时切换
- 通过 `.env` 的 `AI_PROVIDER` 或运行时 API 切换

---

## v2 多轮面试流程（2026-06）

### WebSocket 端点：`/ws/interview/{session_id}`
消息协议状态机由 `main.py` 的 handler 驱动，`interview_engine.py` 管理状态与运算。

### 面试引擎（interview_engine.py）
状态机管理 **双模式**面试流程（拟真6阶段 / 传统5轮次），含：
- 按阶段生成专属题目（6+5 套独立 Prompt）
- 流式双 Agent 诊断
- 轻量追问决策（回答<30字 或 评分<2.5 触发）
- 综合报告生成（各维度趋势 + 强项/弱项 + 建议 + 面试官历程）

### 前端模块化
8 个 JS 模块（ES Module）+ 独立 CSS，使用 Chart.js 雷达图展示各维度趋势。
