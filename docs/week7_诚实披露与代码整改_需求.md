# Week7 需求文档：诚实披露与代码整改

> 背景：2026-08-13 用户对系统做了一次深度审计，提出五处带具体代码依据的质疑。
> 本轮不新增功能，只做两类动作：① 文档主动披露（不改行为）；② 四项代码修复（改行为）。
> 范围经用户确认（提问表单）：学术诚信走文档披露、不动代码；四项代码修复全做。

## 一、五处质疑与代码事实（全部经实读源码核实属实）

### 质疑一：`diagnosis_engine.py` 三处经不起推敲
1. **权重注入的无因果性**：`DIAGNOSTICIAN_SYSTEM_PROMPT` 第 38-41 行写"权重高的维度请分析得更细致、评分更审慎，但五个维度都必须给出独立评分"。而权重真正生效处在 `normalize_result()` 的纯数学 `weighted_score(dimensions, w)`。prompt 里"评分更审慎"无任何可验证的因果锚点，没有做过 A/B 验证有无这段字模型打分分布会变——若只在加权平均阶段生效，这段 prompt 文字是噪声。
2. **`weakest_dimension` 无交叉校验**：`normalize_result()` 第 218-225 行先信任模型自报的 `weakest_dimension`，仅当 key 不在 `DIM_KEYS` 才用代码兜底。若模型报的 key 合法但与自身分数不吻合（如写了 `job_relevance` 但实际 `professional_depth` 更低），系统不校验直接采用 → 追问可能打偏、前端"最薄弱维度"标签与雷达图分数对不上。
3. **`_astream` 桥接是技术债**：第 342-374 行用 `asyncio.Queue` + `run_in_executor` + `run_coroutine_threadsafe(...).result()` 把同步 `chat_stream` 包成异步生成器。而 `llm_client.py` 用的是同步 `OpenAI` 客户端；OpenAI SDK 同时提供 `AsyncOpenAI`，可直接 `async for` 流式消费。死锁论据：worker 线程的 `.result()` 在队列满（maxsize=64）时阻塞等主协程 `queue.get()` 消费，消费协程被取消则线程永久挂起 → 线程泄漏。

### 质疑二：`gap_analyzer.py` + `market/*` 诚信矛盾（核心关切）
Gap 分析的"市场基准交叉参考"数据来自 `market.db`，而管道是 job-crawler `data.db` → importer → store → `market.db`。这与此前"job-crawler 因学术诚信被排除复用（产物不能复用）"的口径直接冲突。CODEBUDDY.md 对此仅一句轻描淡写的"被推翻"，无利弊审视。两层问题：(a)"数据资产≠代码复现"论证站不住——若 Gap 分析核心价值（市场基准数据）完全来自另一已提交项目采集的数据，该功能新颖工作量只是 importer 字段映射 + store upsert；(b) 决策反转未真正被审视，像遇到"重新用 Playwright 采集太麻烦"后找技术理由绕过自己设的红线。

### 质疑三：`dimension_weights.py` 设计合理但假设未验证
`normalize_weights()` 裁剪 `[0.10, 0.40]` + 归一化、SHA256 缓存扎实。但未验证：LLM 判断"该 JD 更看重量化还是逻辑"的准确性与一致性从未测过（`temperature=0.2` 非完全确定），"千岗千面"卖点稳定性无可辩护证据。

### 质疑四：`security.py` 输出检测 + 英文规则
1. `check_output()` 第 163-180 行检测到泄漏仅 `logger.warning`，调用方第 300-302、329-331 行只记日志、不阻断不脱敏——只有监控价值、无防护价值。
2. 正则列表第 37-63 行大量英文模式（`you are` / `ignore previous` / `jailbreak` / `DAN` / `do anything now` 等），产品是中文求职者中文回答场景，英文规则命中率极低，更像"看起来全面"。

### 质疑五：测试套件验证壳非核
50 用例中 `test_gap_analyzer` / `test_dimension_weights` 测纯函数（规范化/加权/降级），无一条验证 LLM 输出语义合理性。"50 用例通过 ≠ 核心被验证"的错觉确实存在。

