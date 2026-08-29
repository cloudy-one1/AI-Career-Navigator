# HakiMeet 深度研读报告

> 研读对象：<https://github.com/zhaojunfei/HakiMeet>（AI 模拟面试平台，MIT）
> 研读方式：克隆源码全量通读（后端 19 个 .py / 前端 8 视图 + 7 composable + 2 Three.js 场景）
> 研读目的：为本项目（AI 模拟面试官 v6.2）寻找可迁移的机制与应规避的坑
> 代码引用中的路径均相对仓库根目录；`backend/`、`frontend/` 前缀即该仓库目录

---

## 0. 速览

| 项 | 内容 |
|---|---|
| 定位 | 语音优先（voice-first）的 AI 模拟面试练习平台 |
| 提交数 / 周期 | 23 次提交，2026-02-08 → 2026-03-29（约 7 周） |
| 后端 | FastAPI + SQLAlchemy(async) + SQLite + LangChain + ChromaDB + 豆包（火山方舟） |
| 前端 | Vue 3 + Vite 7 + Pinia + Tailwind 4 + Arco Design + Three.js |
| 代码规模 | 后端约 90 KB / 前端约 240 KB（不含 `avatar.glb` 9.7 MB） |
| 测试 | **0 个**（无 tests 目录、无 CI） |
| 文档 | README 2.7 KB，无架构文档、无 API 契约文档 |

一句话概括：**它把"面试官"整体外包给了豆包的实时语音大模型（端到端 Realtime Dialogue），自研部分退化为「上下文准备（RAG）+ 过程投喂（502 外部知识）+ 事后沉淀（长期记忆）」三件事。**

这个取舍是理解整个项目的钥匙：它换来了极低的对话编排复杂度和天然流畅的语音体验，代价是对话过程完全不可控、不可测、不可离线回放。

---

## 1. 架构总览

### 1.1 部署拓扑

```
浏览器 ──HTTP──> nginx(:80) ──/api/──> uvicorn(:8000)
       ──WS────> nginx(:80) ──/ws/───> uvicorn(:8000) ──WSS──> 豆包 Realtime Dialogue
                                            │
                                            ├── SQLite (hakimeet.db)
                                            └── ChromaDB (本地 bge-small-zh-v1.5 embedding)
```

`docker-compose.yml` 用 4 个 named volume 持久化 `chroma_db / hakimeet.db / uploads / logs`，前端 nginx 同时代理 `/api/` 与 `/ws/`（`proxy_read_timeout 300s`）。

> ⚠️ `backend/Dockerfile:13` 写成了 `COPY req uirements.txt .`（`requirements.txt` 被拆成两个词），**当前 `docker compose build` 必然失败**。README 的 Docker 一键启动路径实际是断的。

### 1.2 后端模块职责

| 模块 | 行数级 | 职责 |
|---|---|---|
| `app/ai/voice_engine.py` | 12.4 KB | 豆包 Realtime 二进制协议客户端（连接/重连/事件解析） |
| `app/ai/protocol.py` | 4.4 KB | 协议头编解码（4bit 分段头 + gzip + JSON） |
| `app/ai/engine.py` | 10.8 KB | 面试引擎：system prompt、RAG 上下文拼接、结束报告 |
| `app/ai/rag.py` | 7.2 KB | Chroma 入库/检索/随机出题/删除 |
| `app/ai/memory.py` | 5.5 KB | 面后独立 LLM 分析，沉淀薄弱点 |
| `app/routers/ws.py` | 9.2 KB | 浏览器 ↔ 豆包 的双向转发枢纽（**唯一的面试主流程**） |
| `app/routers/{resume,question_bank,interview,memory,ai_config}.py` | 3–5 KB × 5 | 常规 CRUD |
| `app/models/database.py` | 5.6 KB | 8 张表的 SQLAlchemy 模型 |

### 1.3 接口清单

