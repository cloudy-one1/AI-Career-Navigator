
<h1 align="center">🤖 AI 模拟面试官与职业规划</h1>

<p align="center">
  <strong>v7.1 — 全站 UI 统一「纸墨印章」：Design Token 重映射 / 手动双主题 + 语义色切换 / 市场数据 DOM 级复刻 / 全国范围采集 / 岗位收藏持久化</strong>
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
  支持简历解析、双 Agent 诊断、流式反馈、语音交互、题库管理、职业路径规划
</p>

---

## 📖 项目简介

AI 模拟面试官是一个面向求职者的智能面试练习平台。上传简历后，AI 会模拟大厂面试流程（6 阶段拟真模式 / 5 轮次传统模式），围绕 **STAR 完整性、量化程度、逻辑连贯性、岗位相关性、专业深度** 五个维度进行实时诊断，提供改写建议和综合评分报告。

### 核心亮点

- **全站 UI 统一为「纸墨印章」风格（v7.1）**：11 个 Tab 统一视觉语言（功能布局与 DOM 结构不变）——`tokens.css` 变量名保持、仅重映射色值（印章红 / 米纸 / 墨色 / 青绿 / 黄铜），约 50 处字面 `rgba()` 改 `rgba(var(--primary-rgb), α)` 双主题自动跟随；设计规格沉淀为 `docs/job-crawler-UI设计系统规格.md`，后续改造以此为唯一基线
- **手动双主题 + 语义色切换（v7.1）**：新增 `themeToggle.js` + `theme.css`，主题由跟随系统改为**手动切换 `html.theme-dark`**（localStorage 记忆、内联脚本防 FOUC、派发 `theme:changed`），深色下可切青/粉/金/紫语义色；废弃 `pages/dark.css` 中 Indigo 时代的硬编码修正，消除深浅割裂
- **市场数据 Tab DOM 级 1:1 复刻（v7.1）**：采集/列表/详情三视图对齐开源项目 job-crawler（省份→城市级联 + 已选 `tag-chip`、`.data-row` 整行上浮点击跳详情、`data-no` 角标 + `.stamp` 印章 + `.alert` / `.fade-up` 入场动效），增强能力（跨岗位对比 / 统计概览 / 学历薪资筛选 / Gap 分析）全部保留；`market.css` 清理死代码 597 行
- **市场采集放开全国范围 + 收藏持久化（v7.1）**：`POST /api/market/crawl` 的 `cities` 改为可选（不传 = 全国搜索，底层本就支持）；新增 `job_postings.is_interested` 字段（含 `PRAGMA` 幂等迁移）+ `POST /api/market/jobs/{id}/interest`，「感兴趣」由 localStorage 升级为落库，重新采集不清空收藏
- **双端平台化（v7.0）**：轻量认证（bcrypt + JWT，可关闭开关 `AUTH_ENABLED=false` 回退旧行为）+ 资源归属（会话/简历/岗位按 owner 隔离，WebSocket 握手校验身份）+ **报告分享链接**（招聘者免登录只读，输出侧强制脱敏手机号/邮箱/身份证，可撤销/可设有效期/带访问计数）+ **简历库/岗位库**（跨会话复用，不必重复上传与解析）
- **诊断证据引用（v7.0）**：五维评分每维度附 `quote`——从候选人回答中原样摘录的支撑片段（≤30 字），把主观打分锚定到可复核的文本证据
- **流程状态显式化（v7.0）**：面试推进决策收敛为纯函数 `decide_next(FlowSnapshot)`（无 IO 可单测），流程位置（出题/追问/推进/结束）落库可追溯
- **全新 UIUX（v4.0）**：三步引导准备 Setup + 双栏面试工作台（对话流 + 固定诊断面板）+ 复盘态诊断卡（环形总分/原文改写对照）+ 报告 Dashboard + 深色主题（v7.1 起改为手动切换）
- **Vite 工程化（v4.0）**：Design Tokens 四层 CSS 架构 + 左垂直导航（桌面/平板/移动三态自适应）+ npm 开发/构建脚本
- **市场数据 Tab（v4.1）**：B 档内嵌 Playwright 实时采集（省份→城市级联多选 + 进度轮询，采集自动回灌 market.db）+ 岗位库检索统计 + 全屏岗位详情（跳转 51job 原文）+ 单选 Gap 分析 / 多选跨岗位对比；[v7.1] 视图已 DOM 级复刻 job-crawler，主题统一由全局切换器控制
- **MiMo 云端语音（v4.2）**：后端代理 mimo-v2.5-tts（合成）+ mimo-v2.5-asr（识别，官方 chat/completions 协议），前端双引擎自动降级，录音用 MediaRecorder，密钥仅存后端不泄漏
- **双 Agent 诊断引擎**：Diagnostician（诊断）+ Rewriter（改写）独立协作，非单一评分
- **动态维度权重**：根据 JD 自动调整各维度权重 + SHA256 缓存，诊断更贴合岗位
- **流式诊断反馈**：WebSocket 实时推送诊断结果、追问、雷达图数据
- **7 种面试官角色**：友好/严格/压力/专业/好奇/质疑/鼓励型自动切换
- **双模式面试**：拟真 6 阶段（破冰→技术广度→技术深度→项目拷问→行为面→反问）+ 传统 5 轮次
- **语音交互（v4.2 升级）**：小米 MiMo 云端语音优先（TTS 朗读 + ASR 语音转文字），未配 Key / 失败自动降级浏览器原生 Web Speech API，语音作为输入输出替代层不参与诊断内核
- **Gap 分析**：简历-岗位六维度透明匹配（技能/城市/学历/经验/薪资/可信度），含市场基准参照
- **跨岗位对比**：一份简历同时对比多个 JD，输出排名与择岗建议
- **职业规划路径**（v3.2）：以 Gap 六维快照为基线，LLM 推理多阶段时间轴路径（需补技能/里程碑/岗位跃迁），替代横截面打分
- **分层依赖强制**（v3.2）：import-linter 契约（L1-L4）确定性拦截所有 import 越层，`run.py lint` 一键校验
- **岗位画像研究**：DuckDuckGo 搜索 + LLM 分析，自动丰富 JD 背景
- **市场数据注入**：出题时自动注入市场行情（热门技能/薪资分位/学历分布）
- **Web 层限流**：slowapi 频率限制 + 安全响应头 + 请求体大小限制（降低滥用，非安全边界）
- **启发式内容检查**：基于关键词/正则拦截最幼稚的注入尝试（非安全边界，可被绕过；详见「已知局限」）
- **多 AI 后端**：DeepSeek / 通义千问 / 智谱 GLM / OpenAI 可切换
- **模型调用优雅降级（fallback）**：主模型失败（限流/超时/不可用）时按 `LLM_FALLBACK_CHAIN` 自动切换备用模型，调用方无感知（v4.3）
- **简历证据检索（v5.0）**：本地关键词 + 优先级加权轻量检索器，为追问与诊断实时产出「本轮证据包」，配合证据硬规则约束模型**只依据简历证据或亲述评价**、严禁编造经历，杜绝"AI 凭空捏造候选人做过的事"
- **不会答恢复（v5.0）**：检测到候选人示弱（不会/不懂/没思路…）自动切换辅导式引导，而非机械继续拷打
- **薄弱点跨轮累计（v5.0）**：把各轮诊断的薄弱标签跨轮聚合，实时面板 + 报告沉淀「今日弱点」，并新增逐题参考答案背诵（修复参考答案恒为空）
- **会话中多模式/多阶段切换（v5.0）**：模拟过程中动态切换模式（simulation / traditional / coach / hardcore / interview_only）与阶段（phone_screen / tech_round_1 / tech_round_2 / hr）
- **Prompt 硬约束 + 三态推进决策（v6.0）**：出题 Prompt 写死题型枚举/难度递进/只出题不替答；诊断与"追问/下一题/收束（next_action）"同一次 LLM 调用产出，会话层只做兜底校验（对标 career-copilot）
- **JSON 四级容错（v6.0）**：LLM 输出解析走 直接解析→提取{}块→字符级修复→宽松解析 四级降级，轻微畸形输出（围栏/截断/尾逗号/单引号）就地修复，不再浪费 fallback 候选
- **Provider 注册表自动探测（v6.0）**：`AI_PROVIDER=auto` 按注册顺序自动选用第一个配置了有效 Key 的后端；Key 校验下沉配置层，切换后端时无效 Key 即时告警
- **命名空间知识库（v6.0）**：`rag:interview/career/resume` 命名空间隔离的本地关键词检索 + `augment_prompt` 注入（零托管依赖，前向储备）
- **ASR 转写容错评分 + TTS 预取（v6.1，对标 offerMaster）**：语音回答自动注入转写容错评分（"SaaS→SARS" 类同音误写不计失分、口语停顿不视为混乱）；新题/追问到达即后台预合成预热缓存（TTS LRU 缓存 + Provider Protocol 工厂抽象）
- **追问引用原话 + 结束面试口令（v6.1，对标 offerMaster）**：追问 Prompt 硬约束"必须显式引用候选人回答原话"，杜绝套路式追问；回答位输入"结束面试"等口令即优雅收束并生成部分报告（确定性关键词检测，不依赖 LLM）
- **报告 HTML 导出（v6.1）**：复盘报告一键导出打印友好 HTML（`/api/reports/{id}/export.html`），浏览器 Ctrl+P 即得 PDF（零重量级依赖）
- **面试收尾工程强控（v6.2，对标 GrillMind）**：末轮按轮次计数判定为 closing 阶段，工程层强制禁止追问与追加题、注入内部收尾指令并推送收束语，面试收尾不再依赖模型自决
- **简历前置追问点（v6.2，对标 GrillMind）**：简历解析阶段即产出「值得深挖的点」与「可疑/模糊的点」，注入出题 prompt 与诊断证据包，让追问有据可依而非临场泛问（LLM 异常/正文过短一律降级为空，不阻断流程）
- **面试话术输出净化（v6.2，对标 GrillMind）**：Prompt 侧注入「禁 Markdown / 禁括号动作 / 禁垫词开头」硬约束，工程侧 `sanitize_spoken_text` 确定性兜底——先去舞台提示再去 Markdown，`Redis（缓存）` 这类术语括号不被误删
- **任务级模型绑定 + 面试禁思考（v6.2，对标 GrillMind）**：`LLM_TASK_MODELS` 按任务（parse/question/interview/diagnosis/rewrite/report/career/market）独立绑定模型；实时面试链路自动剔除推理类模型（首 token 延迟高），离线任务不受限
- **报告逐题拆解（v6.2，对标 GrillMind）**：`qaBreakdown` 逐题呈现分数/五维/最薄弱维度/风险点，附 `realInterviewImpact`（对真实面试的影响，模型未产出时按规则兜底）与 `thinkingSeconds`（每题思考时长，前端计时上报、追问累加入本题）
- **语音 VAD 节流 + 朗读结束切回文字（v6.2，对标 GrillMind）**：录音期间采样音量，连续静音 2.5s 且已采集到语音即自动停录并转写（2 分钟硬上限兜底）；题目/追问朗读结束自动聚焦输入框，用户始终落回可打字状态
- **面试官角色卡三件套（v6.3，对标 mock-interviewer）**：7 种风格各补 `perspective`（视角独白）/ `followup_chain`（追问链）/ `never_ask`（**不会问**负向清单），`get_interviewer_role_prompt()` 拼装完整角色卡——让角色"不问什么"也有硬边界，而非靠模型自觉发挥
- **简历锚点五分类（v6.3）**：新增 `resume_anchors.py`，把简历值得追问处由 deep/vague 二分升级为技术选型/量化数据/架构设计/业务决策/团队管理五类，每类绑定追问方向；LLM 分类 + 关键词规则双路径互为兜底，数字自动加权
- **评分规则化加减分项（v6.3）**：新增 `score_adjustments.py`，10 条确定性正则规则（6 扣 4 加），**每条修正带 evidence 原文片段**，解决纯 LLM 评分"不可解释/不可复现"；三重封顶（单题扣分≤3/加分≤2/单维度≤2）+ 夹紧 [1,5]，只作用于已评分维度
- **JD gap 出题优先级显式注入（v6.3）**：低于 `JD_GAP_SCORE_THRESHOLD` 的 JD 维度作为缺口注入出题 prompt，优先级链 **JD gap（必问）> JD 强匹配（验证）> 简历锚点（补充）**，纠正"模型顺简历走"的偏差；缺口无经历时改用假设/迁移问法
- **压力题库随机注入（v6.3）**：新增 `pressure_bank.py`，5 类 16 道与简历/JD 解耦的压力题；全局开关 + 整场限量 1 + 破冰/收尾轮不注入 + 按 `attack_level` 抽签（友好/鼓励型概率为 0），补"内容层压力"
- **恢复红线 + 连续 3 次阈值 + assisted 标记（v6.3）**：coaching 红线**绝不给答案**（工程兜底 `contains_answer_leak`）；连续 3 次触发主动建议跳过（可突破追问上限）；assisted 标记在报告披露"多少题在提示下完成"，占比过高即诊断信号
- **长期记忆闭环（v6.4，对标 HakiMeet）**：薄弱点带 `resolved` 标记形成"练 → 评 → 记 → 再练"收敛——首轮出题回注入历史未解决短板（【历史薄弱点·优先考察】），标记已解决即退出回注入与复习建议口径；幂等迁移老库无感升级，拉取失败降级不阻断面试
- **2D SVG 记忆图谱（v6.4，对标 HakiMeet）**：新增"长期记忆"页，中心→维度→薄弱点三级贝塞尔图谱；节点位置由 id 哈希确定性生成（刷新不跳位）、颜色 = 严重度×未解决率；平移缩放走 transform 合成层；图谱与明细栏双向联动，零前端依赖（刻意不做 2D/3D 双轨）
- **RAG 注入去重 + 备选题（v6.4，对标 HakiMeet）**：会话级指纹缓存（blake2b 稳定摘要，非内置 hash）让同一段简历证据不再反复拼进 prompt；换题时把已问题目清单作为负向约束注入，重复题带样本重试一次
- **语音真打断 + 状态机收敛（v6.4，对标 HakiMeet）**：语音世代号守卫——打断先摘回调再停止，修复"打断后仍触发结束回调 / 误降级续播"；面试页收敛为 PHASE 四态 + setPhase 单一入口，锁定/恢复统一走 setInputLocked
- **前端成品感补强（v6.4）**：token 层补六级阴影/玻璃态/标准微交互缓动；空状态三件套、题库模板一键下载、全局 Promise 化确认弹窗——组件类一律走全局层，页面不得各自重写
- **目标公司风格配置层（v6.5，对标 interviewerAgent）**：`backend/company_profiles/*.yaml` 热加载（加文件即加公司、零改码），公司人格 + 轮次指令 + 评估量表三层注入；内置字节/腾讯/阿里三份种子配置，支持 JD 关键词自动匹配与前端选择器，pyyaml 缺失/坏文件自动降级不阻断面试
- **PDF 文本两阶段修复（v6.5，对标 interviewerAgent）**：`parse_pdf` 输出先逆拼接（仅编号项/全大写标题为硬断信号）再复原断行（中文章节词表/`·`/`-`+CJK/嵌入编号项，排除 `3.14` 小数与 `2023-09` 日期），修复列宽切碎与标题粘连两类损伤，纯函数可单测
- **长期薄弱点 EMA 衰减 + 过期淘汰（v6.6，对标 interviewerAgent）**：长期记忆不再裸计数——EMA 加重（α=0.4）/ 高分减轻（×0.7）/ 30 天未再失分自然淘汰 / 中性区不动，并按 JD 维度权重放大（岗位越看重的短板越要命）；回注入按"加权薄弱度"排序并标注"累计失分 N 次"
- **面试技能状态机（v6.6，对标 interviewerAgent）**：补上"临时插入、有步骤、有完成条件"的能力层（区别于整场生效的面试模式）——快速测验 / 概念讲解 / 技术对比三个内置技能，走完自动退回正式面试；技能轮不进诊断，避免测验答案污染评分
- **动态难度调度（v6.6，对标 interviewerAgent）**：按诊断加权总分做轮内难度自适应（连续 2 次达标升档 / 失手降档，1-5 档）；难度**不参与阶段推进**（归 v6.2 工程强控），并逐题记录难度轨迹进报告、变档实时推送，解决"分数变低是能力下降还是难度升高"的归因问题
- **题库管理**：CRUD + 收藏 + 从面试会话导入
- **Docker 部署**：Dockerfile + docker-compose.yml 一键部署
- **自动化测试**：约 900 个测试用例覆盖核心路径（含依赖 API Key 的 LLM 类测试；v7.0.3 起新增黄金样本回归）

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