## 二、整改方案与修改后文案

### A. 学术诚信（文档披露，不动代码）—— 用户选定方案
在 CODEBUDDY.md「已知局限」、README.md「已知局限」、gap_analyzer.py 模块 docstring 明文写：
> 市场基准数据来自本人此前已完成并提交的采集项目（job-crawler）的 `data.db`，本次仅做管道整合（importer 字段映射 + store upsert），**不含数据采集工作量**。如评审基于"本次周期实际产出了什么"，此部分可辩护性较弱，已主动披露。

### B. 代码修复一：`weakest_dimension` 交叉校验（diagnosis_engine.py `normalize_result`）
```python
    # 代码推导最弱维度（按 低分+高权重），与模型声明交叉校验
    valid_dims = {k: v for k, v in dimensions.items() if v > 0}
    code_weakest = (
        min(valid_dims, key=lambda k: (valid_dims[k], -w.get(k, 0.25)))
        if valid_dims else ""
    )
    model_weakest = str(diagnosis.get("weakest_dimension", "")).strip()
    if model_weakest in DIM_KEYS and model_weakest == code_weakest:
        weakest = model_weakest
    else:
        if model_weakest in DIM_KEYS:  # 声明合法但与真实最低分不符 → 覆盖
            logger.warning(
                f"模型 weakest_dimension({model_weakest}) 与真实最低分维度"
                f"({code_weakest}) 不符，已按真实分数重算"
            )
        weakest = code_weakest
```
效果：模型声明合法但与实际分数不符时，以真实分数覆盖，消除追问打偏与标签错配。

### C. 代码修复二：`_astream` 异步化（llm_client.py + diagnosis_engine.py）
- `llm_client.py`：`_init_client()` 增加 `self.async_client = AsyncOpenAI(api_key=..., base_url=...)`；新增 `async def chat_stream_async(...)` 直接 `async for` 流式消费；`switch_provider()` 复用 `_init_client()` 同步重建两个客户端。
- `diagnosis_engine.py`：重写 `_astream` 为直接 `async for chunk in llm_client.chat_stream_async(...): yield chunk`，删除 `asyncio.Queue` / `run_in_executor` / `run_coroutine_threadsafe().result()`。同步 `chat_stream` 经 grep 确认仅 `_astream` 调用，可替换。

### D. 代码修复三：权重注入 prompt 诚实化（diagnosis_engine.py）
第 38-41 行改为：
```
【本次评估的维度权重】
{weight_desc}
注意：上述权重仅用于最终结果的加权总分计算，不要求你改变任一维度的打分标准。
请对每个维度独立、一致地评分（1-5 分），不要因为权重高低而放宽或收紧某个维度的评分。
（诚实说明：权重是否通过 prompt 影响你的打分分布未经 A/B 验证；唯一确定生效的地方是后端的加权平均分公式。）
```
并在 `_build_diagnostician_system` 加注释声明同样事实。工程正向收益：防止模型按权重偏置打分。

### E. 代码修复四：security 输出检测诚实化（security.py）
- 模块 docstring 与 `check_output` 文档字符串明确"仅监控不阻断，非防护边界"。
- 移除纯英文句式规则（`you are (a|an|now|actually)` / `ignore previous|above|all|instructions` / `forget previous|above|all|instructions` / `do not (act|pretend|roleplay)` / `do anything now`），保留跨语言有效的 token/特殊字符/`jailbreak`/`DAN`/`system prompt` 模式；加威胁模型注释说明保留依据（中文面试场景下纯英文句式命中率近零）。

## 三、修改记录 [2026-08-13]（指向本文件及 week1）

