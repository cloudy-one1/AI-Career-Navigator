# interviewerAgent（大厂面试官 Agent · InterviewPro）深度研读报告

> 来源：`https://github.com/chenyongzhi1119/interviewerAgent`
> 元信息：Go 1.25.1 · 9 commits · 1★ · 0 fork · 主分支 `main` · 未声明 LICENSE（README 写 MIT）
> 定位：用 AI 模拟 8 家大厂三轮技术面试 + AI Coding 专项面试，可打包为 macOS 菜单栏 App
> 研读范围：`main.go` `internal/{agent,difficulty,extract,llm,memory,model,server,skill}` 全部 Go 源码 + 8 份 `companies/*.yaml` + `web/{index.html,app.js,problems.js}` + 全量 commit message
> 研读方式：逐文件读源码（非只读 README），所有结论均带代码位置

---

## 0. 一句话结论

**产品包装 90 分，内核 40 分。** 它的"三大增强系统"（动态难度 / Agent 记忆 / Skill 注册中心）设计得相当漂亮，是本仓库最值得学的东西——但由于 4 处接线缺失，这三个系统在默认路径下**一行代码都没有真正执行过**。它真正跑起来的只有"公司风格 YAML + LLM 多轮对话 + SSE 流式"这条主干。

对我们项目的价值排序：**配置化公司风格库（可直接对标抄）> PDF 文本修复启发式（可直接抄）> Skill 状态机抽象（值得改造吸收）> 其余（作为反面教材）**。

---

## 1. 技术栈与您的项目对比

| 维度 | interviewerAgent | 您的项目（AI模拟面试官 v6.2） |
|---|---|---|
| 后端 | Go 1.25 · **纯 `net/http` + `ServeMux`，零框架** | Python 3.12 · FastAPI + WebSocket |
| 前端 | 原生 HTML/JS（无构建），`marked` + `Tesseract.js` CDN | 原生 ES Module SPA（Vite）+ Chart.js |
| 存储 | **JSON 文件（会话）+ SQLite（记忆）**，双写 | SQLite（aiosqlite）统一 |
| 桌面端 | `go:embed` + `systray` 打包 macOS `.app` | 纯 Web |
| 语音 | 浏览器 `Web Speech API`（仅输入，无 TTS） | 小米 MiMo 云端 TTS/ASR 双向 |
| 简历解析 | Go PDF 库 + 两阶段文本修复 + 浏览器 Tesseract OCR | `resume_parser` + `resume_retriever` 证据检索 |
| 面试编排 | **无状态机**，纯 LLM 自决 + 用户点"结束本轮" | 轮次/阶段状态机 + `next_action` 三态 + 收尾强控 |
| 评测 | 公司 YAML 里的 `evaluation_rubric`（纯文本模板） | 5 维诊断（STAR/量化/逻辑/相关性/深度）+ 逐题拆解 |
| 测试 | **0 个测试文件** | 559 用例 pytest |
| 分层治理 | 无（`internal/` 只是目录约定） | `.importlinter` L1–L4 强制契约 |

结论：它的**工程成熟度明显低于您的项目**（无测试、无分层约束、无状态机、无收尾控制），但在**"公司风格配置化""PDF 文本修复""桌面端分发"**三个点上做出了我们没有的东西。

---

## 2. 架构总览

```
interviewerAgent/
├── main.go                  # 入口：托盘/CLI 双模式 + 供应商注册 + 三系统初始化
├── tray.go / icon.go        # macOS 菜单栏（systray）
├── companies/*.yaml         # 8 家公司风格配置（热加载，加文件即加公司）
├── internal/
│   ├── model/               # Session / CompanyProfile / AttachedFile（纯数据结构）
│   ├── llm/                 # Provider 接口 + OpenAI 兼容实现 + Anthropic 实现
│   ├── extract/             # pdf.go（文本修复）/ vision.go（LLM OCR，实为死代码）
│   ├── agent/               # session.go（Store：会话 CRUD + 面试驱动）/ prompts.go（Prompt 组装）
│   ├── difficulty/          # scheduler.go（三阶段 + 5 档难度自适应）
│   ├── memory/              # model/service/storage/cache（Cache-Aside 记忆系统）
│   ├── skill/               # skill.go（接口）/ registry.go / builtins.go（4 个内置技能）
│   └── server/              # handler.go（全部路由）/ cors.go
├── web/                     # index.html / app.js / problems.js / style.css（go:embed 内嵌）
└── scripts/build_app.sh     # 打包 macOS .app
```