# 4. 安装 Playwright 浏览器（v4.1 市场数据 Tab 实时采集需要；跳过则实时采集不可用，岗位库检索/Gap 分析/跨岗位对比不受影响）
python -m playwright install chromium

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key（至少配置一个 AI 后端）
# 可选：填入 MIMO_API_KEY 启用小米 MiMo 云端语音（更自然的朗读 + 跨浏览器语音识别）；不配置则自动使用浏览器原生语音
# MiMo 端点：https://api.xiaomimimo.com/v1（sk- 开头 Key 走按量付费集群）；TTS/ASR 均按官方 chat/completions 协议调用
# 可选音色：MIMO_TTS_VOICE=冰糖（默认）/ 茉莉 / 苏打 / 白桦 / Mia / Chloe / Milo / Dean

# 6. 启动服务
python run.py
```

前端开发模式（v4.0，可选，提供热更新）：
```bash
cd frontend
npm install
npm run dev     # http://localhost:5173（自动代理 /api /ws /upload 到 :8000）
npm run build   # 产出 dist/，由 FastAPI 托管（http://localhost:8000）
```

启动后访问：
- 🎯 **面试页面**：http://localhost:8000（生产构建）或 http://localhost:5173（开发热更新）
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
AI_PROVIDER=deepseek        # deepseek / qwen / zhipu / openai / auto（v6.0：auto=按注册顺序自动探测第一个 Key 有效的后端）

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

# 模型调用优雅降级（fallback，可选，v4.3）
# 主模型失败(限流/超时/不可用)时按序自动切换备用模型，调用方无感知
# 格式: "provider:model,provider:model,..."；留空=不降级(单模型)
# qwen-plus 与 deepseek-chat 能力相当(通用对话主力)，作备用首选
# LLM_FALLBACK_CHAIN=deepseek:deepseek-chat,qwen:qwen-plus
# LLM_FALLBACK_MAX_RETRIES=3
```