| Method | 路径 | 用途 |
|---|---|---|
| POST | `/api/resume/upload` | 上传 PDF/MD 简历 → 提取文本 → 向量化 |
| GET/DELETE | `/api/resume/list`、`/api/resume/{id}` | 简历列表 / 删除 |
| POST | `/api/qb/upload` | 上传题库（PDF/MD），按问答边界切分入库 |
| GET | `/api/qb/list`、`/api/qb/categories`、`/api/qb/{id}/chunks` | 列表 / 分类 / 预览切块 |
| DELETE | `/api/qb/{id}` | 删题库 + 删向量 |
| POST/GET | `/api/interview/create`、`/api/interview/list` | 创建 / 列表 |
| GET | `/api/interview/stats` | 总次数、平均分、分类覆盖 |
| GET/DELETE | `/api/interview/{id}` | 详情（含 turns）/ 删除 |
| GET | `/api/memory/list` | 薄弱点（按分类分组） |
| GET | `/api/memory/suggestions?categories=` | 首页选题时提示"该复习什么" |
| PUT/DELETE | `/api/memory/{id}/resolve`、`/api/memory/{id}` | 标记已解决 / 删除 |
| GET/PUT/DELETE | `/api/ai-config` | 用户自定义模型配置（返回密钥脱敏预览） |
| POST | `/api/ai-config/test` | 连通性测试（发一句"你好"） |
| WS | `/ws/interview/{interview_id}` | 面试主链路 |

WS 下行消息类型：`ai_text` / `user_text` / `ai_audio`(base64 PCM) / `interrupted` / `error` / `report`；上行：二进制音频帧 + `{type:'control',data:{action:'end'}}`。

---

## 2. 核心机制拆解

### 2.1 端到端实时语音对话（本项目最值得研究的部分）

**关键设计**：浏览器不跟自研 LLM 对话，而是把麦克风 PCM 直接转投给豆包 Realtime，豆包内部完成 ASR → LLM → TTS，后端只做三件事：连接时下发 system prompt、过程中用 event 502 投喂外部知识、把 TTS 音频流和文本流转回浏览器。

二进制协议（`backend/app/ai/protocol.py`）：

```43:66:backend/app/ai/protocol.py
def generate_header(
        version=PROTOCOL_VERSION,
        message_type=CLIENT_FULL_REQUEST,
        message_type_specific_flags=MSG_WITH_EVENT,
        serial_method=JSON,
        compression_type=GZIP,
        reserved_data=0x00,
        extension_header=bytes()
):
    header = bytearray()
    header_size = int(len(extension_header) / 4) + 1
    header.append((version << 4) | header_size)
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved_data)
```

事件时序（`voice_engine.py`）：

| event | 方向 | 含义 |
|---|---|---|
| 1 / 2 | → | StartConnection / FinishConnection |
| 100 / 102 | → | StartSession（带 asr/tts/dialog 配置）/ FinishSession |
| 200 | → | 音频帧（gzip 压缩的 PCM） |
| 300 | → | say_hello（下发作开场白，让其开口说第一句） |
| 502 | → | **external_rag：外部知识投喂**（本项目的灵魂接口） |
| 451 / 459 | ← | 用户 ASR 流式 / 说完 |
| 550 / 559 | ← | AI 文本流 / 回复结束 |
| 450 | ← | 被打断（Interrupted） |
| 152 / 153 | ← | Session 结束 |

音频参数：上行 ASR `pcm_s16le / 16kHz / 单声道`，下行 TTS `pcm_s16le / 24kHz`，`end_smooth_window_ms=1500`（句尾静音判定），`recv_timeout=30`。

健壮性处理有两点做得不错：

```116:133:backend/app/ai/voice_engine.py
        for attempt in range(1, retries + 1):
            try:
                self.ws = await websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    proxy=None,
                    ping_interval=None,
                    open_timeout=20,
                )
                logger.info("WebSocket 连接已建立 (第%d次尝试)", attempt)
                break
            except (TimeoutError, OSError) as e:
                last_err = e
                logger.warning("连接语音超时 (第%d/%d次): %s", attempt, retries, e)
                if attempt < retries:
                    await asyncio.sleep(1)
        else:
            raise ConnectionError(f"语音 API 连接失败 ({retries}次重试后): {last_err}") from last_err
```

- 连接重试 2 次 + `open_timeout=20` + 显式关掉 `ping_interval`（避免与服务端心跳打架）；
- `receive_loop()` 用 `async for ... else` 区分「正常结束」和「服务端错误」，错误才重连、`_reconnect()` 期间暂停 `send_audio` 丢弃音频而不是报错。

**代价**（务必看清）：
1. 面试官的一字一句由云端模型产出，本地**无法做输出净化**（本项目 v6.2 的 `output_sanitizer` 那一套在这里无处挂载，除非在 TTS 前拦截——但 Realtime 模式拿不到"文本先于音频"的时机）；
2. 拿不到结构化的"当前题 / 当前状态"，所有决策只能靠"投喂 + 自然语言策略指引"间接影响；
3. 强供应商绑定 + 无法离线/无法录播回放；
4. 本地 `history` 只是**旁听记录**（从 550/559 事件拼回的完整句），用于事后报告与记忆分析，不参与对话控制。