依赖方向：`main → server → agent → {difficulty, memory, skill, llm, model}`，无循环依赖，无强制检查（纯靠自觉）。

---

## 3. 启动与双形态分发（值得抄）

`main.go` 判断"是否从终端启动"来切换形态：

```go
// 无 TERM 且无 TERM_PROGRAM → 认为是 .app 双击启动
if os.Getenv("TERM") == "" && os.Getenv("TERM_PROGRAM") == "" { trayMode = true }
```

- **托盘模式**：`systray` 菜单栏图标 → 后台起 HTTP → 就绪后自动 `open http://localhost:8080`
- **单实例控制**（`c57cda4` 修复）：启动前 `GET /api/companies`，200 就说明已有实例，直接开浏览器后退出
- **资源路径自适应**：`.app` 内运行时，`companies/` 从 `embed` 解压到临时目录，sessions 落到 `~/Library/Application Support/InterviewPro/`
- **零依赖分发**：`//go:embed all:web` + `//go:embed companies`，`go build` 出单个二进制

**可抄点**：单实例探测（用业务 API 而不是裸端口占用检测，避免误判）、`.app` 内资源路径降级。我们项目若要做桌面壳可直接复用这套判断。

---

## 4. 公司风格配置层（核心资产，强烈建议对标）

`internal/model/company.go` 只有 15 行，却撑起了整个产品的差异化：

```go
type CompanyProfile struct {
    Name             string               `yaml:"name"`
    DisplayName      string               `yaml:"display_name"`
    RoleDescription  string               `yaml:"role_description"`
    Rounds           map[int]*RoundConfig `yaml:"rounds"`
    EvaluationRubric string               `yaml:"evaluation_rubric"`
}
```

`agent.NewStore` → `loadCompanies(dir)` 扫目录读 `*.yaml`，**新增公司 = 丢一个 YAML 文件，零改码**。

以 `bytedance.yaml` 为例，`role_description` 是人格层，"答得太虚直接挂"这种语气都写进去了；每轮 `instructions` 是行为层，字节二面直接硬编码了针对性追问清单：

```
4. 如果候选人描述多 Agent 架构，必须追问：
   - 某个 Agent 持续输出低质量结果时，如何动态调整工作流？
   - 长对话的上下文压缩策略是什么？如何防止 token 爆炸？
5. 如果候选人描述 RAG 项目，必须追问：
   - 召回质量下降时，按什么顺序排查（分块→Embedding→检索）？
```

`tencent.yaml` 则是另一套：一面考 OS/网络/数据结构 + 语言底层（Go GMP、Java JVM、C++ RAII），三面考价值观 + STAR 行为面。**同构不同魂**，这是它 8 家公司的实现方式。

`evaluation_rubric` 是纯文本模板，字节问"强项/薄弱点/建议/评级"，腾讯问"技术深度/项目真实性/亮点/薄弱点/评级"——**评估维度也是按公司配置的**。

> 对比我们：我们的轮次是 `config.TRADITIONAL_ROUNDS` 硬编码在配置里，面试官角色在 `interview_engine/session.py` 里拼。**缺一个"按目标公司切换人格 + 追问清单 + 评估量表"的配置层**。这是本项目最值得吸收的一点。

---

## 5. 会话引擎 `agent/session.go`（Store）

`Store` 是全局单例，持有 `sessions map[string]*model.Session` + `companies` + `providers` + 三大系统（可为 nil，nil 即降级）。

三个动作：

| 动作 | 触发 | 行为 |
|---|---|---|
| `StartInterview` | `POST /sessions/{id}/start` | 塞一条 `IsHidden:true` 的 opener user 消息，让 LLM 出第一题 |
| `Chat` | `POST /sessions/{id}/chat` | Skill 状态机 → 追加消息 → LLM → 难度记录 + 记忆写入 |
| `Evaluate` | `POST /sessions/{id}/evaluate` | 追加 `BuildEvaluationPrompt` 作为 user 消息，状态置 `done` |

**持久化**：每次动作后 `persist(sess)` 全量 `json.MarshalIndent` 写 `sessions/{id}.json`；启动时 `loadPersistedSessions()` 全量读回内存。前端"继续面试"就是把消息重放成气泡（`resumeSession`）。