---

## 🏗️ 项目结构

```
AI-simulated-interviewer/
├── run.py                        # 一键启动入口 + lint 子命令（import-linter）
├── CHARTER.md                    # [v3.2] 不变宪章：架构约束/决策记录卡/已知局限
├── CHANGELOG.md                  # [v3.2] 版本迭代叙事
├── .importlinter                 # [v3.2] 分层依赖契约（L1-L4）
├── Dockerfile                    # 容器镜像（课程项目级）
├── docker-compose.yml            # Docker Compose 部署
├── .dockerignore                 # 容器构建忽略清单
├── requirements.txt              # Python 依赖（含 dev 依赖 import-linter）
├── .env.example                  # 环境变量模板
│
├── backend/                      # Python 后端
│   ├── main.py                   # FastAPI 入口 + HTTP/WebSocket 路由 + 频率限制
│   ├── config.py                 # 配置 + 面试官风格 + 轮次定义
│   ├── logger.py                 # 集中日志配置（RotatingFileHandler）
│   ├── llm_client.py             # 多 AI 后端客户端（含流式）
│   ├── db.py                     # SQLite 多表操作（aiosqlite）+ JD 权重缓存表
│   ├── schemas.py                # Pydantic 数据模型（含跨岗位对比）
│   ├── security.py               # 启发式内容检查（课程项目级，非安全边界）
│   ├── diagnosis_engine.py       # 双 Agent 诊断引擎
│   ├── dimension_weights.py      # JD 动态维度权重（含 SHA256 缓存）
│   ├── gap_analyzer.py           # 简历-岗位 Gap 分析 + 市场基准参照
│   ├── career_planner.py         # [v3.2] 职业路径规划（以 Gap 为基线做多阶段推理）
│   ├── question_gen.py           # 问题生成（含市场数据注入）
│   ├── question_bank.py          # 题库 CRUD 管理
│   ├── resume_parser.py          # 简历解析（PDF/DOCX/TXT）+ [v6.5] PDF 两阶段文本修复
│   ├── web_research.py           # 岗位画像研究（DuckDuckGo）
│   ├── data_support.py           # 技能匹配数据
│   ├── skills_data.json          # 岗位技能静态数据
│   ├── market/                    # [v3.0] 市场数据子包
│   │   ├── __init__.py
│   │   ├── cleaner.py            # 数据清洗
│   │   ├── importer.py           # 外部数据导入
│   │   ├── service.py            # 导入编排 + 岗位快照检索
│   │   ├── store.py              # 数据持久化
│   │   └── crawler/              # [v4.1 NEW] B 档内嵌实时采集（Playwright）
│   │       ├── python_job_scraper.py   # job-crawler 采集核心（相对导入改造）
│   │       ├── salary_parser.py        # 薪资解析
│   │       ├── adapters.py             # 采集记录 → 标准 job dict + JD 组装
│   │       └── tasks.py                # 后台任务表（互斥/进度/TTL 清理）
│   ├── voice_service.py          # [v4.2 NEW] MiMo 云端语音代理（TTS 合成 + ASR 识别）
│   ├── resume_retriever.py       # [v5.0 NEW] 简历证据检索器（分块/加权/预算/证据包）
│   ├── output_sanitizer.py       # [v6.2 NEW] 面试话术输出净化（禁 Markdown/舞台提示/垫词，L2）
│   ├── resume_anchors.py         # [v6.3 NEW] 简历锚点五分类（技术选型/量化/架构/业务/团队，L2）
│   ├── score_adjustments.py      # [v6.3 NEW] 评分规则化加减分项（确定性正则 + evidence，L2）
│   ├── pressure_bank.py          # [v6.3 NEW] 压力题库（5 类 16 道，与简历/JD 解耦，L2）
│   ├── auth.py                   # [v7.0 NEW] 轻量认证（bcrypt + JWT，AUTH_ENABLED 可关，L2）
│   ├── share_access.py           # [v7.0 NEW] 报告分享凭据（高熵 token + SHA-256 摘要存储，L2）
│   ├── company_profiles.py       # [v6.5 NEW] 公司风格配置层（YAML 热加载/JD 匹配/片段生成，L2）
│   ├── company_profiles/         # [v6.5 NEW] 公司风格 YAML（内置字节/腾讯/阿里，加文件即加公司）
│   ├── weakness_memory.py        # [v6.6 NEW] 长期薄弱点 EMA 衰减 + 过期淘汰（L2）
│   ├── difficulty.py             # [v6.6 NEW] 动态难度调度器（轮内自适应，L2）
│   ├── interview_skills.py       # [v6.6 NEW] 面试技能状态机（有状态多轮，L3）
│   └── interview_engine/         # 面试引擎子包
│       ├── __init__.py
│       ├── session.py            # 核心状态机
│       ├── flow.py               # [v7.0 NEW] 流程状态显式化（decide_next 纯函数）
│       └── report.py             # 综合报告生成
│
├── frontend/                     # 原生 ES Module 前端（Vite 工程化）
│   ├── index.html                # SPA 骨架
│   ├── package.json / vite.config.js
│   └── src/
│       ├── js/
│       │   ├── app.js            # 主入口 + Tab 切换（含市场数据分支）
│       │   ├── api.js            # HTTP + WebSocket 封装（含市场采集/城市映射/岗位详情）
│       │   ├── interview.js      # 面试流程控制
│       │   ├── liveRadar.js      # 实时五维雷达图
│       │   ├── report.js         # 综合报告 + Gap 分析 + 跨岗位对比
│       │   ├── history.js        # 历史记录
│       │   ├── questionBank.js   # 题库管理界面
│       │   ├── careerPlan.js     # [v3.2] 职业规划 Tab（时间轴 + 阶段卡片 + 技能曲线）
│       │   ├── marketData.js     # [v4.1] 市场数据 Tab（采集/岗位库/详情/分析，v7.1 DOM 复刻 job-crawler）
│       │   ├── memoryGraph.js    # [v6.4] 长期记忆 Tab（2D SVG 薄弱点图谱 + 明细联动 + resolved）
│       │   ├── voice.js          # 语音交互（TTS + STT，v6.4 世代守卫真打断）
│       │   ├── themeToggle.js    # [v7.1 NEW] 全局主题切换器（手动深浅 + 语义色切换）
│       │   └── utils.js          # 工具函数（含 confirm 弹窗 / emptyState 三件套）
│       └── css/
│           ├── tokens.css        # Design Tokens（v7.1 纸墨印章色值重映射 + RGB 三元组）
│           ├── theme.css         # [v7.1 NEW] 主题切换相关样式（html.theme-dark / 语义色切换器）
│           ├── base.css          # reset + 排版
│           ├── components.css    # 框架组件
│           └── pages/            # 领域样式（含 market.css 纸墨印章 / memory.css 记忆图谱）
│
├── tests/                        # 自动化测试（约 900 用例 + 1 live_llm 抽检，本机非 LLM 类全绿）
│   ├── conftest.py               # 共享 fixtures
│   ├── test_schemas.py           # Schema 验证
│   ├── test_api.py               # HTTP 路由集成测试（含安全测试）
│   ├── test_gap_analyzer.py      # Gap 分析器
│   ├── test_dimension_weights.py # 维度权重
│   ├── test_resume_parser.py     # 简历解析
│   ├── test_report.py            # 报告生成
│   ├── test_security.py          # 安全防护
│   ├── test_web_research.py      # 岗位画像研究
│   ├── test_data_support.py      # 技能匹配
│   ├── test_market_cleaner.py    # 市场数据清洗
│   ├── test_market_importer.py   # 市场数据导入
│   ├── test_career_planner.py    # [v3.2] 职业规划（schema + 路由 + 降级路径）
│   ├── test_market_crawler_*.py  # [v4.1] 采集适配器 + 后台任务状态机
│   ├── test_voice_service.py     # [v4.2] MiMo 语音服务（key 校验/错误处理/mock）
│   ├── test_voice_api.py         # [v4.2] /api/voice/* 代理路由
│   ├── test_session.py           # [v5.0] 会话状态机（追问/权重/薄弱点/恢复/多模式，49 例）
│   ├── test_resume_retriever.py  # [v5.0] 简历证据检索（分块/命中/预算/溯源，12 例）
│   ├── test_grillmind_borrowings.py  # [v6.2] 收尾强控/追问点/净化/任务绑定/思考时长/逐题拆解（50 例）
│   ├── test_mock_interviewer_borrowings.py  # [v6.3] 角色卡/锚点/加减分/JD gap/压力题/恢复红线（50 例）
│   ├── test_injection_dedup.py      # [v6.4] 注入去重（指纹稳定/先过滤后预算/耗尽回退，19 例）
│   ├── test_alternate_question.py   # [v6.4] 备选题/换题（台账/负向约束/重试上限，10 例）
│   ├── test_weakness_memory.py      # [v6.4] 长期记忆闭环（迁移幂等/resolved/回注入，17 例）
│   ├── test_diagnosis_golden.py     # [v7.0.3 NEW] 黄金样本评测（4 类典型回答确定性回归 + live-LLM 抽检）
│   └── fixtures/golden_answers.json # [v7.0.3 NEW] 黄金样本与人工标注
│
├── docs/                         # 需求文档与周报
│   ├── week1_*.md                # v1 模块需求
│   ├── week2_v2迭代_需求.md       # v2 大版本迭代
│   ├── week3_*.md                # 模块差距分析
│   ├── week4_深化诊断核心_需求.md  # v2.6 深化诊断
│   ├── week5_v3数据层_需求.md     # v3.0 市场数据层
│   └── job-crawler-UI设计系统规格.md  # [v7.1] 全站 UI 改造基线（Token/组件/深色覆盖/页面骨架）
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
| **语音（v4.2）** | 小米 MiMo 云端（TTS/ASR，需 `MIMO_API_KEY`）+ 浏览器 Web Speech API 降级 |
| **简历解析** | pdfplumber + python-docx |
| **岗位研究** | DuckDuckGo 搜索 + LLM 分析 |
| **岗位采集（v4.1）** | Playwright + playwright-stealth（`playwright install chromium`，B 档内嵌 `market/crawler/`） |
| **日志** | logging + RotatingFileHandler（5MB×3 旋转） |
| **部署** | Docker + Docker Compose（跨平台一键部署） |
| **分层校验** | import-linter 契约（L1-L4，`run.py lint` 强制） |
| **测试** | pytest（约 900 用例 + 1 live_llm 抽检，本机非 LLM 类全绿） |

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

## 🔒 内容护栏（启发式，非安全边界）

本系统包含一层**课程项目级的内容护栏**，目的是拦截最幼稚的注入尝试、重复刷屏和明显的流程操控，**不是**一道能被认真对待的安全边界：

| 层级 | 内容 | 性质 |
|------|------|------|
| 频率限制 | slowapi 全局限流 + 高敏感端点独立限流 | 降低滥用 |
| 输入检查（硬） | 角色逃逸 / Prompt 盗取 / 越狱 / 特殊 token 等**高置信**模式 | 正则拦截，可被绕过 |
| 输入检查（软） | "从现在开始""你必须输出"等易误伤句式 | 仅告警，不阻断 |
| 输出检查 | System Prompt 片段泄漏 | 仅记录，不阻断 |
| 状态校验 | 重复回答检测（Jaccard）+ 内容质量校验 | 防刷屏 |
| 记忆防污染 | 检测篡改历史 / 替换简历意图 | 启发式 |
| HTTP 安全头 | x-content-type-options / x-frame-options / x-xss-protection | 纵深防御一角 |

**已知绕过方式**：换说法、错别字、同义词、中英混杂、Base64/拼音/编码变形均可绕过上述正则。生产环境必须依赖**认证/授权 + 服务端可信边界 + 模型侧指令隔离**，而非客户端关键词过滤。

**请求体限制**：简历上传 10MB，普通请求 1MB。

---

## 👥 双端使用（v7.0）

系统现在同时服务两类角色，共享同一套诊断内核。**登录界面是同一个**（「账户」面板，注册时选身份），登录成功后按身份进入不同的系统：

### 求职者（主端）

1. **注册/登录**（可选）：顶部「账户」面板注册，身份选"求职者"。不登录也能完整使用——登录后简历库/岗位库/历史记录跨设备归集到你的账户下。
2. **建立素材库**：「简历库」上传一次简历（完整入库，不截断）；「岗位库」保存常练的岗位 JD。之后每次开练直接选用，不必重复上传与解析。
3. **开练**：面试面板选择「从简历库选择 / 粘贴上传」与「从岗位库选择 / 粘贴 JD」→ 开始面试。
4. **复盘与分享**：报告页的每维度评分附**候选人原话引用**（quote），可逐条核对"这个分凭什么"；点「🔗 分享给招聘者」——可只生成免登录链接，或填入对方用户名让报告直接进入其收件箱。

### 招聘者（只读端）

- **统一登录**：「账户」面板注册，身份选"招聘者"。登录成功后自动进入招聘者视图——主界面只剩「收到的报告」+「账户」，求职者的练习面板全部隐藏。
- **收到的报告**：求职者分享时填了你的用户名，报告会出现在这里；点开即看（总分、五维雷达、诊断摘要，勾选"含逐题"的还有逐题明细，自动脱敏手机号/邮箱/身份证）。
- **免登录链接仍然可用**：求职者也可只发链接（`/share/{token}`），无需注册即可查看，可撤销、可设有效期。两条通道独立：链接过期不影响已进收件箱的报告。

### 认证开关（部署方须知）

```bash
AUTH_ENABLED=false   # 默认。回退 v6.x 行为：无登录要求、无归属过滤
AUTH_ENABLED=true    # 启用：登录/注册生效，资源按 owner 隔离，WS 握手校验身份
AUTH_SECRET=...      # 可选；不配置时自动生成并持久化到 data/.auth_secret
```

> ⚠️ 开关关闭期间"无认证"**仍然成立**（等同 v6.x），部署方需自行知晓这一前提。

---

## 🧪 测试策略与工程保障（答辩看点）

本项目的测试不是「堆数量」，而是**分层保障 + 评测（eval）**两套机制配合。约 900 个自动化用例全绿，结构如下：

| 层级 | 代表文件 | 守什么 | 为什么必要 |
|------|----------|--------|-----------|
| ① 确定性脚手架不变式 | test_schemas / test_dimension_weights / test_score_adjustments / test_flow / test_output_sanitizer | 纯函数逻辑（Schema、权重、评分加扣分项、状态机、话术净化）一旦被改坏，立刻红灯 | LLM 不可控，但脚手架必须可控——这是「改代码不引入回归」的底线 |
| ② 端到端链路 | test_api / test_session | 简历→出题→诊断→报告全链路；穷尽异常 / 降级 / fallback 路径 | 保证「系统真的跑得通」，而非单个函数对 |
| ③ 安全与边界 | test_security / test_auth / test_share | 注入拦截、越权、分享脱敏、恢复红线 | 课程项目级护栏的可验证证据 |
| ④ 黄金样本评测（eval） | test_diagnosis_golden | **诊断有效性**：最弱维度抓得对不对、加扣分命中没命中、证据引用是否原话 | AI 项目最该测、却最常被忽略——单测验证「工程正确性」，eval 验证「诊断准不准」 |

**为什么这是项目优势（而非负担）：**
- 学生 / 课程 AI 项目普遍「跑通 demo 就交」，测试多为 0–10 条且**零模型质量评测**；本仓库的四层 + eval 体现工业级工程素养。
- 最关键的差异化是 **④ 黄金样本评测**：固定样本 + 人工标注做确定性回归，并用 `live-LLM` 抽检（默认 deselect，需显式开启）做真实模型结构软断言——首次把「诊断准不准」纳入可观测 / 可回归范围。
- 测试已从「锁死 prompt 文案」重构为「从配置取追问链 / 收尾指令做行为断言」，因此**频繁改写提示词不会误红**，测试从「阻挠迭代」变成「允许迭代」。

> 诚实边界：诊断质量最终依赖 LLM，单测验证的是工程正确性；黄金样本 + live-LLM 抽检补齐「诊断有效性」的可观测性，但模型本身的质量仍需人工评审。详见下文「已知局限」。

## ⚠️ 已知局限与架构取舍

本系统定位为**课程项目**，以下局限是已知的、刻意的取舍，而非待修复的 bug：

| 局限 | 说明 | 可选演进方向（未实现） |
|------|------|------------------------|
| ~~**无认证/授权**~~（v7.0 已解决） | v7.0 起提供认证层 + 资源归属（DC-06）；但 **`AUTH_ENABLED=false` 期间仍等同无认证** | 部署时按需开启开关 |
| ~~**WebSocket 无连接身份校验**~~（v7.0 已解决） | 现于握手阶段校验 token；认证关闭时回退旧行为 | 同上 |
| **无断点续答** | v7.0 落库了流程位置与答题数，但进程重启后**不能**从 DB 重建会话续答；已答题与报告不丢，进行中的那道题会丢 | 序列化整个 `InterviewSession`（成本高，暂不做） |
| **全局单例可变状态** | `llm_client`/`diagnosis_engine` 为模块级单例，被所有会话共享、无按会话隔离；多后端高频切换或并发导入下内部 provider 状态存在理论竞态 | 引入按会话隔离的客户端实例或请求作用域依赖（课程项目阶段仅文档披露，不做隔离） |
| **双 Agent 成本** | Diagnostician + Rewriter 每题至少 2 次 LLM 调用，流式下延迟与 token 成本翻倍 | 做单 Agent + 结构化输出（JSON）的对比实验，量化"分 vs 合"的质量/成本权衡后再决策 |
| **模型调用单点故障（已缓解）** | 原仅单模型，任一 provider 故障即硬失败；v4.3 起支持 `LLM_FALLBACK_CHAIN` 优雅降级，主模型失败自动切备用模型，调用方零改动、不影响双 Agent 诊断客观性 | 仍建议为备用 provider 配置独立密钥以保障可用性 |
| **SQLite 扩展性** | 单文件数据库；多 Worker 下 WebSocket 需 sticky session，水平扩展受限 | 换异步 Postgres / 引入连接池；或改用内存态 + 持久化分离 |
| **内容护栏可被绕过** | 见上节，正则过滤防不住认真攻击者 | 见上节演进方向 |
| **测试偏纯函数** | 确定性逻辑（权重/Schema/评分修正）覆盖充分；但**诊断准确性、追问是否抓最弱维度、评分稳定性**依赖 LLM 输出，单测难以验证 | **已实现（v7.0.3）**：黄金样本回归（4 类典型回答 × 确定性断言）+ live-LLM 抽检（默认 deselect），首次把"诊断有效性"纳入可观测范围 |
| **证据检索为本地启发式** | v5.0 简历证据检索是本地关键词 + 优先级加权，非语义向量检索；中文分词粒度受限，同义/模糊表述可能漏命中，仅作证据提示不替代向量库；可调参数为代码级常量未下沉 `.env` | 引入轻量向量库（如 sqlite-vec / faiss）做语义召回；参数下沉配置 |
| **知识库为关键词检索且未接入业务流** | v6.0 `knowledge_store.py` 为命名空间隔离的本地关键词检索（对标向量 RAG 的降级实现），同义表述可能漏命中；v6.4 已补齐 tracked 去重接口（`augment_prompt_tracked`），但业务检索仍只走 `ResumeRetriever` 一线，知识库注入暂无生产调用方 | 接入职业规划/出题的 Prompt 增强；知识规模大时升级向量索引 |
| **next_action 依赖模型自觉** | v6.0 三态推进决策采信模型声明，模型误判"回答合格"时可能少追问；已用"回答过短仍强制追问"硬兜底 + 未声明时回退阈值规则，且追问次数上限不受影响 | 用真实面试样本统计 next_action 与人工判断的一致率后再决定是否提升模型话语权 |
| **参考答案面板未渲染** | v5.0 报告已产出 `detailed_qa`（逐题参考答案）字段，但前端 `report.js` 尚无对应渲染面板，属前后端待对齐 | 在报告 Tab 补逐题参考答案背诵面板 |
| **市场基准数据来源（学术诚信披露）** | Gap 分析的"市场基准参照"数据来自本人此前已完成并提交的采集项目（job-crawler）的 `data.db`，经 importer + store 导入 `market.db`，**本次仅做管道整合、不含数据采集工作量** | 若评审基于"本次周期实际产出"，可评估替换为小样本人工整理/公开数据集 |
| **权重注入 prompt 因果未验证** | Diagnostician prompt 中的权重真正生效处在 `weighted_score()` 加权平均；prompt 是否改变模型打分分布未经 A/B 验证（已有 prompt 已改为中性诚实表述） | 做"有无权重说明文字"的 A/B 对照实验，量化影响 |
| **LLM 权重稳定性未测** | `analyze_jd_weights()` 用 LLM 判 JD 权重，`temperature=0.2` 非完全确定，"千岗千面"卖点的同-JD 权重方差从未测过 | 固定 JD 反复采样统计权重方差，给出稳定性区间 |
| **输出检测仅监控不阻断** | `security.check_output()` 检测到泄漏仅记日志、不拦截、不脱敏，泄漏内容原样返回前端，属可观测性而非输出安全边界 | 需要时做输出脱敏/阻断（产品化阶段事项） |
| **职业规划路径未经验证** | v3.2 的路径推理为单次 LLM 生成，阶段划分/顺序/里程碑合理性未做 A/B 或专家校验；LLM 失败时走启发式三段式兜底 | 用真实职业样本做专家评审；将"路径可行性"纳入黄金样本回归评测 |

> **关键结论**："50 个测试用例通过"不等于"核心功能被验证"。核心诊断质量依赖 LLM，测试套件验证的是**工程正确性**；v7.0.3 起新增**黄金样本回归**与 **live-LLM 抽检**（`tests/test_diagnosis_golden.py`），首次把**诊断有效性**纳入可观测范围。

---

## 📝 开发文档

详见 `docs/` 目录：

- [v1 模块需求文档](docs/)
- [v2 大版本迭代需求](docs/week2_v2迭代_需求.md)
- [模块差距分析](docs/week3_三个模块差距分析与阶段结论.md)
- [v2.6 深化诊断核心](docs/week4_深化诊断核心_需求.md)
- [v3.0 市场数据层改造](docs/week5_v3数据层_需求.md)
- [前端设计方案（UI/UX 重构·评审稿）](docs/前端设计方案_UIUX重构.md)

### 宪章与契约（v3.2）

- [不变硬约束 CHARTER.md](CHARTER.md)：架构原则 / 诊断五维度 / L1-L4 分层规则 / 决策记录卡模板 / 已知局限
- [版本迭代叙事 CHANGELOG.md](CHANGELOG.md)：v2 → v7.1 各轮新增、推翻、修复
- [.importlinter](.importlinter)：分层依赖契约文件（INI 格式，与 CHARTER 约束同步）

### 自动化测试

测试策略见上文「测试策略与工程保障」。常用命令：

```bash
# 运行全部测试（约 900 用例，全绿）
pytest tests/ -v

# 仅跑黄金样本评测（确定性回归，默认运行）
pytest tests/test_diagnosis_golden.py -v

# 黄金样本 + 真实 LLM 抽检（需 GOLDEN_LIVE_LLM=1 + 真实 Key，烧 token，仅手动触发）
$env:GOLDEN_LIVE_LLM="1"; $env:GOLDEN_LIVE_LLM_API_KEY="sk-..."; pytest tests/test_diagnosis_golden.py -v

# 覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing
```

测试覆盖：Schema 验证 / API 路由 / Gap 分析器 / 维度权重 / 简历解析 / 报告生成 / 安全防护 / Web 研究 / 技能匹配 / 市场数据 / 职业规划 / 收尾强控 / 追问点提取 / 输出净化 / 任务级模型绑定 / 逐题拆解 / 黄金样本评测

### 分层依赖检查

```bash
# 校验 L1-L4 分层契约（新增/重构模块后必跑）
python run.py lint
```

> Windows 下无需额外操作：`run.py lint` 已内置 `PYTHONUTF8=1`，避免 grimp 按 GBK 解析 UTF-8 源码导致漏检。


---

## 🤝 贡献

本项目为课程项目，暂不开放外部贡献。欢迎 Star ⭐ 和 Issue 反馈！

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。