### 修改点 1：`normalize_result` 的 weakest_dimension 信任边界
- 原方案：先信任模型自报 `weakest_dimension`，仅当 key 不在 `DIM_KEYS` 才代码兜底。
- 用户指出的问题本质（[批判性思维]）：这是没有交叉校验的信任边界——模型声明合法但与实际分数不符时，系统不校验直接采用，导致追问打偏 + 前端标签与雷达分数对不上，是最易被现场问倒的漏洞。
- 修改后的方案：用代码按 `(score, -weight)` 推导最弱维度，与模型声明比对；不一致时以代码结果覆盖并 `logger.warning`，彻底消除信任边界。

### 修改点 2：`_astream` 同步桥接技术债
- 原方案：`asyncio.Queue` + `run_in_executor` + `run_coroutine_threadsafe().result()` 包同步 `chat_stream`。
- 用户指出的问题本质（[批判性思维]）：这是为适配同步 SDK 引入的架构妥协，非必须设计；且 `.result()` 在队列满 + 消费协程取消时会线程泄漏。OpenAI SDK 自带 `AsyncOpenAI` 可直接 `async for`。
- 修改后的方案：`llm_client` 增加 `AsyncOpenAI` 客户端与 `chat_stream_async`，`_astream` 改为直接 `async for`，移除全部线程/队列桥接。

### 修改点 3：权重注入 prompt 因果未验证
- 原方案：prompt 写"权重高的维度请分析得更细致、评分更审慎"。
- 用户指出的问题本质（[批判性思维]）：这段话对 LLM 指导逻辑模糊，权重若只在 `weighted_score()` 加权平均阶段生效，注入 prompt 就是噪声；没有 A/B 验证过它是否改变打分分布——属"显得更懂行"的伪装。
- 修改后的方案：改为中性诚实表述（权重仅用于加权总分，请一致评分），并加注释标明该 prompt 影响未经 A/B 验证。

### 修改点 4：security 输出检测与英文规则
- 原方案：`check_output` 仅 `logger.warning`，请求原样返回前端；英文规则覆盖率高但中文场景命中率近零。
- 用户指出的问题本质（[批判性思维]）：输出检测只有监控价值无防护价值，与"5 层安全防护"防御想象有落差；英文规则是"看起来全面"而非风险建模。
- 修改后的方案：明确文档/注释 `check_output` 仅监控不阻断；移除纯英文句式规则，保留跨语言有效 token 并加威胁模型注释。

### 修改点 5（学术诚信，属用户决策的边界声明）
- 原口径："job-crawler 因学术诚信被排除复用（产物不能复用）"。
- 用户批判（[批判性思维]）：当前实现把"代码不复用"重新解释为"数据资产可迁移"，与既往口径冲突；"数据资产≠代码复现"论证站不住——若 Gap 分析核心价值（市场基准数据）全来自另一已提交项目，该功能新颖工作量只是管道脚本。且该决策反转未被真正利弊审视。
- 用户决策：走文档主动披露，不动代码。在 CODEBUDDY.md / README / gap_analyzer 注释明文披露数据来源，属于用户本人负责的边界声明（AI 只记录决策结果）。

## 四、批判性思维归档（[批判性思维]）

本次用户展示了五类典型批判性信号，按 CODEBUDDY.md「批判性思维归纳」规则归档：
1. **要求审计/对照核查**：对权重注入、weakest 来源、_astream 桥接逐条要求"用代码事实证伪/验证"，而非接受 AI 的口头辩护。
2. **质疑设计取舍/推翻重来**：指出 `_astream` 桥接是技术债、权重 prompt 是噪声、安全输出检测是"看起来全面"，要求诚实化。
3. **范围纪律克制判断**：学术诚信问题明确选择"文档披露"而非砍功能，体现"课程项目阶段不做过工程"的取舍清醒。
4. **纠正方向偏离**：当用户此前口径（job-crawler 排除复用）与当前实现（导入其 data.db）冲突，要求正视而非回避，并主动提出"答辩前想清楚"。
5. **区分可验证与不可验证**：明确"50 用例通过 ≠ 核心被验证"，要求把"测试验证壳非核"写入诚实披露。

这些信号均已写入本文件「修改记录」段，并在 CODEBUDDY.md「已知局限」与 README「已知局限」同步披露。