### 2.2 RAG 动态注入 + 注入去重缓存

最有巧思的一处：因为对话不在本地 LLM 上跑，无法每轮改 system prompt，于是**把"下一题该问什么"作为外部知识从 event 502 塞进实时会话**。

```103:136:backend/app/ai/engine.py
    async def get_turn_context(self, user_input: str) -> str:
        if not self.rag or not self.interview_obj or not self.interview_obj.qb_categories:
            return ""
        categories = self.interview_obj.qb_categories
        # 初始化时只检索1道，后续每轮检索3道
        k = 1 if self.turn_count <= 1 else 3
        docs = self.rag.search_qb(user_input, categories, k=k)
        # 去重：只保留没注入过的内容
        new_parts = []
        for doc in docs:
            content_hash = hash(doc.page_content.strip())
            if content_hash not in self._injected_cache:
                self._injected_cache.add(content_hash)
                new_parts.append(doc.page_content)
        parts = []
        if new_parts:
            parts.append("【相关题库参考】\n" + "\n\n".join(new_parts))
        # 随机出一道备选题（也走缓存去重）
        if self.turn_count > 1:
            for _ in range(5):
                random_q = self.rag.random_question(categories)
```

三条工程经验：
- **注入去重**：用内容哈希集合 `_injected_cache` 保证同一道题不会被反复投喂（提交历史里 `8a359c5`、`83f2ff7` 两次迭代正是修这个：先做缓存去重，再修"随机题注入被去重误杀"）；
- **首轮 k=1、后续 k=3**：开场少给避免污染开场白，之后加量供追问；
- **策略指引只注入一次**（`_strategy_injected`），用自然语言告诉模型"可选深挖/纠错/换题"，配合"备选题"实现换题能力——这是没有 tool-calling 时的土味但有效的做法。

题库切分用了一个启发式（不依赖正则规则库）：扫描行，遇到含问号且此前连续 ≥2 行无问号的答案时切为新题，切不动则退化为 500/50 字符滑窗。

### 2.3 长期记忆闭环

`app/ai/memory.py`：面后**另起一个 LLM**（temperature=0.3）专门分析"哪些题答得不好"，输出 JSON 数组写 `weak_points` 表。

- 分类归属做了兜底：模型返回的 category 若不在题库分类内，回落到第一个分类；
- severity 用 `min(max(int(x),1),5)` 夹紧；
- JSON 容错三级：markdown 代码块剥离 → 数组兜底 → 对象兜底（本项目 v6.0 的"四级容错"思路一致，可互为参照）；
- 触发方式：报告落库后 `asyncio.create_task(...)` 异步跑，不阻塞报告返回。

```40:53:backend/app/ai/engine.py
                    wp_result = await session.execute(
                        select(WeakPoint).where(
                            WeakPoint.user_id == self.interview_obj.user_id,
                            WeakPoint.resolved == False,
                            WeakPoint.category.in_(categories),
                        ).order_by(WeakPoint.severity.desc()).limit(10)
                    )
```

下次面试初始化时，取**本场分类内、未解决、按 severity 降序 top10** 注入 system prompt 的「用户长期记忆（重点考察）」段，首页 `/api/memory/suggestions` 则在选分类时实时提示——形成"练 → 评 → 记 → 再练"闭环。**这个闭环的完整度和 UI 呈现（3D 图谱 + 已解决标记）是它相对本项目的最大产品优势。**

### 2.4 报告与评分（反面教材）

```210:211:backend/app/ai/engine.py
        response = await self.llm.ainvoke(msgs)
        return {"summary": response.content}
```

```162:164:backend/app/routers/ws.py
        m = re.search(r'(?:总体评分|总体成绩|综合评分|评分|得分)[*\s]*[（(：:\s-]*(\d+(?:\.\d+)?)', summary)
        if m:
            score = float(m.group(1))
```

两个硬伤：
1. **用正则从 LLM 自由文本里抠分数**，措辞一变就抠不到 → `overall_score` 为 NULL，趋势图、平均分、最高分全部失真；
2. 前端 `InterviewView.vue:82` 渲染 `report.dimensions`，但后端 `end_interview()` 只返回 `{summary}` → **维度评分卡片是永远不显示的死 UI**。正确做法是像本项目 v6.2 那样走结构化 JSON + 逐题拆解。

### 2.5 前端：3D 数字人面试官

`useAvatarScene.js` 211 行，Three.js 加载 `avatar.glb`（ReadyPlayerMe 风格，带 ARKit/viseme 形态键）：

