# 变更日志（CHANGELOG）

> 记录 v2 → v7.0 的版本迭代叙事（新增/推翻/修复/范围）。不变的架构约束与决策记录见 [CHARTER.md](CHARTER.md)，日常协作入口见 [CODEBUDDY.md](CODEBUDDY.md)。

---

## v7.0 双端平台化：认证与资源归属 + 三实体 + 报告分享 + 流程状态显式化（2026-08-29）

> 本轮把项目定位从"单端课程项目"转向"工程化平台"（DC-06）：求职者自主练习的产品命题**不变**，在外围加一层"身份与归属"，让同一套诊断内核可以服务"招聘者只读查看报告"这第二端。诊断链路（五维/双 Agent/追问）零改动。设计依据来自对 Gua-AI-interview 的深度研读（`docs/Gua-AI-interview-深度研读.md`）。

### 1. 认证与资源归属（`backend/auth.py`，L2 新增）

- **分层落点**：认证刻意独立成 `auth.py` 而非塞进 `security.py`——后者定性是"面试回答内容的启发式检查"，与"密码哈希/JWT"是两种职责，混用会让 "security" 一词指两件事。已登记 `.importlinter` L2 行，`run.py lint` 强制。
- **可关闭开关（回滚承诺）**：`AUTH_ENABLED=false`（默认）时 `get_current_user` 恒返回匿名身份、所有归属过滤跳过，**行为与 v6.x 完全一致**——`tests/test_api.py::TestAuthIntegration::test_disabled_matches_legacy_behavior` 是这条承诺的回归底线。
- **安全设计**：bcrypt 哈希（自带盐，同密码两次哈希必不同）；JWT HS256，密钥优先取 `AUTH_SECRET` 环境变量，缺省生成并持久化到 `data/.auth_secret`（避免重启后所有 token 失效）；登录失败不区分"用户名不存在"与"密码错误"（防枚举），用户不存在时也执行一次哈希校验（防计时侧信道）；**越权一律 404 而非 403**——403 会暴露"该 id 存在"。
- **WebSocket 握手校验**：token 走 query 参数（浏览器 WS API 不支持自定义请求头），在 `accept()` **之前**校验，失败 `close(4001)`——消除 CHARTER 披露的"WS 无身份校验"局限。前端 `createInterviewWS` 在每次重连时重新读 token，收到 4001 停止重连。
- **归属语义**：会话/简历/岗位按 `owner_id` 归属；存量数据（owner=NULL）在认证开启后对任何登录者不可见，但**数据未丢**（关掉开关仍可查看）。
- **遗留坑记录**：slowapi 的 `@limiter.limit` 靠**参数名** `request` 注入请求对象——改名（如 `http_request`）会让全部限流端点在启动期抛 `No "request" argument`。

### 2. 简历库 / 岗位库（可复用输入资产）

- 简历此前**不落库**（每次开练重新上传、重新调 LLM 解析）；岗位 JD 每次重新粘贴。新增 `resumes` / `positions` 两张表（`CREATE TABLE IF NOT EXISTS`，老库自动生效），CRUD + 归属过滤沿用"一个可空 owner_id 参数"的统一约定。
- `sessions` 表加列走 `_ensure_owner_columns`（照抄 `_ensure_weakness_columns` 的 PRAGMA+ALTER 范式）。**SQLite 的 `ALTER TABLE ADD COLUMN` 不支持 `REFERENCES`**，owner_id 不带外键，完整性由应用层保证——这是硬限制，已在注释中写明。
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

- 借鉴 Gua-AI-interview 的 evidenceQuote：每个维度除 score/comment 外，必须输出 `quote`——从候选人回答中**原样摘录**的支撑片段（≤30 字，不得改写/概括/编造）。把主观打分锚定到文本证据，让"分数怎么来的"可复核。
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

## v6.6 竞品借鉴专项七期：interviewerAgent P1 三项落地——记忆衰减 + 技能状态机 + 动态难度（2026-08-29）

> 承接 v6.5（同一来源的 P0 两项），落地研读报告 §17 的 **P1 三项**。本轮的共性是：**三项都不是新功能，而是给既有能力补上"时间维度""状态维度""强度维度"**——v6.4 建成的长期记忆闭环里跑的是裸计数器，模式切换没有结束条件，出题难度恒定不变。

### 1. 长期薄弱点：EMA 衰减 + 30 天过期 + 中性区不动（`backend/weakness_memory.py`，L2）

借鉴 `internal/memory/service.go` 的 `updateWeakness`，把 v6.4 的 `_weakness_counts[t] += 1` 升级为有强度的长期记忆：

- **阈值换算**：对方 0-100 分制 → 我们五维 1-5 分，先映射薄弱度 `(5-score)/4×100`，阈值 **<3.0 加重 / >4.5 减轻 / 3.0–4.5 中性**；加重用 EMA（α=0.4，10 次迭代残差 0.6%），减轻按比例衰减（×0.7），计数归零即删除。
- **岗位权重放大（相对原设计的增量）**：`weight/0.2` 夹 0.5–2.0 倍——岗位越看重的维度，同样失分越要命。复用 v2.6 的 JD 动态权重，对方无此概念。
- **保留原版语义**：中性区连 `last_seen` 都不续期 → "30 天没再暴露严重短板即视为已改善"，衰减靠时间而非练习次数。
- **存储分工**：`weakness_profile`=历史流水（图谱/建议），新增 `weakness_memory`=当前状态（每维度一行，新表用 `CREATE TABLE IF NOT EXISTS` 即可，无需 ALTER 迁移）。
- **升级兼容**：新表为空时回注入与复习建议**回退 v6.3 口径**——否则老库升级后首场面试会静默丢掉记忆回注入。
- 回注入 prompt 同步升级：从"历史均分 X"改为"最近得分 X，**累计失分 N 次**"，让模型区分"反复失分"与"一次失手"。