**风险**：
1. Session 指针在锁外被并发读写——`s.mu.RLock()` 只包住了读 `companies`，`sess.Messages = append(...)`、`sess.Status = ...` 全在锁外。两个请求打同一个 session 会 data race。
2. 全量会话常驻内存，无淘汰、无上限。
3. 每次对话全量重写整个 JSON（含全部历史），长面试下 I/O 与内存放大明显。

---

## 6. Prompt 组装：三路注入（`agent/prompts.go`）

`BuildSystemPrompt` 是一个**分层拼接器**，每一层可独立开关（传 nil 即跳过）：

```
① 基础层：公司 role_description + 轮次 title/instructions + JD + 简历 + 通用规则
② 记忆层：memSvc.BuildWeaknessPrompt(userID)      → 【候选人薄弱点（请重点考察）】：…
③ 难度层：sched.BuildQuestionPrompt(st, weakTags) → 【出题指令】当前阶段：… | 难度：…（第 N 题）
④ Skill 层：最高优先级，追加在最后 → 覆盖普通面试逻辑
```

规则层很薄，只有 5 条：

```
- 每次只提一个问题，等候选人回答后再继续
- 根据候选人回答灵活追问，不要照本宣科
- 始终保持专业、严谨但不刁难的态度
- 全程使用中文
```

> 对比我们：我们的 Prompt 硬约束（禁 Markdown、禁舞台提示、禁垫词、收尾强控）比它强一个量级。它**没有输出净化、没有收尾控制、没有重复题拦截**——面试何时结束完全靠用户点按钮。

**可抄点**：`BuildSystemPrompt` 的"可空注入 + 分层拼接"结构本身很干净，四个系统各自返回片段、由一处统一组装、任一为 nil 就自动降级。这比把逻辑全塞进一个巨型 f-string 要好维护。

---

## 7. 动态难度调度器（设计好，但没接线）

`internal/difficulty/scheduler.go`，三阶段 × 五档难度：

```go
PhaseMinQ:     {basic: 3, experience: 3, design: 2}
UpThreshold:   2,  UpScore:   75.0   // 连续 2 次 ≥75 → 难度 +1
DownThreshold: 2,  DownScore: 55.0   // 连续 2 次 <55 → 难度 -1
```

`RecordScore` 一次调用完成三件事：更新连续计数 → 难度升降档（1–5  clamping）→ 阶段推进（题数达标且阶段均分 ≥50 才升阶）。

难度描述映射得很有层次：

```
1 简单（定义/概念层）  2 基础（原理+简单应用）  3 中等（有深度，需举例）
4 较难（需权衡取舍或手撕思路）  5 困难（开放性，无标准答案，考察视野）
```

**问题见 §16.1 / §16.2：这个调度器在默认路径下从未被调用。**

---

## 8. Agent 记忆系统（设计最完整，死得最彻底）

`internal/memory/`，四件套：

**① 数据模型**（`model.go`）
- `UserProfile`：`overall_level` 1–5 / `total_questions` / `avg_score`，跨会话
- `WeaknessRecord`：`tag` + `weakness_score` 0–100 + `occurrence_count` + `expires_at`
- `QuestionRecord`：单次答题，含 `phase` / `difficulty` / `tags` / `score`

**② 更新策略**（`service.go`）——设计得很好：

```
score < 60  → 记录/加重：EMA  α=0.4，weakness = 0.4*(100-score) + 0.6*old，计数 +1，续期 30 天
score > 85  → 减轻：计数 -1；归零则删除薄弱点，否则 weakness *= 0.7
60–85       → 中性区间，不动
```

**③ 过期淘汰**：`WeaknessExpireDays = 30`，后台 goroutine `PruneExpired` 清理，"练 → 评 → 记 → 再练"闭环。

**④ Cache-Aside**（`cache.go`）：内存 `map` + `RWMutex` + 5 分钟 GC；TTL 分级（Profile 10min / Weakness 5min / Recent 2min）；写路径"先写 DB 再 `Del` 缓存"。`Storage` 是接口，注释说"生产可换 MySQL"。

**问题见 §16.1–§16.3：`QuestionRecord.Tags` 从不赋值、`Session.UserID` 从不赋值，导致薄弱点表永远为空、记忆写入整段被跳过。**

---

## 9. Skill 技能注册中心（本项目最原创的抽象）

`internal/skill/skill.go` 开篇注释就点明了与 Tool 的区别，这是全仓库最有价值的一段设计说明：

```go
// Skill 与普通 Tool 的核心区别：
//   - Tool 是无状态的单次调用（如：搜索、计算）
//   - Skill 是有状态的多轮交互（跨多个对话轮次维持上下文）
```