- 遍历骨骼取 `Head` / `Spine`，做微小摆动与呼吸（scale.y 正弦 0.3%）；
- 眨眼：随机 3–5s 触发，`eyeBlinkLeft/Right` 置 1 持续 0.15s；
- 口型：预留了 viseme 时间轴接口（`setVisemes()`，注释说未来接 rhubarb），**当前用程序化模拟**——`sin(t*7)` 叠加 `sin(t*11.3)` 驱动 `jawOpen` + 元音 viseme 轮换，用 lerp 平滑：

```165:184:frontend/src/composables/useAvatarScene.js
  function driveProceduralMouth(t, inf, lerpSpeed) {
    const base = Math.sin(t * 7) * 0.5 + 0.5
    const vary = Math.sin(t * 11.3) * 0.3 + Math.sin(t * 4.7) * 0.2
    const jawIdx = morphDict['jawOpen']
    if (jawIdx != null) inf[jawIdx] = base * 0.5
    const vowels = ['viseme_aa', 'viseme_E', 'viseme_I', 'viseme_O', 'viseme_U']
    const pick = Math.floor((t * 5) % vowels.length)
```

即：**口型和音频无关，只是"说话时嘴在动"的视觉暗示**。优点是不需要音素对齐链路（省掉 rhubarb/Whisper 对齐），成本几乎为零；缺点是不可能对上真实发音，属于"氛围组"。

### 2.6 前端：3D 长期记忆图谱

`useMemoryGraph3D.js` 453 行，Three.js + CSS2DRenderer：

- 场景：星空（2000 点，AdditiveBlending）+ 指数雾 + 三点光；
- 布局：**极坐标两层**——中心"知识图谱"发光球 → 各类别节点按 `2π*i/n` 均匀分布在半径 5 的圆周 → 每个类别下最多 6 个记忆点分布在半径 1.5 的小圆上（限 6 个是显式性能取舍）；
- 颜色语义双通道：类别用调色板轮转，记忆点用 severity（≥4 红 / ≥3 橙 / 否则蓝），已解决的节点 `emissiveIntensity` 降到 0.3、透明度 0.4；
- 交互：拖拽旋转（拖动时暂停自动旋转）、滚轮缩放（z 夹在 8–25）、Raycaster 点击节点回调；
- 性能处理：节点浮动动画每 3 帧更新一次、连线/标签数量受控。

缺陷同样明显（见 §5 P2）：`createNodes()` 只清理 `nodes.value` 里的 mesh，而 `centerLine` / `itemLine` 是 `scene.add()` 后**没有登记**的，重复刷新会不断累积线段并泄漏。

### 2.7 前端设计系统与交互工程（最值得单独研究的一块）

补充一轮专项阅读（`style.css` / `HomeView` / `MemoryView` / `QuestionBankView`）后的结论：**它的前端"成品完成度"明显高于后端，且有一套自觉的视觉工程方法**，不是堆组件堆出来的。

**（1）先建 token，再写页面。** `style.css` 用 Tailwind v4 的 `@theme` 定义了完整语义体系：背景 4 层、边框 3 级、文字 4 级、主色 4 阶 + 2 档 soft、语义色 4 组各带 soft、阴影 6 级（从 `xs` 的单层到 `xl` 的双层叠加）、内阴影 2 级。之后所有页面一律只用 token，不写死色值。

**（2）把第三方组件库"驯化"成自家语言。** 引入 Arco Design 后没有放任它的默认观感，而是在 `style.css` 末尾用 200 行覆盖：圆角统一 12px（卡片/模态 16px）、主色重绑到自家 `--primary-6`、主按钮改成渐变+发光投影、输入框/下拉/标签统一 2px 边框 + 聚焦 3px `accent-soft` 光环、禁用态统一 0.5 透明度。**这是很多人用组件库时缺的一步**，也是它"看起来像同一个产品"的根本原因。

**（3）微交互有统一语法。** 缓动统一 `cubic-bezier(0.4,0,0.2,1)`；hover 一律 `translateY(-1~-3px)` + 阴影升级；active 一律 `scale(0.96~0.99)`；卡片交互态 `translateY(-3px) scale(1.01)`；页面进入动画带 `blur(4px)→0` 的入场；还准备了 `stagger-1~4` 做列表错峰。滚动条、shimmer、pulse、玻璃态（`.glass` / `.glass-dark`）都是全局件。