### 2. 面试技能状态机（`backend/interview_skills.py`，L3）

补上"临时插入、有步骤、有完成条件"的能力层——区别于既有 `switch_mode`（整场设定、无结束条件）：

- **接口**：`SkillBase{name/description/priority/can_activate/build_prompt/on_turn_end/is_complete}` + `SkillRegistry`（按 priority 降序，match 取首个命中；单技能判定抛异常不影响其它技能）。
- **两点刻意不照抄原版**：
  - **触发**：原版纯关键词 `strings.Contains`（穷举 `"和…的区别"` 变体）会把普通回答误判为触发；本项目**默认显式触发**（WS `skill` 消息），`can_activate` 仅在开启自动匹配时参与。
  - **结束**：原版完成只清字段不告知用户；本项目返回 `closing_message`，工程层推送"已回到正式面试"。
- **技能轮不进诊断**：测验答案（"B"）不是面试作答，打五维分只会污染报告 → 技能轮单独维护 `skill_history`，不写 `all_diagnoses`/`answer_history`。
- **内置 3 个**：`quick_quiz`（5 题即时判分，P80）、`concept_teach`（苏格拉底讲解 ≤4 轮，P70）、`tech_compare`（5 维度对比，P50）。原版 4 个中的 `project_highlight` 未移植——与 STAR 诊断 + `resume_anchors` 高度重合。

### 3. 动态难度调度器（`backend/difficulty.py`，L2）

- **只抄轮内自适应，不抄阶段推进**：对方的调度器同时决定难度与阶段；本项目阶段推进是 v6.2 的工程强控，让难度信号反向决定阶段流转等于把已收敛的可控性交回统计信号。本模块只回答"这道题出多难"。
- **信号源纪律**（对方最大的坑）：它用"回复长度"代理评分，整套调度是噪声；我们直接用 `diagnosis_engine` 加权总分，且**无效分数（None/0/非数字）一律忽略**——诊断失败不是"得 0 分"，误记会把难度一路降到底档。
- **归因披露（必须配套）**：难度改变出题分布但评分标准固定，分数变低时须能区分"变差了"与"难度升了" → `trace` 逐题记录档位进报告 `difficulty` 字段，变档时 WS 推 `difficulty_change`。
- 出题 prompt 同步修正：原"第 1 题热身、最后 1 题深度挑战"与难度档指令自相矛盾，改为"有难度指令则按档位，否则按递进"。

### 4. 测试与契约

- 新增 `test_weakness_ema.py`（28 例）/ `test_interview_skills.py`（29 例）/ `test_difficulty.py`（26 例）；全量 **830 例通过**，`run.py lint` 通过。
- 契约：`weakness_memory` + `difficulty` 注册 L2，`interview_skills` 注册 L3。
- 需求文档：[week8_记忆衰减与技能难度_需求.md](docs/week8_记忆衰减与技能难度_需求.md)。

### 范围边界（诚实披露）

- **AI Coding 专项题库（原 P2-8）不做**：与"诊断回答质量"命题距离远；原项目实现是无状态旁路（刷新即丢、无评估），引进需连会话引擎与报告一起改。
- ~~**技能未接前端 UI**~~ → **已补齐（同轮追加）**：面试页诊断侧边栏新增「🛠 面试技能」条——三个技能按钮显式激活（不靠关键词猜测）；激活中禁用其它按钮并显示 `技能名 步数/总步数` 与「退出技能」入口；技能轮发言经 `follow_up` 消息回带 `skill/step/total` 刷新进度；`difficulty_change` 以 toast 提示，让用户看见难度在动（否则分数变化无法归因）。`npm run build` 通过。
- 难度**不影响**轮次推进与阶段判定，仅在出题 prompt 层生效。
- 前端为 Vite 构建产物（`frontend/dist`），源码改动后需 `npm run build` 才会生效。

---

## v6.5 竞品借鉴专项六期：interviewerAgent 两项落地——公司风格配置层 + PDF 文本两阶段修复（2026-08-29）