接口 7 个方法：`Name / Description / Priority / CanActivate / BuildSystemPrompt / OnTurnEnd / IsComplete`。

`Registry` 按 `Priority` 降序排序，`Match` 返回第一个 `CanActivate` 为真的 Skill。4 个内置技能：

| Skill | 优先级 | 触发词 | 步数 | 行为 |
|---|---|---|---|---|
| `quick_quiz` | 80 | 测验/quiz/刷题/来几道题 | 5 题 | 选择题 A/B/C/D，即时判对错+解释，最后给 X/5 总分 |
| `concept_teach` | 70 | 解释/不太懂/教我/什么是 | ≤4 轮 | Socratic 教学：先问已知 → 类比讲解 → 小练习 → 确认掌握 |
| `project_highlight` | 60 | 项目亮点/怎么介绍/STAR | 4 步 | 背景 → 技术方案 → 结果 → 提炼 STAR，给 30 秒/2 分钟话术 |
| `tech_compare` | 50 | 区别/对比/哪个好/vs | 5 维 | 定位 → 性能 → 一致性 → 运维 → 选型建议（3 条判断标准） |

状态推进靠 `Metadata map[string]any`（如 `quiz_q`、`teach_round`、`ph_step`、`cmp_dim`），`OnTurnEnd` 递增，`IsComplete` 判边界。触发即 `ActiveSkill` 置名，`BuildSystemPrompt` 里把 Skill 专属 prompt **追加在最后以覆盖普通面试逻辑**。

**评价**：这套"有状态多轮技能"抽象比我们 v5.0 的 `switch_mode`（simulation/traditional/coach/hardcore/interview_only）更结构化——我们有模式切换但没有"进入条件 + 退出条件 + 步骤状态机"。**值得改造吸收**（见 §17）。

**局限**：触发是纯关键词 `strings.Contains`，`CompareSkill` 的 `"和…的区别"` `"和...区别"` 这种穷举变体很脆弱；无语义匹配、无优先级冲突日志、无"Skill 中途被用户打断"的兜底。

---

## 10. LLM 抽象层

```go
type Provider interface {
    Stream(ctx, systemPrompt, sess, history, w io.Writer) (string, error)
    ExtractImageText(ctx, base64Data, mimeType) (string, error)
    Info() ProviderInfo
}
```

- 5 个供应商：Anthropic（原生 SDK）/ OpenAI / DeepSeek / GLM / Qwen（后四者全走 `OpenAICompat`）
- **双通道 Key**：环境变量（服务端配置，`IsServerConfig=true` 前端显示"服务器已配置"）vs 前端 `localStorage` 里的用户 Key（`NewProviderFromKey` 动态构造 Provider）
- 图片能力按供应商声明：`supports_img`（Anthropic/OpenAI/Qwen ✅，DeepSeek/GLM ❌），`supports_pdf` 全 false
- **多模态注入策略**（很聪明）：图片只在**首条 user 消息**注入一次，后续轮次只发纯文本，避免每轮重复计费：

```go
// 首条用户消息特殊处理：imgBlocks + text 合并成 content 数组
// 其余消息 Content 均以纯字符串形式发送
```

- **SSE 转义**（`util.go`，20 行但很关键）：

```go
func sseEscape(s string) string {  // 换行会破坏 SSE 帧，转成 "\ndata: "
    ... if r == '\n' { out += "\ndata: " } else { out += string(r) }
}
```

> 对比我们：我们的 v4.3 fallback + v6.0 `AI_PROVIDER=auto` 探测比它的"环境变量 if-else 链"更健壮；但它的**"图片只注入首条消息"和"供应商能力声明表驱动"**两点可以直接补进我们的 `llm_client`。

---

## 11. 简历/JD 提取：两阶段文本修复（直接可抄）

`internal/extract/pdf.go` 是**全仓库工程含量最高的文件**。PDF 库取出的文本被排版切碎后，它做了两阶段修复：

**Phase 1 `rejoinBrokenLines`** — 逆操作：只认两种硬断信号，其余全部拼接
- 硬断信号 1：`isNumberedListItem`（`1.` / `2、` / `3)` / `①`，且 ≥3 字符）
- 硬断信号 2：`isLongAllCapsHeading`（全大写且字母数 ≥6，避免把 "API" 误判为标题）
- `needsSpace`：只有 ASCII 单词相邻时才补空格（中文拼接不需要空格），并处理 `3.14` 这类小数不被当编号

