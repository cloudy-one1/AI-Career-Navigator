# week9 语音链路强化 — 需求理解文档

> 对应版本：v7.4.0（2026-08-31）
> 触发方式：对 v4.2 落地的语音链路做一次完整审计后，按审计结论做定向强化。
> 范围纪律：**不引入新的语音厂商、不做端到端 Realtime、不改诊断内核**。

---

## 1. 模块目标

语音在本项目中的定位自 v2.3 起就明确为**输入 / 输出替代层**：只替换「题怎么念出来」与「回答怎么进文本框」两端，不参与五维诊断。本次强化的目标不是扩展语音能做什么，而是把已有能力的**三个断点**补上：

1. **长录音用不了** —— 允许录 120 秒，但请求体只放行 1MB，长回答必然失败且回答丢失；
2. **降级太脆** —— 一次网络抖动就让整场面试退回浏览器机械音，不可恢复；
3. **闭环没合拢** —— 念完题要手动点麦克风、说完还要手动点提交，且录音过程零反馈。

---

## 2. 技术方案

### 2.1 链路现状（审计基线）

```
TTS:  speak() → mimoSpeak → /api/voice/tts → voice_service → MiMo chat/completions
                          ↘ 失败 → browserSpeak(speechSynthesis)
ASR:  startRecording(MediaRecorder + VAD) → stopRecording → /api/voice/asr → MiMo
                          ↘ 失败 → SpeechRecognition（仅 Chrome/Edge）
诊断: WS answer.source=voice → from_voice → VOICE_TRANSCRIPTION_NOTE 注入评分 prompt
```

### 2.2 本次改动清单

| # | 问题本质 | 方案 | 落点 |
|---|---|---|---|
| P0 | `/api/voice/asr` 不在上传白名单，走 1MB 普通请求额度，与 `maxDurationMs=120000` 直接冲突 | 加入 `_UPLOAD_PATHS`（10MB 额度）+ 路由层按实际 body 长度二次校验 | `main.py`、`routers/voice.py` |
| P1 | MiMo 路径开麦前不停朗读，外放的题目语音被自己的麦克风采进回答，还会被 ASR 容错评分盖掉 | `startRecording()` 补 `stopSpeaking()`，与浏览器路径 `startListening()` 对齐 | `voice.js` |
| P1 | `mimoStatus` 单向熔断，一次失败永久降级 | 连续失败计数（阈值 3）+ TTL（60s）后可重试 + `resetMimoStatus()` 供开新面试复位 | `voice.js`、`interview.js` |
| P2 | VAD 固定阈值 0.02 两头失效 | **预滚校准**：开录后 700ms 取窗口最小 RMS 当底噪，阈值 = 底噪×2 + 0.012，夹在 [0.008, 0.12]，之后固定 | `voice.js` |
| P2 | 云端 ASR 无中间反馈（反而不如浏览器路径有 interim） | 复用 VAD 已有的 RMS，外抛 `stt:level` 事件，前端渲染 3px 电平条 | `voice.js`、`interview.js`、`components.css` |
| P2 | 9 个预置音色在 UI 层完全不可达（前端硬编码 `'default'`） | 模块级 `setTTSVoice()` + 引导页下拉，摘要同步 | `voice.js`、`interview.js` |
| P3 | 免手闭环未合拢 | 引导页开关（默认关）→ 念完题自动开麦 → VAD 说完自动停录 → 倒计时 3s 自动提交（可取消，转写 <10 字不提交） | `interview.js`、`components.css` |

### 2.3 关键取舍

**为什么 VAD 用「预滚校准」而不是「连续自适应」？**

最先写的是经典慢升快降（底噪 = 低通滤波后的 RMS）。写测试时发现它在逻辑上站不住：持续说话同样会被缓慢"学"成底噪，导致同一场面试里前后的判定标准漂移；而要在嘈杂环境里把底噪抬到位需要几十秒，等它收敛完 `maxDurationMs` 早就到了。

改为开录后先观察 700ms、取窗口**最小** RMS 当底噪，之后全程固定。理由：

- 用户点完麦克风到开口通常有间隔，窗口内最小值≈真实底噪；
- 一次性定阈，行为可预测、可复现，也便于写确定性测试；
- 代码里显式注明「刻意不做连续自适应」，避免后人以为是遗漏。

代价：若用户开麦瞬间就在说话，底噪会被高估（阈值被抬高，需要更大声才能触发）。已接受——宁可让用户重说，也不要让判定标准在录音中途漂移。

**为什么自动提交要留 3 秒倒计时 + 10 字下限？**