> 对标 [chenyongzhi1119/interviewerAgent](https://github.com/chenyongzhi1119/interviewerAgent)（Go 单二进制大厂面试模拟器，10 小时 AI 辅助完成）研读后，按《[interviewerAgent-深度研读.md](docs/interviewerAgent-深度研读.md)》§15 的 **P0 两项**落地。该项目"产品包装 90 分、内核 40 分"——三大增强系统（动态难度/Agent 记忆/Skill 注册中心）全部死于接线缺失（`estimateScore` 评错对象、`DiffPhase`/`UserID`/`Tags` 从未赋值），本轮只抄它**真正跑了**且**我们没有**的部分；同时以它的接线缺失为反面教材，新模块落地的同轮即补端到端断言测试。

### 1. 公司风格配置层（`backend/company_profiles.py`，L2 + `backend/company_profiles/*.yaml`）

借鉴其 `loadCompanies` 扫目录热加载与 15 行 `CompanyProfile` 字段结构，**加 YAML 即加公司、零改码**：

- **字段三层**：`role_description`（公司人格：评判标准/追问清单）+ `rounds[].match+instructions`（轮次行为）+ `evaluation_rubric`（评估量表，进报告 `company_rubric`）。内置字节/腾讯/阿里三份种子配置（内容按本项目诊断驱动风格改写，不照抄）。
- **与原版的关键差异**：其轮次按键 `1/2/3` 索引，只兼容"一面/二面/三面"一种结构；本项目改为**轮次名关键词匹配**（"技术广度"/"技术一面"同时命中"技术"），拟真 6 阶段与传统 5 轮两种模式通吃。新增 `match_keywords` 按 JD 关键词命中数自动选定。
- **解析优先级**：前端显式选择 > JD 自动匹配 > 不启用；`"none"` 哨兵值明确关闭；未知名称降级为自动匹配而非报错。
- **注入点与顺序**：`get_interviewer_role_prompt()` 前置「公司人格 > 本轮公司指令 > 风格角色卡」——公司是外层人格，风格卡是内层语气，两者正交（修复过程中发现并修正 `parts` 列表被重建覆盖公司块的 bug，公司块必须 append 不能重建）。
- **容错哲学**（与 v6.2 简历追问点同款）：pyyaml 缺失 / 目录不存在 / 单文件损坏 / 空壳配置 → 跳过或整体降级，**绝不阻断面试主流程**。
- API：`GET /api/company-profiles`（前端选择器）+ `SessionCreateRequest.company_profile`；前端面试设置 Step 2 新增"🏢 目标公司风格"下拉（自动匹配/具体公司/不启用），接口失败静默保留兜底选项。

### 2. PDF 文本两阶段修复（`resume_parser.py`）

移植其全仓库工程含量最高的 `internal/extract/pdf.go` 启发式，修复 PDF 提取文本的两类损伤（列宽切碎的软换行 / 标题条目与正文粘连）：

- **Phase 1 逆拼接**：只认两种硬断信号（编号列表项、≥6 字母全大写标题——避免 API/SQL 被误判），其余全部拼回，仅 ASCII 单词相邻补空格；
- **Phase 2 复原**：中文简历章节词表（22 词）前后插空行、`·` 前换行、`-` 后（允许隔空白）紧跟 CJK 换行（`2023-09` 日期与负数天然不含 CJK 不受影响）、嵌入正文的编号项前换行（`3.14`/`3.5` 小数排除）。
- **对原版的一处改进**：行首 `N.` 判定额外排除点号后紧跟数字（`"3.5倍"` 不再被当编号拆行），与嵌入判定口径对齐（Go 原版此处偏松）；`-` 规则允许隔空白（Go 原版只处理 `-中文`，漏掉更常见的 `"- 负责xx"`）。
- 全部纯函数（`_rejoin_broken_lines` / `_restore_structure` / `_repair_pdf_text` 等），`parse_pdf` 尾部调用，PDF 库无关。

### 3. 明确不抄（范围纪律）

- **多模态图片只注入首条消息**：本项目后端无任何图片输入链路（全文检索 0 命中），没有可挂载的调用点，强行预埋就是该项目式死代码（其 `vision.go` + 后端 image 分支因前端改走 Tesseract 全部不可达）。
- 动态难度调度器 / Skill 状态机 / 薄弱点 EMA：属研读报告 P1 改造项，非本轮范围。

### 4. 测试与契约

- 新增 `tests/test_company_profiles.py`（25 例：加载/匹配/片段生成/会话角色卡集成/坏 YAML 与空目录降级）+ `test_resume_parser.py` 追加 45 例修复用例；全量 **747 例通过**。
- `company_profiles` 注册 L2 层，`.importlinter` 契约同步，`run.py lint` 通过；`requirements.txt` 新增 `pyyaml>=6.0`（缺失时该层整体降级，非硬依赖）。
- 需求文档：[week8_公司风格配置与PDF文本修复_需求.md](docs/week8_公司风格配置与PDF文本修复_需求.md)。

---

## v6.4 竞品借鉴专项五期：HakiMeet 八项落地——长期记忆闭环 + 前端成品感（2026-08-29）

> 对标 [HakiMeet](https://github.com/zhaojunfei/HakiMeet)（Vue3 + FastAPI 语音面试平台）研读后，按《[HakiMeet-深度研读.md](docs/HakiMeet-深度研读.md)》§7 的 **P1 八项**逐项落地。它的产品感强、工程纪律弱：值得学的是长期记忆闭环可视化与真打断语义，必须规避的是内置 `hash()` 去重键不稳、2D/3D 图谱双轨并存、页面各自复制粘贴样式——本轮落地全部按改进版处理。其中后端四项已随 v6.3 提交窗口先行入库，本节补记完整叙事；前端四项为本节新增。

### 后端（已随 v6.3 窗口入库，此处补记叙事）

1. **RAG 注入去重**：`content_hash()`（blake2b 8 字节，跨进程稳定——HakiMeet 用内置 `hash()` 受 PYTHONHASHSEED 随机化影响，重启即失效）；`resume_retriever.select_context_tracked()` / `knowledge_store.retrieve(exclude_hashes)` / `augment_prompt_tracked()` 贯通去重参数，返回值携带指纹；两条纪律：**先过滤再走字符预算**（被排除的名额不得白占预算）、**耗尽必须回退**（长会话后期所有块都已注入，不回退则证据包恒空，去重反致能力退化）。
2. **备选题 / 换题**：会话层登记已问题目台账（文本 + 指纹），出题时以【已问题目清单·严禁重复】负向约束传入 `question_gen`；模型无视约束吐出重复题时，**把那道重复题追加进排除清单重试一次**（给出具体反例比反复强调规则有效，但只重试一次——重试是完整 LLM 往返）。
3. **长期记忆闭环**：`weakness_profile` 幂等迁移补 `resolved` / `updated_at` 列（`CREATE TABLE IF NOT EXISTS` 不会给已存在的表补列，必须 PRAGMA 检查后 ALTER）；新增 `PUT /api/weakness-profile/{id}/resolve`、`GET /api/weakness-profile/{id}/suggestions`（静态段注册在 `/{session_id}` 之前防参数吞并）、`GET /api/weakness-profile/points`；首轮出题回注入历史未解决薄弱点（【历史薄弱点·优先考察】，仅首轮注入一次，后续轮次重复注入是纯 token 浪费）；拉取失败降级为"无历史记忆"，不阻断面试。
4. **测试**：新增 `test_injection_dedup.py`（19 例）/ `test_alternate_question.py`（10 例）/ `test_weakness_memory.py`（17 例），覆盖指纹稳定性、去重与回退、迁移幂等（含老库升级）、resolved 闭环语义、换题重试上限。

### 前端（本轮新增）

5. **Design token 补强**：`tokens.css` 补 `--shadow-xs/xl/inset` 六级阴影、玻璃态 `--glass-*`、`--ease-standard` 微交互缓动（与 `--ease-out` 的"入场"语义区分）；`style.css` 落地全局组件类 `card-hover / btn-press / stat-chip / glass-panel / empty-state 三件套 / confirm 弹窗 / btn-danger`——页面不得各自重写（对应 HakiMeet"视觉统一、实现复制"的反面教材）。
6. **长期记忆页 + 2D SVG 记忆图谱**（新文件 `memoryGraph.js` + `pages/memory.css`）：中心"薄弱点图谱" → 维度环形分布 → 子节点确定性哈希散开（FNV-1a 种子，**刷新不跳位**）；节点颜色 = 严重度×未解决率（红/橙/蓝/灰四级，token 化深色自适应）；SVG 二次贝塞尔连线、hover 节点↔明细项双向联动、点击节点滚动定位明细；平移缩放走 transform 合成层（缩放不重算路径）；每维度最多渲染 6 个子节点（超出聚合 +N）；**只做 2D 一套**（HakiMeet 2D/3D 双轨并存是维护负担）。标记已解决即退出回注入与建议口径——闭环收敛动作。
7. **面试页状态机收敛 + 语音真打断**：`interview.js` 收敛为 `PHASE` 四态 + `setPhase()` 单一入口（副作用如状态灯统一驱动），锁定/恢复 4 条路径统一走 `setInputLocked()`（保留"超时保留草稿 / 拦截清空聚焦"等语义差异）；删除三个死状态（`pendingFollowUp` 无读取、`currentInterviewerName` 无读取、`autoReadEnabled` 无写入恒真）；修复 `connectWS` 重置不全（补 voiceState/计时器/思考计时，防第二场面试继承污染）与 `finishInterview` 后 `ws` 未置空（旧 socket 静默吞消息）。`voice.js` 引入语音世代号：`stopSpeaking()` 先摘 `onended` 回调再 pause（HakiMeet `flush()` 同类缺陷的教训），修复 `browserSpeak` 对 canceled/interrupted 也触发 `onEnd`、以及打断后 MiMo 失败误降级续播；`autoReadQuestion` 打断时仅复位 UI 不触发连锁动作。
8. **Onboarding 细节**：题库页"📄 模板"一键下载（内联字段说明 + 真实示例题，Blob 触发）、空状态三件套接入题库页与记忆页、全局 Promise 化确认弹窗（删除薄弱点等不可逆操作二次确认）。

### 工程化
- 全量 **655 例通过**、`run.py lint` 分层契约通过；前端零新依赖（图谱为原生 SVG/DOM）。
- 文档：研读报告 §7 八项落实状态逐条标注。

### 范围与约束（诚实披露）
- `knowledge_store` 的 tracked 去重接口仍是**前向储备**：业务检索当前只走 `ResumeRetriever` 一线，`augment_prompt_tracked` 暂无生产调用方（接口就绪，待职业规划/出题知识注入接线）。
- 图谱子节点每维度最多 6 个（超出聚合 +N）；<768px 收起图例、双击复位代替滚轮缩放。
- **Realtime 语音（研读报告 P2-9）明确不做**：端到端实时语音会让 `output_sanitizer` 与结构化评分无处挂载，与 v6.2 以来的核心优势冲突，如需引入应单独立项并配"转录后离线评分"兜底。

---

## v6.3 竞品借鉴专项四期：mock-interviewer 七项能力落地（2026-08-28）

> 对标 [crowscc/mock-interviewer](https://github.com/crowscc/mock-interviewer)（Agent Skills 开放标准的纯 Prompt 技能包，零代码，4 个 Markdown 文件）研读后，按《[mock-interviewer-深度研读.md](docs/mock-interviewer-深度研读.md)》第 10 节的 **P0 三项 + P1 四项**逐项落地。
>
> 与前三期最大的不同：前三期借鉴的是**工程模式**（状态机、收尾强控、输出净化、JSON 容错），本期的对象**没有一行代码**，借鉴的是**内容资产**——面试官角色卡、锚点分类、追问范式、压力题库、评分 rubric。因此本轮改动以「数据结构 + Prompt 注入 + 确定性规则」为主，引擎控制流基本未动。新增测试 50 例，受影响面 326 例全绿，分层 lint 通过。

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
   - 采纳原书一条高性价比判断：**简历中出现的每个数字都是高价值追问点**（metric 类对数字加权）。
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
   - **assisted 标记**：原书做法是"教练对话不计入评分"，本项目**不做不计分**（评分是连续诊断链路的一部分，剔除会打断数据流），改为**标注**：分数照记，报告 `assistance_stats` 披露"全场有多少题是在提示下完成的"。占比过高本身就是诊断信号——说明当前难度/方向与该候选人不匹配。

### 工程化
- **测试**：新增 `tests/test_mock_interviewer_borrowings.py`（50 例，覆盖角色卡完整性/追问 prompt 双自由度/锚点分类与兜底/加减分项各规则与封顶夹紧/JD gap 注入/压力题三道闸门与去重/恢复红线与阈值/assisted 标记与报告统计）；受影响面 326 例全绿，`run.py lint` 分层契约通过。
- **配置**：新增 `JD_GAP_SCORE_THRESHOLD`、`JD_GAP_MAX_ITEMS`、`PRESSURE_QUESTION_ENABLED`、`PRESSURE_MAX_PER_SESSION`、`PRESSURE_PROB_BY_ATTACK_LEVEL`。
- **契约**：`.importlinter` L2 层补登 `output_sanitizer`（此前遗漏）、`resume_anchors`、`pressure_bank`、`score_adjustments`。

### 修复
- `tests/test_weakness_memory.py` 9 例失败修复：`weakness_profile.session_id` 有外键指向 `sessions(id)`，而测试的 `_seed()` 直接写子表未落父记录，导致 `FOREIGN KEY constraint failed`。新增 `_ensure_sessions()` 补齐父记录并开启 `PRAGMA foreign_keys`。属**既有缺陷**（v6.3 长期记忆闭环引入），与本轮改动无关，修复后 17 例全绿。

### 范围与约束（诚实披露）
- **维度映射是近似的**：原作四维度含「表达结构」「应变能力」，本项目五维度（宪章约束 3）无对应项，故「甩锅」「过度防御」等应变类信号只能就近映射到 STAR 完整度 / 逻辑连贯性，语义上并非严格等价。
- **存在双重惩罚风险**：模型若已因"没有数据"把量化程度打到 3 分，规则再 -1 即构成"模型与规则各扣一次"。缓解手段是封顶机制（非消除），换取的是可解释性；若模型已打到 1 分则夹紧后无额外惩罚。
- **压力题前端标识**：`question` 消息透传 `is_pressure` / `pressure_topic`，前端 `showQuestion` 渲染「⚡ 压力题 · 类别」徽章（红色系但克制——提示"这是一道意外的问题"，不是警告用户答错了）。
- `jd_gaps` 使会话创建多一次 LLM 往返（仅当有 JD 时）。失败静默降级为无缺口模式，不阻断会话创建。

---

## v6.2 竞品借鉴专项三期：GrillMind 六项工程模式落地（2026-08-28）

> 对标 [GrillMind](https://github.com/1935417243/GrillMind)（React 19 + Electron + 阿里百炼 ASR/TTS 全双工语音）研读后，按《[GrillMind-深度研读.md](docs/GrillMind-深度研读.md)》第 9 节的 6 条建议逐项落地。原则延续前两期：**只借工程模式，不抄技术栈**——不引入 Electron 桌面壳（本项目定位 Web 服务平台），全双工语音不引入 WebSocket 音频流（MiMo 云端 ASR 为请求-响应协议，改造为流式需自研网关），改为在半双工链路上补齐 VAD 节流与"TTS 结束自动切回文字"这两个体验缺口。新增测试 50 例，全量 **559 例通过**、分层 lint 通过、前端 `vite build` 通过。

### 新增（功能线）

1. **面试状态机 closing 收尾强控**（借鉴点 1）
   - `config`：`INTERVIEW_ROUNDS` 末轮「反问收尾」与 `TRADITIONAL_ROUNDS` 末轮「自定义环节」新增 `closing: True`；新增 `CLOSING_INSTRUCTION`（内部收尾指令）与 `CLOSING_MESSAGE`（收束语文案，工程层确定性输出，不额外消耗 LLM 调用）。
   - `session`：`is_closing_round()`（轮次计数判定：显式 closing 标记或已推进到末轮）+ `closing_instruction()`；**工程强控** —— 收尾阶段 `should_follow_up()` 恒为 False（连"回答过短强制追问"一并强控）、`generate_extra_question()` 恒为 None。
   - `question_gen.generate_round_questions()` 新增 `closing_instruction` 参数并注入出题 prompt；`main.py` 末轮答完推送 `interview_closing` 事件，前端 `showClosingMessage()` 渲染收尾卡片。
   - 价值：收尾不再依赖模型自决，杜绝最后一题被无限追问拖住。

2. **简历解析前置追问点 deepDivePoints / vaguePoints**（借鉴点 2）
   - `resume_parser` 新增 `extract_interview_points(resume_text, llm_client, jd_text)`：简历解析阶段一次性产出「值得深挖的点」（写了但细节不足，需考真伪与深度）与「可疑/模糊的点」（表述含糊、缺时间或量化）；输出经清洗（去空/去重/去列表符/丢弃超长项/每类上限 5 条）；**全流程降级** —— LLM 异常、正文过短（< `MIN_RESUME_CHARS=50`）、无可用线索一律返回 `{}`，不阻断会话创建。
   - 复用链路：`main.create_session` 提取 → `InterviewSession(resume_points=...)` → ① 出题时经 `build_resume_points_block()` 注入 prompt（补强题不注入，避免上下文冲突）；② 经 `_evidence_for()` 并入诊断证据包，使 `follow_up_question` 也有据可依。

3. **Prompt 输出约束 + 工程净化兜底**（借鉴点 3）
   - 新增 L2 模块 `backend/output_sanitizer.py`：
     - `OUTPUT_CONSTRAINTS`（禁 Markdown / 禁括号动作 / 禁垫词开头 / 纯文本平铺 / 术语保留原样），已注入出题、诊断、改写、追问四处 prompt。
     - `sanitize_spoken_text()` 确定性净化：**先去舞台提示再去 Markdown**（关键顺序——若先剥斜体标记，`*停顿*` 只剩"停顿"二字留在正文）；舞台提示支持括号形式 `（微笑）` 与强调形式 `*停顿*`，用动作词表命中，**不误删 `Redis（缓存）` 这类术语括号**；垫词剥离要求后随标点才生效，避免误伤"好问题，值得展开"。
   - 落点：题目 `question/intent`、诊断 `follow_up_question/overall_comment/real_interview_impact`、`rewritten_answer` 全部净化后再进 TTS 与前端渲染。

4. **任务级模型绑定 + 面试禁思考**（借鉴点 4）
   - `config`：新增 `LLM_TASK_MODELS`（`JSON` 环境变量，值支持 `"model"` 或 `"provider:model"`）、任务枚举 `LLM_TASKS`（parse/question/interview/diagnosis/rewrite/report/career/market）、实时链路集合 `REALTIME_TASKS`、`INTERVIEW_DISABLE_REASONING`（默认开）。解析失败/未知任务/未知 provider 一律跳过并告警，向后兼容（不配即无变化）。
   - `llm_client`：新增 `is_reasoning_model()`、`task_candidates(task)`、`resolve_task_model(task)`；`chat/chat_json/chat_stream/chat_stream_async` 新增可选 `task` 参数，内部候选池按任务解析（绑定模型置顶 → 全局池）。实时链路剔除推理类模型；**若剔除后无候选则保留原池并告警**（宁可慢，也不能无候选导致调用直接失败）。
   - 已接入：question / diagnosis / rewrite / interview（追问）/ parse（简历追问点、JD 权重）/ market（Gap、岗位画像）/ career（职业规划）。

5. **报告结构：qaBreakdown + realInterviewImpact + thinkingSeconds**（借鉴点 5）
   - 诊断 prompt 新增 `real_interview_impact` 字段（"这段回答放到真实面试里会发生什么"），`normalize_result()` 透出；模型未产出时由 `report._fallback_impact()` 按"分数 × 思考时长"确定性兜底（措辞明确为规则结论，不伪装成面试官原话）。
   - `thinking_seconds`：前端记录题目/追问展示到提交的秒数（`elapsedSeconds()`），随 `answer` 上报；后端 `_normalize_thinking_seconds()` 规整（非法值/超 600s 归零），写入 `answer_history` 与诊断记录；追问补充**累加**到本题。
   - `report.build_report()` 新增 `qa_breakdown`（逐题：分数/五维/最薄弱维度/评语/真实面试影响/思考时长/风险点/是否含改写）、`thinking_stats`（均值/最大/最小/总时长/采集题数）、`resume_points`；`detailed_qa` 同步补齐同名字段，前端可复用一套渲染。
   - 前端 `report.js` 新增「📊 逐题拆解」与「🔎 简历追问线索」两张卡片。

6. **语音链路：VAD 节流 + TTS 结束自动切回文字**（借鉴点 6）
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

## v6.1 竞品借鉴专项二期：ASR 容错评分 + 追问引用原话 + 结束面试口令 + 语音 Provider 抽象/缓存预取 + 报告 HTML 导出（2026-08-28）

> 对标 [offerMaster](https://github.com/heatnan/offerMaster)（Next.js 14 + FastAPI + LangGraph 功能节点 + MySQL + 本地 Whisper/Edge TTS）逐文件研读后落地的 5 项可借鉴设计。原则延续 v6.0：**只借工程模式，不抄技术栈**——对方"LangGraph 编排 + REST 状态机驱动"的取舍其核心价值在于"人类语音输入门控下不做全自动 Agent"（本项目 WebSocket 状态机已满足，不再引入 LangGraph）；PDF 报告不引入 weasyprint（GTK/Pango 在 Windows 部署成本高），降级为"HTML 打印模板 + 浏览器 Ctrl+P 即 PDF"。新增测试 18 例、受影响面 127 例全绿、分层 lint 通过。

### 新增（功能线）
- **ASR 转写容错评分（对标 offerMaster 的 ASR-aware 评分 prompt）**：`diagnosis_engine` 新增 `VOICE_TRANSCRIPTION_NOTE`——回答来自语音输入时注入评分 prompt，要求按语义意图理解（"SaaS"→"SARS" 类同音误写不计入专业深度失分、口语停顿词不视为表达混乱、涉及转写误差在评语中注明）。全链路贯通：前端 `answer` 消息新增 `source`（voice/text，`interview.js` 跟踪最近一次输入来源，手动键入自动重置）→ `main.py` WS 解析 `from_voice` → `session.stream_answer()/handle_answer()` 透传 → `_build_diagnostician_system(weights, from_voice)` 注入。
- **追问"引用原话"硬约束（对标 offerMaster FOLLOWUP_DECIDE 的 anti-套路约束）**：`DIAGNOSTICIAN_SYSTEM_PROMPT` 追问要求新增"必须显式引用候选人回答里的具体词汇/数字/项目名，严禁套路式追问"；`session.generate_follow_up()` 的独立生成路径同步加约束。
- **结束面试退出口令（对标 offerMaster rules.py 的 END_KEYWORDS）**：`session.py` 新增 `END_INTERVIEW_KEYWORDS + is_end_signal()`（中英文、大小写不敏感子串匹配，确定性规则不依赖 LLM）；`main.py` WS 在安全检查**之前**检测（口令文本过短会被质量校验拦截），命中后不诊断、不计分，推送 `interview_end_signal` 事件并优雅收束，照常生成部分报告（`user_ended` 标志贯穿三层循环）；前端监听该事件 toast 提示。
- **语音 Provider 协议抽象 + TTS 缓存（对标 offerMaster services/voice.py 的 Protocol 工厂）**：`voice_service` 新增 `TTSProvider/STTProvider`（`runtime_checkable Protocol`）+ `get_tts_provider()/get_stt_provider()` 工厂（`VOICE_TTS_PROVIDER/VOICE_STT_PROVIDER` 配置选择，未知值回退 mimo 并告警）；`VoiceService.synthesize` 新增 **LRU 缓存**（`TTS_CACHE_MAX=32`，仅缓存成功结果，线程安全）——重听题目、追问预取、探测包不再重复付费合成。
- **TTS 预取（对标 offerMaster 的后台预合成延迟优化）**：`voice.js` 新增 `prefetchTTS()`（静默失败，不播放），新题/追问到达即后台合成预热缓存，用户点朗读/开自动朗读时零等待；`report.js` 新增「🖨 打印 / 存为 PDF」按钮。
- **复盘报告 HTML 导出（对标 offerMaster report_pdf.py 的 MD→HTML 模板渲染）**：`main.py` 新增 `GET /api/reports/{session_id}/export.html`——`markdown` 库渲染（tables/fenced_code 扩展）+ 内置打印样式模板（中文字体栈、表格/引用样式、`@media print`），浏览器打开后 Ctrl+P 即得 PDF；依赖新增 `markdown>=3.5`。

### 工程化
- **测试**：新增 `tests/test_offer_master_borrowings.py`（18 例：退出口令/prompt 注入与约束/TTS 缓存命中·音色隔离·LRU 淘汰·失败不缓存/Provider 协议与回退/HTML 导出 404 与渲染）；`test_voice_service` 等既有用例零破坏。

### 范围与约束
- 结束口令仅检测**主回答位**（追问补充位不检测）；命中即收束，当前轮未答题不计入报告。
- 语音 Provider 注册表当前仅 `mimo` 一个实现，工厂为前向接缝（接入火山/豆包等只需登记实现类）。
- TTS 缓存按"文本+音色"为键，命中依赖文本完全一致；`MIMO_TTS_STYLE` 变更不会使缓存失效（风格仅影响首条 user 消息，实际可忽略）。

---

## v6.0 竞品借鉴专项：Prompt 硬约束 + 评分同轮三态决策 + JSON 四级容错 + Provider 自动探测 + 命名空间知识库 + 音色映射表（2026-08-28）

> 对标 [career-copilot](https://github.com/peeker-tao/career-copilot)（React + NestJS + Prisma/PostgreSQL + Redis）逐项深度学习后落地的 6 项可借鉴设计。原则：**只借工程模式，不抄技术栈**（对方用 Redis+向量 RAG，本项目按"零托管依赖"宪章降为本地关键词实现）；市场数据实时性、真实流式、语音实时性三项本项目本就领先，不在借鉴范围。全量测试 491 例全绿、分层 lint 通过。

### 新增（功能线）
- **出题/诊断 Prompt 硬约束（对标 interview.system.ts）**：`question_gen.get_question_gen_system_prompt()` 新增 4 条约束——只出题不替答、`question_type` 枚举（knowledge/project/behavior）、easy→mid→hard 难度递进、5-8 轮整场意识；`DIAGNOSTICIAN_SYSTEM_PROMPT` 补"连续追问不得超过 2 次"（与 `FOLLOW_UP_MAX_COUNT=2` 双保险）。
- **评分同轮三态决策（对标 nextAction）**：Diagnostician JSON schema 新增 `next_action`（`follow_up` / `next_question` / `complete`），评分与"追问/推进/收束"一次调用产出；`normalize_result()` 规整三态（非法值由追问文本推导，空值交会话层兜底）；`session.should_follow_up()` 采信模型推进决策——`next_question/complete` 且无追问文本时低分不再强制追问，但**回答过短仍强制追问**（防敷衍被放行），未声明时走原阈值规则（向后兼容）。
- **JSON 四级容错提取（对标 safeJsonParse）**：`llm_client.safe_json_extract()`——L1 直接解析 → L2 字符串感知提取配平 `{}` 块（兼容围栏/前后缀文本）→ L3 字符级修复（字符串内裸换行/未转义引号启发式判定/截断补闭合引号与括号）→ L4 宽松解析（尾逗号/值位单引号/True-False-None-undefined 字面量），并规避 `it's` 类正文撇号误伤。`chat_json` 的候选可用性判定与最终解析均走四级容错（轻微畸形输出就地修复，不再浪费一次 fallback 候选）；`diagnosis_engine._extract_json` 委托同源实现。
- **Provider 注册表自动探测（对标 PROVIDER_REGISTRY / createProvider）**：`validate_api_key` 下沉 `config`（`llm_client._api_key_issue` 保留别名兼容测试）；新增 `AI_PROVIDER=auto`——按 `AI_PROVIDERS` 注册顺序探测第一个 Key 有效的后端，未知值回退 deepseek；`LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_FALLBACK_CHAIN` 全部跟随 `AI_PROVIDER_RESOLVED` 解析；`switch_provider` 支持 `auto` 并在目标 Key 无效时告警。默认值 `deepseek` 不变，零行为破坏。
- **命名空间知识库（对标 SimpleRagService / augmentCall）**：新增 L2 模块 `backend/knowledge_store.py`——`rag:interview / rag:career / rag:resume` 命名空间隔离，复用 `resume_retriever` 分块 + 关键词加权评分（零第三方检索依赖），`augment_prompt()` 把检索块以【参考知识库相关内容】注入 System Prompt（附反幻觉约束，与简历证据包同一口径）；已纳入 `.importlinter` L2 契约（顺带补上此前遗漏的 `voice_service` 与 `resume_retriever` 契约登记）。
- **音色别名映射表（对标 DASHSCOPE_VOICE_MAP）**：`voice_service.VOICE_ALIASES`——OpenAI 风格音色（alloy/echo/fable/onyx/nova/shimmer）与性别简称（male/female）统一映射到 MiMo 预置音色；解析顺序 = 预置音色 → 别名（大小写不敏感）→ 配置默认音色。

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

> 对标 [agent-interview-coach](https://github.com/xiaodeng-lp/agent-interview-coach) 的 interview_corpus / coaching recovery 思路，补齐三块硬短板：(1) **简历证据检索**——新增 `resume_retriever.py` 轻量检索器，为追问与诊断实时产出「本轮证据包」，并用证据硬规则约束诊断模型**只依据简历证据或候选人亲述评价**、严禁编造经历，从机制上杜绝"AI 凭空捏造候选人做过的事"；(2) **不会答恢复（coaching recovery）**——检测到候选人示弱（不会/不懂/没思路…）时切换辅导式引导，而非机械继续拷打；(3) **薄弱点跨轮累计**——把各轮诊断的薄弱标签跨轮聚合，实时面板 + 报告沉淀「今日弱点」。另支持会话中动态切换模式/阶段（simulation / traditional / coach / hardcore / interview_only × phone_screen / tech_round_1 / tech_round_2 / hr）。新增/重写测试 61 例（session 状态机 + resume_retriever），分层 lint 通过。

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

> 按用户定案 B 档（子模块内嵌），将开源项目 job-crawler 的 Playwright 采集核心整合进本系统，新增第 6 个"市场数据"Tab，复刻其纸墨印章设计语言（米色纸张 + 衬线 + 印章红）。**后端其余契约零变更**；291 测试全绿、分层 lint 通过。

### 新增（功能线）
- **实时采集**：关键词 + 省份→城市级联多选（≤5 城市）+ 排序（相关性/最新发布）+ 页数 1~5；后台线程执行 `scrape_jobs()`，前端 1.5s 轮询进度（当前城市/页数/累计条数/进度条）；采集结果经 `adapters.to_standard_job()` 直通 `store.upsert_jobs()` 回灌 `market.db`。
- **岗位库**：统计概览（岗位总量/平均薪资/热门技能 TOP5/样本城市）+ 筛选（关键词/城市/学历/薪资区间）+ 纸感表格（编号角标/悬停浮起/行勾选）+ 分页。
- **岗位详情**：全屏独立视图（还原 job-crawler job_detail 结构），展示完整描述/标签/薪资/经验/学历/发布时间，**支持跳转 51job 原文**，可一键用本岗位做 Gap 分析。
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
基于 job-crawler 项目的安全实践补充：
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