**Phase 2 `restoreStructure`** — 再把结构化断行插回去：
1. 中文简历章节词表前后插空行：`教育背景 / 专业技能 / 工作经历 / 项目经历 / 自我评价 / 获奖情况 …`（20 个词）
2. `·` 前强制换行（逐 rune 扫描）
3. `-` 后紧跟 CJK 且前一个字符不是 `-`/换行 → 换行（**特意避开 `2023-09` 日期区间和负数**）
4. `splitEmbeddedNumberedItems`：处理"…句子。1.下一条…"→ 插换行，且排除 `3.14` 这类（标点后紧跟数字则不算）

失败兜底：`PDF 未提取到文字（可能是扫描版图片 PDF，请改用图片上传）`。

> **可直接抄**：我们的 `resume_parser` 若也有 PDF 排版切碎问题，这两组启发式规则（`isNumberedListItem` / `isLongAllCapsHeading` / 中文章节词表 / `-`+CJK 判别）拿来即用，注释也写得清楚。

**割裂之处**：扫描件/截图走的是**浏览器端 Tesseract.js**（首次下载约 12MB 中文包），后端 `extract/vision.go` 的 LLM OCR 路径前端根本没调用——`callExtract` 的 `image` 分支直接走 `ocrImage()`。**`vision.go`、`handler.go` 的 `case "image"`、`pickVisionProvider` 全是死代码。**

---

## 12. 前端与 AI Coding 模式

三个视图：新面试（配置）/ 历史记录 / AI 编程面试。单页 `div.view` 切换，无路由无框架。

**AI Coding 模式**（`problems.js` 的 `AI_CODING_PROBLEMS`，14 题）——这是它的差异化功能：

```js
{ id, title, company, scenario, difficulty, tags,
  background,        // 业务背景
  requirements[],    // 功能要求
  tech_stack,
  evaluation_points[],  // 考察维度（Prompt 设计 / 架构决策 / 代码审查 / 边界处理）
  starter_prompt     // 给 AI 的起始 Prompt 范例
}
```

题型很贴 2025 真实场景：电商购物车并发、Feed 流推荐接口、分布式限流器（Redis+Lua）、优惠券幂等核销、IM 推送、骑手调度（GeoHash）、搜索补全（ZSET+ZRANGEBYLEX）、日志异常检测 Agent、RAG 知识库、Meta 迷宫 BFS、秒杀压测优化、多模态审核 Pipeline、SQL 慢查询助手。

`buildAICodingSystem(p)` 把题目 4 个字段拼进 system prompt，考察重点是**"你怎么用 AI"**而不是"你会不会写代码"：

```
- 先让候选人描述思路，再引导他们展示 Prompt 设计
- 对候选人的每个回答进行 2-3 层追问
- 当候选人展示 Prompt 或代码时，从「Prompt 清晰度」「架构合理性」「代码质量感知」角度点评
```

**但它完全是无状态旁路**：走 `/api/llm/stream`（后端只做透传，不落库），历史由前端 `codingState.aiMessages` 持有，**刷新即丢、无评估、无历史记录**。

**死代码**：`ALGO_PROBLEMS`（8 道 LeetCode 题）+ `setCodingMode('algo')` + `loadAlgoProblem` 仍在 `app.js` 里，但 `index.html` 已写 `<!-- Monaco removed -->`，`ctab-algo` / `algo-toolbar` / `algo-editor-wrap` 这些 DOM 全被删了——调用 algo 分支会直接抛错。

**前端其他问题**逐条见 §16.7–§16.10。

---

## 13. 全链路数据流

```
[配置] 选供应商/公司/轮次 → 粘贴 JD（或 Ctrl+V 截图 → Tesseract OCR）
                          → 传 PDF（/api/extract → 两阶段修复 → 回填文本框）
   ↓ POST /api/sessions（带 provider_key/model/base_url）
[开始] → POST /sessions/{id}/start
        BuildSystemPrompt = 公司人格 + 轮次指令 + JD + 简历 + 通用规则
        （+ 薄弱点注入 ✗  + 难度指令 ✗  + Skill ✗，原因见 §16）
        → LLM Stream → SSE `data: chunk\n\n`（sseEscape 处理换行）→ persist()
   ↓ POST /sessions/{id}/chat {message}
        Skill 状态机 → 追加消息 → LLM → [难度记录 ✗] + [记忆写入 ✗] → persist()
   ↓ POST /sessions/{id}/evaluate（用户手动点"结束本轮 · 获取评估"）
        BuildEvaluationPrompt = 轮次标题 + 公司 evaluation_rubric（+ 难度摘要 ✗）
        → 流式输出 Markdown → status=done → persist()
   ↓ "继续下一轮" → POST /api/sessions 建**全新 session**（上一轮结论不带入）
```