**（4）状态机驱动页面。** `InterviewView` 把面试拆成 `idle / connecting / initializing / active / ended / error` 六态，每态有独立视觉（状态徽章配色、初始化蒙层、结束后的评分面板），并用**单个 watcher 收敛所有副作用**——计时器启停、摄像头开关、录音启停、ending 标记全挂在这一个 `watch` 上，避免了散落的生命周期钩子：

```258:275:frontend/src/views/InterviewView.vue
watch(() => store.status, async (s, old) => {
  // 计时器
  if (s === 'active' && old !== 'active') {
    startTime.value = Date.now()
    timer = setInterval(() => { ... }, 1000)
  } else if (s !== 'active' && timer) { clearInterval(timer); timer = null }
  // 摄像头 & 录音
  if (s === 'initializing') { await nextTick(); cam.start() }
  else if (s === 'active' && old === 'initializing') { recorder.start() }
  else if (['ended', 'idle', 'error'].includes(s)) { cam.stop(); recorder.stop() }
```

配套细节也到位：聊天面板与摄像头面板可折叠切换、折叠时摄像头升为主画面、展开时降为右下 PiP 画中画；结束时**从 `interview_turns` 反向还原聊天记录**形成复盘视图；危险操作走全局 `useConfirm`（Teleport + Promise 化）；`onUnmounted` 统一回收 timer/camera/recorder/store。

**（5）记忆图谱做了两套。** 除了 §2.6 的 Three.js 3D 版，`MemoryView` 里还并行实现了一套 **2D SVG/DOM 版**：`<svg viewBox="0 0 1000 600">` 画贝塞尔连线（`getConnectionPath` 用二次 Q 曲线），节点用绝对定位 DOM（`.node-dot` / `.memory-dot`），带平移拖拽（`panOffset` + `isDragging`）和滚轮缩放（`graphScale` 夹在 0.5~1）。两个值得抄的细节：

- **确定性伪随机布局**：`getSynapsePosition` 把节点 `id` 做字符串哈希当随机种子，保证同一节点每次渲染位置一致（不会刷新一次图谱跳一次）；
- **颜色即数据**：`getHeatmapColor` 把 `avgSeverity/5 × 未解决比例` 映射成红/黄/蓝/灰四级渐变，一眼看出哪个分类最该复习。

**（6）onboarding 细节。** 空状态是"图标 + 标题 + 说明"三件套而不是干巴巴一行字；题库页提供**模板一键下载**（`downloadTemplate()` 内联一段带真实 Java 题的 Markdown，用 Blob 触发下载），把"我该上传什么格式"这个疑问直接消解掉。这类细节最能拉开成品感差距。

**但它的问题同样在前端：**

- **巨石组件**：8 个视图平均 24 KB，`HomeView` 41 KB、`MemoryView` 37.8 KB（其中 CSS 就 1200+ 行），`template + script + scoped CSS` 全塞在一个文件里，几乎不拆子组件；
- **样式复制粘贴**：`style.css` 里定义了 `.card / .card-hover / .stat-*` 等全局件，但各页面又在自己 `scoped` 里重写一套 `.page-header / .page-title / .stat-card / .stats-grid`（数值还略有出入）。**视觉上统一，实现上是复制**，改一次主题要动七八处；
- **视觉领先于数据**：精美的热力图/趋势图/学习中心背后是 `Math.random()` 和硬编码常量（见 §5 P1-10），前端做得越好，这些假数据越有欺骗性；
- **同一功能两套实现**（2D + 3D 图谱）在无人维护时必成负担。

### 2.8 前端音频链路

- 录音：`ScriptProcessor(4096)`（作者注释：AudioWorklet 需要单独文件，故用废弃 API），Float32→Int16，16 kHz；
- 播放：base64 → Int16 → Float32，`AudioBufferSourceNode` 队列串行播放，`onended` 驱动下一段；
- **无 VAD、无节流**：每 256 ms 一帧全量上行（本项目 v6.2 已做 VAD 节流，这点领先）；
- `flush()` 只清空队列，**没有 stop 正在播放的 source** → 打断时当前这段仍会播完并触发 `playNext`，打断体验有瑕疵。

---

## 3. 数据模型（8 张表）

```
users ──< resumes            (filename / raw_text / file_path / vectorized)
     ──< question_banks      (category 为检索过滤维度)
     ──< interviews          (qb_categories JSON / status / overall_score / report JSON)
     ──< ai_model_configs    (文本模型 + 语音模型，user_id unique)
interviews ──< interview_turns (turn_number / ai_question / user_answer / score_data)
weak_points (user_id, interview_id, category, question_summary, weakness_desc, severity, resolved)
job_positions (定义了但全项目未使用)
```