自动提交是"替用户做决定"，误提交的代价（丢一次作答机会）远大于多点一次按钮的代价。因此：只对 VAD 判定的"说完了"（`reason === 'auto'`）生效，手动点停止语义上是"我还要再说一段"；短文本不提交；倒计时期间任何打字 / 点麦克风 / 点取消都能撤销。

---

## 3. 涉及的知识点

- **浏览器媒体栈**：`MediaRecorder`（容器/编码协商）、`getUserMedia`、`AnalyserNode` 时域数据与 RMS 能量门限；
- **Web Audio 生命周期**：`AudioContext` 的 suspended/resume 与 close，采样器的泄漏边界；
- **竞态守卫**：世代号（generation counter）模式——异步请求落地时用世代号比对决定是否继续，配合"先摘回调再停止"消除迟到的结束回调；
- **熔断与恢复**：连续失败计数 + TTL 半开重试（区别于一次性熔断）；
- **请求体分层限流**：中间件按路径与 `Content-Length` 预检，路由层按实际读到长度兜底（分块传输无长度头时中间件会跳过）；
- **测试替身**：`vi.mock` 模块替换、`vi.useFakeTimers()` 推进时间、`Date.now` 打桩控制 TTL、`vi.waitFor` 等待异步副作用。

---

## 4. 测试补位

此前 `voice.js`（23KB）**零自动化覆盖**，而它装着世代号竞态与 VAD 状态机这两块最脆弱的逻辑。

- 新增 `frontend/vitest.config.js` + `frontend/tests/voice.test.js`（16 例）；
- 运行环境选 `node` 而非 `happy-dom`：`MediaRecorder` / `AudioContext` / `speechSynthesis` 在 DOM 模拟库里同样没有实现，全都得打桩，多引依赖无收益；
- 后端新增 2 例（`tests/test_voice_api.py`）：>1MB 录音必须放行、超限必须 413 且不得转发上游。

---

## 5. 修改记录 [2026-08-31]

### 原方案的问题本质

- **P0 不是"配置写得小了"，而是"路径没归类"**：`_UPLOAD_PATHS` 是个白名单，ASR 上传的二进制 body 与简历上传同性质，却从来没被登记进去。这类缺陷的隐蔽性在于——短录音（<1MB）一切正常，只有长回答才炸，而长回答恰恰是语音面试的主场景。
- **P1 的"开麦不停朗读"是能力升级带来的回归**：v4.2 把主引擎从浏览器 STT 换成 MiMo ASR 时，新写的 `startRecording()` 漏抄了旧路径 `startListening()` 里的那句 `stopSpeaking()`。功能更强的新引擎，防御反而比它要替代的降级引擎少一行——典型的新路径未对齐既有契约。
- **P1 的熔断是"故障代价错配"**：一次抖动（网络 / 自动播放策略 / 413）代价是几十毫秒，而永久降级的代价是整场面试的音质。用不可逆手段响应可逆故障，比例失衡。
- **P3 的"免手"不是新功能，是既有能力的未接线**：VAD 的 `onAutoStop` 回调与面试页的 `voiceState` 状态机早就把基础设施铺好了，缺的只是把"说完"接到"提交"上那一小段。

### 用户批判性判断点

- 要求先做**只读审计再动手**，且审计必须给出严重度分级与真实代码位置——避免"我觉得这里可以优化"式的无据改动；
- 明确**不为微优化碰世代号函数**：原本计划把 `atob` 逐字节循环换成 `fetch(dataURL)`，评估后放弃——收益仅几毫秒，却要在全模块最 delicate 的竞态函数里新增一个 await 点，风险收益不成比例。这条取舍已写进本文档第 2.3 节。

### 修改后的方案

见第 2.2 节改动清单。全部改动已通过：

- `frontend` 构建（`npm run build`）；
- 前端 16 例新增测试（`npx vitest run`）；
- 后端 52 例语音相关测试（`pytest tests/test_voice_api.py tests/test_voice_service.py tests/test_offer_master_borrowings.py -q`）。

---

## 6. 已知局限（不掩饰）

- VAD **只判断"何时停"，不做端点检测、不裁剪音频**：开头等待与结尾 2.5s 静音仍在上送的音频里，付费时长与尾部幻听风险没有消除；
- 预滚校准在「开麦瞬间就在说话」时会高估底噪，需要更大声才能触发；
- 免手模式依赖云端 ASR（`voiceSupport.mimo`），浏览器原生 STT 没有自动停录语义，该模式下不启用；
- 音频不落库：报告里只有转写文本，没有原始音频与 ASR 置信度，复盘时无法判断某句话是否转写幻觉；
- 转写失败即丢弃 blob，无重试、无本地暂存；
- `/api/voice/*` 未挂鉴权依赖，`AUTH_ENABLED` 开启后仍公开，唯一防线是 `RATE_LIMIT_VOICE=20/min`（按 IP）。