---

## 14. 演进历史（9 commits，1 天内完成）

```
fe84cc0  Initial commit：8 家公司 + 三轮 + AI Coding 14 题 + 多供应商 + PDF/OCR + 历史记录
8c43e60  docs: 完善 README
5fb380b  feat: 封装为 macOS 菜单栏应用（tray.go / icon.go / embed / build_app.sh）
e0d4d69  fix: .app 启动问题 + 重做图标（端口占用检测）
c57cda4  fix: 多实例冲突（探测 8080，已运行则开浏览器退出）
4510753  docs: 重写 README（新手向 5 步部署）+ 截图
8ee7e91  docs: 更新模型列表
654fc70  feat: 三大增强系统 —— 动态难度 + Agent 记忆 + Skill 注册中心   ← 核心提交
23e107d  fix: DeepSeek 默认模型 deepseek-chat → deepseek-v4-flash
```

**关键观察**：整个仓库是 **2026-06-18 21:44 至 06-19 07:38 的 10 小时内**完成的，全部 commit 带 `Co-Authored-By: Claude Sonnet 4.6`。这是一次典型的 **AI 辅助的"一气呵成式开发"**——架构设计漂亮、文档齐全，但**缺少验证环节**：核心提交 `654fc70` 落地三大系统后，没有任何一个 commit 验证过它们真的在跑。这直接导致了 §16 的四处接线缺失。

---

## 15. 工程亮点清单（值得抄的 8 条）

| # | 亮点 | 位置 | 我们可复用程度 |
|---|---|---|---|
| 1 | **公司风格 YAML 热加载**（加文件=加公司，零改码） | `agent.loadCompanies` | ★★★★★ 直接对标 |
| 2 | **PDF 两阶段文本修复**（章节词表/编号识别/CJK 判别） | `extract/pdf.go` | ★★★★★ 直接抄 |
| 3 | **Skill 有状态多轮接口抽象**（7 方法 + 优先级 Registry） | `skill/skill.go` | ★★★★☆ 改造吸收 |
| 4 | **分层 Prompt 注入**（nil 即降级，Skill 最高优先级覆盖） | `agent/prompts.go` | ★★★★☆ 结构可借鉴 |
| 5 | **薄弱点 EMA + 过期淘汰**（0.4 加重 / 0.7 衰减 / 30 天过期） | `memory/service.go` | ★★★★☆ 补进我们的记忆闭环 |
| 6 | **多模态只注入首条消息**（省 token） | `llm/openaicompat.go` | ★★★★☆ 直接抄 |
| 7 | **SSE 换行转义**（`\n` → `\ndata: `） | `llm/util.go` | ★★★☆☆ 我们若上 SSE 需要 |
| 8 | **单实例探测 + `.app` 资源路径降级** | `main.go` | ★★★☆☆ 做桌面端时用 |

---

## 16. 关键技术债与 Bug（重点，按严重度排序）

### 🔴 16.1 `estimateScore` 评错了对象（核心 Bug）

```go
// session.go Chat()
reply, err := provider.Stream(nil, systemPrompt, sess, sess.Messages, w)  // ← 面试官的回复
...
if s.Sched != nil && sess.DiffPhase != "" {
    score := estimateScore(reply)   // ← 拿「面试官回复」的长度给「候选人」打分
```

`estimateScore` 注释写的是"用回复质量代理估算**候选人**得分"，但传进去的 `reply` 是 **LLM 面试官的输出**。后果：候选人答得再好，分数取决于面试官下一题写了多少字。整个难度自适应的输入信号是噪声。

顺带：`QuestionRecord{Question: userMsg, Score: score}` —— 把**候选人的回答**填进了 `Question` 字段，而 `Answer` 字段**从未赋值**（永远为空）。

### 🔴 16.2 难度系统永不启动（死代码）

`CreateSession` 不初始化 `DiffPhase`（零值 `""`），而 `Chat()` 的守卫是：

```go
if s.Sched != nil && sess.DiffPhase != "" { ... }   // 首次必为 false
```