- `interview_turns` 与 `weak_points` 都有，但 `score_data` 从未写入——逐题评分是半成品；
- `job_positions` 是死表：路由里 `job_id` 被前端硬编码为 `'demo'`。

---

## 4. 做得好的地方（值得肯定）

1. **Realtime 语音的取舍极其果断**：用"外包对话"换掉了大量编排代码，7 周做出可用的语音面试产品；
2. **event 502 外部知识投喂 + 哈希去重**：在没有 tool-calling 的约束下，做出了"动态出题/换题"的工程解，思路可复用；
3. **连接层容错扎实**：重试、超时、错误码识别（`quota exceeded` 特判成人类可读提示）、错误才重连；
4. **配置可视化**：`/settings` 页配置密钥 + 一键连通性测试 + 密钥脱敏回显（`****xxxx`），UX 完整；
5. **RAG 单一入口重构**（提交 `9601b83`）：统一 filter 构造器、唯一 `search_docs`，消除重复实现；
6. **长期记忆的"分类 + severity + resolved"三元组设计简洁有效**，且真正闭环回注入；
7. **渐进降级**：RAG 初始化失败返回 `None`，全链路以"无向量检索模式"继续跑，不阻断主流程。

---

## 5. 问题与风险清单

### P0 安全

| # | 问题 | 位置 |
|---|---|---|
| 1 | **真实密钥硬编码进 Git**：豆包 API Key、语音 app_id / access_key / secret_key / app_key 全在 `config.py` 默认值里，已随公开仓库泄露 | `backend/app/config.py:9-18` |
| 2 | **零鉴权**：`user_id` 全部硬编码 `"demo-user"` 作为查询参数默认值；`User` 表、`passlib`、`python-jose` 依赖都在，但**没有任何登录/校验中间件**，任何人可读写全部数据 | 全部 router |
| 3 | **上传路径穿越**：`UPLOAD_DIR / file.filename` 直接用客户端文件名，`../../` 可写任意路径；同名文件静默覆盖 | `resume.py:30`、`question_bank.py:30` |
| 4 | **向量库无租户隔离**：所有用户数据进同一个 Chroma 默认 collection，仅靠 metadata 过滤；`delete_by_metadata` 无 user 维度 | `rag.py` |
| 5 | CORS 硬编码 `http://localhost:5173`，部署域名变更即失效 | `main.py:54` |

### P1 工程质量

| # | 问题 |
|---|---|
| 6 | **零测试**：无 tests、无 CI、无 lint 配置 |
| 7 | **评分靠正则抠字**（§2.4），且维度评分 UI 是死代码 |
| 8 | **Docker 构建必然失败**：`COPY req uirements.txt .` 单词被拆开 |
| 9 | 无分层、无契约：路由层直接 `from app.ai.rag import get_rag`，模块循环依赖靠函数内 import 规避 |
| 10 | **假数据充门面**：`LearningView` 整个"学习中心"（42 小时 / 连续 7 天 / 156 题 / 78% 通过率 / 成就墙）全是 `ref(常量)` 硬编码，**不调任何接口**；`HomeView` 热力图 `Math.floor(Math.random()*8)`、趋势折线坐标写死、题目数/正确率 `Math.random()`；`App.vue` 侧栏"本周练习 12 次""已用 3/10 次"也是写死的 |
| 11 | 简历删除只删 DB 行和文件，**不删向量**；题库删除才删 → 数据不一致 |
| 12 | 会话无长度上限：`history` 全量塞进报告 prompt，长面试会超窗 |
| 13 | `main.py` 顶部对 `websockets` 做 monkey patch 兼容 Python 3.14，属于依赖层 hack |

### P2 体验 / 性能

| # | 问题 |
|---|---|
| 14 | 3D 图谱 `createNodes()` 不清连线、`destroy()` 不 dispose geometry/material → 重复渲染累积泄漏 |
| 15 | `flush()` 不 stop 当前 source，打断不彻底 |
| 16 | 音频无 VAD/节流，静音也持续上行 |
| 17 | 用已废弃的 `ScriptProcessor`，音频处理占用主线程 |
| 18 | `avatar.glb` 9.7 MB 无压缩/无 CDN/无加载占位 |
| 19 | 依赖极重：`sentence-transformers + chromadb + torch`，即便已换 CPU 版镜像仍很大 |
| 20 | 无 Markdown/舞台提示净化（Realtime 模式下也确实无处挂载） |

---

## 6. 与本项目（AI 模拟面试官 v6.2）对比矩阵