由于这个分支从不执行，`DiffPhase` 永远不会被写入 → **难度调度器 + 阶段推进永久关闭**。同理 `prompts.go` 里 `if sched != nil && session.DiffPhase != ""` 的难度指令注入也永不触发。

### 🔴 16.3 记忆系统永不写入（死代码）

两道关卡同时卡死：

```go
// 关卡 1：Session.UserID 从未赋值
//   CreateSession 不设置 UserID；前端 POST /api/sessions 的请求体也没有 user_id 字段
if s.MemSvc != nil && sess.UserID != "" { memSvc.RecordAnswer(...) }  // 恒 false
if memSvc != nil && session.UserID != "" { base += BuildWeaknessPrompt(...) }  // 恒 false

// 关卡 2：即便过了关卡 1，Tags 也是空的
memSvc.RecordAnswer(ctx, &memory.QuestionRecord{ ... /* 没有 Tags */ })
// → service.go: for _, tag := range r.Tags { ... }  循环体一次不执行
// → updateWeakness 从不调用 → weakness_records 表永远为空
```

**结论**：`internal/memory/` 的 ~1200 行代码（含 Cache-Aside、EMA、过期淘汰、Storage 接口）在默认路径下**完全未生效**。仓库里提交的 `memory.db`（32KB）大概率只是 `migrate()` 建的空表。

### 🔴 16.4 Skill 系统同样被 `UserID` 拖累（部分失效）

`BuildSystemPrompt` 的 Skill 注入本身不依赖 `UserID`，**能跑**；但 `skillCtx.WeakTags` 因 `UserID == ""` 恒为空，导致 `QuizSkill`、`TeachSkill` 里"重点围绕候选人薄弱点"的分支永远不生效。

### 🟠 16.5 会话状态存在并发 data race

`Store` 有 `sync.RWMutex`，但 `Chat()`/`Evaluate()` 里对 `sess.Messages`、`sess.Status`、`sess.DiffLevel` 的读写**全在锁外**（只有读 `companies` 上了 RLock）。`persist()` 也无锁。两个并发请求打同一 session 会 race；`go test -race` 一跑就现形。

### 🟠 16.6 无鉴权 + Key 明文存 localStorage

- `handler.go` 全部路由无鉴权中间件（只有 CORS）。服务端配了 Key 的话，同网段任何人都能白嫖。
- 用户 Key 明文 `localStorage.setItem('interviewer_provider_settings', ...)`，且每个请求回传后端。
- `Session.ProviderKey` 标了 `json:"-"`（不落盘，这点做对了），但没有任何日志脱敏措施。

### 🟠 16.7 前端每个 chunk 全量重解析 Markdown（O(n²) + XSS 面）

```js
fullText += chunk;
bubble.innerHTML = marked.parse(fullText);   // 每个 token 重新解析整个文本
```

长评估输出下抖动明显；且 `marked` **未配 DOMPurify**，LLM 输出里的 `<img onerror=...>` 会直接执行。我们有 v6.2 `output_sanitizer`，它完全没有。

### 🟠 16.8 跨轮上下文丢失

`nextRound()` 是 `POST /api/sessions` **建全新会话**，二面看不到一面的任何对话与评估结论。所谓"三轮面试"实际是三次独立面试，`savedJD`/`savedResume` 之外什么都没继承。

### 🟡 16.9 Token 无上限增长

`BuildSystemPrompt` 每轮都拼**完整 JD + 完整简历全文**，历史消息全量发送，**无截断、无滑窗、无摘要压缩**。`ContextWindowSize = 10` 定义了但只用在 `GetSessionContext`（而后者从未被调用）。长面试必然撞上下文上限。

### 🟡 16.10 死代码三处

1. `extract/vision.go` + `handler.go` 的 `case "image"` + `pickVisionProvider` —— 前端图片走 Tesseract，从不调后端
2. `ALGO_PROBLEMS`（8 题）+ `setCodingMode('algo')` + `loadAlgoProblem` —— 引用的 DOM 已从 `index.html` 删除
3. `MemoryService.GetSessionContext` / `SQLiteStorage.TopWeakTags` / `TagScoreMap` —— 定义了无调用方

### 🟡 16.11 `var _ = extract.PDF` 的 import hack

`handler.go` 顶部 `var _ = extract.PDF // ensure package is imported` —— 说明 `extract` 包在该文件里没有其他引用点，是重构残留的坏味道。

### 🟡 16.12 `memory.db` 提交进了 git

32KB 的 SQLite 二进制入库，且 `.gitignore` 只有 230 字节（基本只忽略二进制产物）。会话数据 `sessions/` 若未忽略也会入库。

### 🟡 16.13 零测试

全仓库**没有一个 `_test.go`**。难度调度、薄弱点 EMA、PDF 文本修复这三块纯逻辑，本该是单元测试的最佳素材——也正因为没有测试，§16.1–16.3 的接线缺失才完全没被发现。

---

## 17. 对您项目的可迁移清单

### P0 — 直接抄（低风险、高收益）

1. **公司/岗位风格配置层**
   新建 `backend/company_profiles/*.yaml`，字段对齐 `CompanyProfile`（`name / display_name / role_description / rounds[] / evaluation_rubric`），`question_gen` 加载时把它并入 `get_interviewer_system_prompt`。
   → 收益：把 `config.TRADITIONAL_ROUNDS` 从硬编码升级为可配置，且**评估量表随公司变**。

2. **PDF 文本两阶段修复**
   把 `rejoinBrokenLines` / `shouldBreak` / `isNumberedListItem` / `isLongAllCapsHeading` / 中文章节词表 / `splitEmbeddedNumberedItems` 移植进 `resume_parser`。
   → 收益：直接改善简历解析质量，纯函数、易测试。

3. **多模态图片只注入首条消息**
   移植进 `llm_client`，避免每轮重复计费。

### P1 — 改造吸收（中等改动，需走 OpenSpec）

4. **Skill 状态机抽象**
   参考 `Skill` 7 方法接口，把我们现有的 `switch_mode`（simulation/traditional/coach/hardcore/interview_only）升级为：
   ```
   SkillBase: name / priority / can_activate(ctx, user_input)
              / build_prompt(ctx) / on_turn_end(ctx, reply) / is_complete(ctx)
   ```
   新增 `SkillRegistry.match()`，把 `coach` 模式做成真 Skill（有进入条件、步骤状态、退出条件），并补 3 个新 Skill：快速测验、STAR 项目亮点提炼、技术对比。
   → 收益：把"模式切换"从配置开关升级为可插拔能力单元。

5. **薄弱点 EMA + 过期淘汰**
   我们已有 `db.list_unresolved_weaknesses()` 与 `accumulate_weaknesses`，补上：
   - EMA 衰减（加重 α=0.4 / 减轻 ×0.7）而非简单计数
   - `expires_at` 30 天过期 + 后台清理
   - 中性区间（60–85 不动），避免抖动

6. **动态难度调度器**
   三阶段 basic/experience/design × 5 档，参数（`PhaseMinQ` / `UpScore=75` / `DownScore=55` / 升阶均分 50）写进 `config`，**接线时必须用 `diagnosis_engine` 的真实评分，绝不能学它用长度代理**。

### P2 — 作为反面教材（我们知道但不能犯）

7. **每加一个子系统，必须有"接线验证清单"**：本项目三大系统全部死在"字段没初始化"上。我们引入任何新模块时，应在 `tests/` 里加一条端到端断言（"跑完一轮后 `weaknesses` 表非空"），而不是只测单元函数。

8. **AI Coding 专项题库**（14 题设计得很扎实，尤其 `evaluation_points` 四维：Prompt 设计 / 架构决策 / 代码审查 / 边界处理）。若要引入，必须**接进我们的会话引擎与报告体系**，不能像它一样做成无状态旁路（刷新即丢、无评估、无历史）。

---

## 18. 综合评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 产品包装 | ★★★★☆ | README 新手友好、截图完整、FAQ 齐全、一键打包 .app |
| 架构设计 | ★★★★☆ | 分层清晰、接口抽象好（Provider/Storage/Skill）、可插拔 |
| 代码实现 | ★★☆☆☆ | 三大系统未接线、data race、评错对象、无锁写入 |
| 工程质量 | ★☆☆☆☆ | 零测试、死代码三处、二进制入库、无 CI |
| 提示词工程 | ★★☆☆☆ | 公司人格写得细，但缺输出净化/收尾控制/去重 |
| 差异化功能 | ★★★★☆ | 8 家公司风格 + AI Coding 14 题是本仓库真正价值 |
| **可借鉴价值** | **★★★★☆** | **配置化风格库 + PDF 修复 + Skill 抽象，三条都实打实** |

---

*研读完成时间：2026-08-28 · 基于 commit `23e107d`（main 分支最新）*