| 维度 | HakiMeet | 本项目 v6.2 | 判断 |
|---|---|---|---|
| 对话架构 | 外包给 Realtime 语音大模型 | 自研编排（question_gen + interview_engine + next_action 三态） | **各有胜负**：它省代码但失控，我们可控但复杂 |
| 语音 | 端到端实时，天然打断 | MiMo TTS/ASR 分离 + 浏览器降级 | 它体验更好，我们可移植性更强 |
| 输出净化 | 无（且架构上难挂载） | v6.2 `output_sanitizer`（禁 Markdown/舞台提示/垫词） | **我们领先** |
| 评分与报告 | 自由文本 + 正则抠分，维度评分是死 UI | 结构化 JSON + 四级容错 + 逐题拆解 | **我们领先** |
| RAG | Chroma + bge-small-zh，动态注入 + 哈希去重 | 命名空间知识库（`rag:interview/career/resume`）+ 简历证据检索 | 打法不同；**它的注入去重值得抄** |
| 长期记忆 | 薄弱点三元组 + 闭环回注入 + 3D 图谱 UI | v5.0 薄弱点跨轮累计 | **它的闭环完整度和可视化更强** |
| 工程约束 | 无分层、无测试、无 CI | L1–L4 分层 + import-linter + 559 测试 | **我们大幅领先** |
| 安全 | 密钥硬编码、零鉴权、路径穿越 | `security.py`（注入/输出/记忆污染检查）+ 密钥走 .env | **我们大幅领先** |
| 产品宽度 | 纯面试练习 | 面试 + 职业规划 + 市场数据 | 我们更宽 |
| 前端 | Vue 3 + Tailwind + Arco + Three.js；有自觉的 design token 与微交互体系，但巨石组件 + 样式复制粘贴 + 假数据 | 原生 ES Module + Chart.js，双风格主题 | **它的成品观感明显领先**（值得抄 token/状态机/2D 图谱），但我们的可维护性更好 |

结论：**它是一个"产品感强、工程纪律弱"的对手项目**。值得学的是它的三个"产品化巧思"（Realtime 语音取舍、502 动态知识投喂、长期记忆可视化闭环），不值得学的是它的全部工程实践。

---

## 7. 可迁移清单

> **落实状态（v6.4，2026-08-29）**：P1 八项已全部落地，全量 655 例测试通过、分层 lint 通过。落地时的偏差与改进：
> - **#1 注入去重 ✅（改进）**：去重键用 `blake2b` 稳定摘要替代本报告指出的 HakiMeet 内置 `hash()` 缺陷；并加"耗尽回退"——所有块注入过后回退复用，避免长会话后期证据包恒空。
> - **#2 备选题 ✅（形态调整）**：本项目题目由 LLM 生成而非固定题库抽取，故落地为"已问题目台账 + 负向约束注入 + 重复题带样本重试一次"，语义等价。
> - **#3 长期记忆闭环 ✅**：扩展既有 `/api/weakness-profile`（resolved 标记 + suggestions + 首轮回注入），未另起命名空间；幂等迁移解决老库加列问题。
> - **#4 打断语义 ✅（加固）**：voice.js 引入语音世代号；顺带修复"打断后 MiMo 失败误降级续播"与"canceled/interrupted 也触发 onEnd"两个本项目实际存在的同类缺陷。
> - **#5 2D SVG 记忆图谱 ✅**：新增"长期记忆"页，确定性哈希布局 + severity 配色 + 图表双向联动；只做 2D 一套。
> - **#6 token 补强 ✅**：六级阴影/玻璃态/标准缓动 + 全局组件类；页面禁止重写全局类。
> - **#7 状态机收敛 ✅（克制版）**：PHASE 四态 + setPhase 单入口 + setInputLocked 统一；顺带删除三个死状态、修复 connectWS 重置不全与 finishInterview 后 ws 未置空。完整六态未做（避免 1400 行文件的过度重构）。
> - **#8 onboarding ✅**：空状态三件套 / 模板一键下载 / Promise 化确认弹窗。
> - **P2 各项**：#9 Realtime 语音**明确不做**（会废掉 output_sanitizer 与结构化评分）；#10 3D 图谱不做（2D 已覆盖）；#11 数字人未做；#12 Web 端密钥配置未做。

### P1（明确建议做）

| # | 迁移项 | 落地建议 | 风险 |
|---|---|---|---|
| 1 | **RAG 注入去重缓存** | 在 `resume_retriever` / `knowledge_store.retrieve` 之上加会话级 `_injected_cache`（内容哈希），检索结果过滤后再拼 prompt。成本低、收益直接（消除"反复问同一道题"） | 低 |
| 2 | **"备选题"机制** | 每轮额外随机抽 1 道未注入题，标注为"换题时可用"，配合现有 `next_action` 三态的切换分支 | 低 |
| 3 | **长期记忆闭环可视化** | 已有薄弱点数据，缺的是"回注入 + 已解决标记 + 首页复习建议"。可先做轻量版：`/api/memory/suggestions` 式提示 + 列表页 resolved 开关，不急着上 3D | 低 |
| 4 | **打断（barge-in）语义** | 若引入语音播放，需实现真打断：`flush()` 里 `source.stop()` 并置空 `onended`，否则打断不彻底 | 中 |
| 5 | **2D SVG 记忆图谱**（优先于 3D） | 抄 `MemoryView` 的 2D 版：SVG 二次贝塞尔连线 + 绝对定位 DOM 节点 + `id` 哈希确定性布局 + `avgSeverity × 未解决率` 映射配色 + 平移/缩放。**无需 WebGL、无新依赖**，与本项目原生 ES Module 前端直接兼容，性价比远高于 3D 版 | 低 |
| 6 | **前端 design token 体系** | 参考 `style.css` 的语义色阶/阴影分级/统一缓动，先把现有纸墨印章双风格的变量收敛成一套 token；**同时规避它的错误**——页面不得各自重写 `.stat-card` 之类，样式一律走全局层 | 低 |
| 7 | **状态机收敛副作用** | 抄 `InterviewView` 的"单个 `watch(status)` 统一驱动计时器/摄像头/录音"写法，替代散落的生命周期钩子；配合 v6.2 已有的 `next_action` 三态，把前端六态（idle/connecting/initializing/active/ended/error）补齐 | 低 |
| 8 | **onboarding 细节** | 空状态三件套（图标+标题+说明）、题库/简历模板一键下载（Blob 触发）、全局 Promise 化确认弹窗（Teleport） | 低 |

### P2（视资源决定）

| # | 迁移项 | 落地建议 | 风险 |
|---|---|---|---|
| 9 | **Realtime 语音作为可插拔模式** | 抽象 `RealtimeVoiceProvider` 接口，与现有 MiMo TTS/ASR 并列，配置切换；保留 fallback 与"无语音纯文本"降级。**关键前提**：接受该模式下 `output_sanitizer` 与结构化评分失效，需在报告侧改为"文本转录后再离线评分"来兜底 | 高（供应商绑定、成本、不可测） |
| 10 | **3D 记忆图谱**（2D 版跑通后再考虑） | 借鉴其极坐标两层布局 + severity 配色；**务必修正**其缺陷：连线/perf 对象登记进统一数组，`destroy()` 中 dispose geometry/material/texture，`resize` 用 ResizeObserver。**且不要像它那样 2D/3D 两套并存** | 中（Three.js 体积、WebGL 兼容） |
| 11 | **数字人面试官** | 程序化口型（正弦叠加驱动 jawOpen/viseme）是 200 行内的高性价比方案；`avatar.glb` 需压缩（Draco/meshopt）并做懒加载 | 中（9.7 MB 资源） |
| 12 | **Web 端模型配置 + 连通性测试 + 密钥脱敏回显** | 复用现有 `security.py` 的加密能力落库，**绝不**明文存；默认仍走 .env | 中（密钥落库即攻击面） |

### P0（本项目已有的优势，不要因为对标而丢掉）

- 分层契约与 import-linter 检查；
- 结构化评分 + 逐题拆解（不要退回"正则抠分"）；
- 输出净化；
- 安全护栏与密钥不落明文。

---

## 8. 一句话总结

HakiMeet 用 **"把面试官外包给实时语音大模型"** 这一个激进取舍，在 7 周内做出了体验流畅的语音面试产品，并在 **动态知识投喂（event 502 + 注入去重）** 和 **长期记忆闭环可视化** 两处给出了漂亮的工程解；但它在安全（密钥硬编码、零鉴权）、工程质量（零测试、正则抠分、Docker 构建失败）和数据真实性（整个学习中心是硬编码假数据）上的问题，使其**只适合作为"产品形态与交互灵感"的参考，不适合作为工程范本**。

对本项目的净收益排序：**注入去重 > 备选题 > 长期记忆可视化 > 打断语义 > 3D 图谱/数字人 > Realtime 语音模式**。

---

*附：研读时源码克隆于系统临时目录 `%TEMP%\HakiMeet`，未纳入本仓库工作区。*
