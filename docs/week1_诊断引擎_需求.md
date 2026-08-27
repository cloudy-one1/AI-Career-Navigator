# Week1 需求文档：双 Agent 诊断引擎（diagnosis_engine）

> 模块定位：项目核心价值模块（诊断引擎）。但需诚实修正——按代码行数实算，纯诊断核心（diagnosis_engine 468 + dimension_weights 214 ≈ 682 行）实际小于出题线（question_gen 431 + question_bank 137 + web_research 246 + data_support 72 ≈ 886 行），且 session/report/gap 等编排层主要服务于出题驱动。原"占开发精力 60%+"为立项时的差异化话术，已被代码分配证伪；详见 `docs/week6_核心价值重述_需求.md`。

## 一、模块目标

对候选人的面试回答做**结构化质量诊断**并给出**改写示范**，帮助候选人看见"答得差在哪、怎么改"。

诊断始终围绕四个维度评分：
1. STAR 完整度（star_completeness）
2. 量化程度（quantification）
3. 逻辑连贯性（logic_coherence）
4. 岗位相关性（job_relevance）

最终输出：四维度分项分（1-5）+ 综合分 + 诊断评语 + 改写示范 + 关键改动点。

## 二、当前实现状态（骨架已就绪）

文件：`backend/diagnosis_engine.py`，已实现核心双 Agent 主流程 `run_diagnosis()`：

- **Agent 1 — Diagnostician（`DIAGNOSTICIAN_PROMPT`）**：只诊断、不给任何修改建议。四维度逐项评分 + 2-3 句具体评语（要求引用原文作证据），综合分取四项平均。
- **Agent 2 — Rewriter（`REWRITER_PROMPT`）**：基于诊断结果给出改写示范 + `key_changes` 改动说明。约束：不编造经历、补全 STAR、加量化标记 `[建议填入具体数字]`、长度 1.2-1.5 倍。
- **主流程**：`Diagnostician(temperature=0.3)` → `Rewriter(temperature=0.5)`，均走 `llm_client.chat_json` 拿结构化 JSON，返回 `{"diagnosis": {...}, "rewrite": {...}}`。

输入参数已定义：`question / user_answer / resume_text(截断1500) / jd_text(截断1500)`。

## 三、技术方案

- **职责分离（不可合并，CODEBUDDY 架构约束）**：Diagnostician 当"裁判"，Rewriter 当"运动员"，禁止合并为单 Agent，杜绝"既当裁判又当运动员"的自评漏洞。两者各有独立 prompt、独立温度、独立调用。
- **两步流水线**：诊断先于改写，Rewriter 的输入显式包含 Diagnostician 的完整 JSON 输出，保证"改"对症下药。
- **结构化输出契约**：两 Agent 均强制只输出 JSON（`chat_json` 解析），前端可直接渲染四维度雷达/列表与改写对照。
- **轻量规则（CODEBUDDY 允许范围）**：后续可对四维度评分权重做参数化（如按 JD 动态调整岗位相关性权重）、增加"回答过短触发追问"等规则，无需额外批准。

## 四、涉及的知识点

- Prompt Engineering：角色设定、职责隔离、输出格式约束（strict JSON schema）。
- LLM 结构化生成与解析：`chat_json` 调用、temperature 对稳定性/创造性的权衡。
- STAR 行为面试模型、面试回答质量评估维度设计。
- 双 Agent 协作编排（编排顺序、上下文传递、职责解耦）。
- 文本截断策略（resume/jd 截断长度平衡上下文成本与相关性）。

## 五、待完善 / 优化点（后续迭代）

- [ ] `chat_json` 解析失败 / 字段缺失时的兜底与重试（当前无异常保护）。
- [ ] Diagnostician 评分的客观性校验（如跨题一致性、与简历/JD 的真实关联核对）。
- [ ] 四维度权重参数化（按 JD 岗位类型动态加权）。
- [ ] "回答过短/偏题"触发追问的轻量规则。
- [ ] 诊断与改写结果落库（关联 `db.py`，供历史对比，但历史趋势追踪属范围纪律外，需用户批准才做）。

## 六、修改记录 [2026-08-13]

- 原方案：顶部声明"项目核心价值模块，占开发精力 60%+。其余模块都是为它提供输入或锦上添花。"
- 用户指出的问题（[批判性思维]）：按代码行数实算，纯诊断核心（diagnosis_engine 468 + dimension_weights 214 ≈ 682 行）实际小于出题线（question_gen 431 + question_bank 137 + web_research 246 + data_support 72 ≈ 886 行），"60%+"是被代码分配证伪的立项话术；宪章开篇"诊断不是出题"的对立在出题—诊断耦合闭环架构上不成立。
- 修改后的方案：顶部声明改为诚实表述，显式标注"60%+"为已被证伪的差异化话术，并指向 `docs/week6_核心价值重述_需求.md`。

## 七、修改记录 [2026-08-13]（week7 整改）

> 由 `docs/week7_诚实披露与代码整改_需求.md` 驱动，针对深度审计提出的两处诊断引擎信任边界做行为修复。

- 原方案：`normalize_result()` 先信任模型自报的 `weakest_dimension`，仅当 key 不在 `DIM_KEYS` 才代码兜底；权重注入 prompt 写"权重高的维度请分析得更细致、评分更审慎"。
- 用户指出的问题本质（[批判性思维]）：① `weakest_dimension` 是无交叉校验的信任边界——模型声明合法但与实际分数不符时系统不校验，导致追问打偏 + 前端标签与雷达分数对不上，是最易被现场问倒的漏洞；② 权重注入 prompt 的"评分更审慎"无因果锚点，若权重只在 `weighted_score()` 加权平均阶段生效，这段 prompt 是噪声，且未经 A/B 验证。
- 修改后的方案：① `normalize_result` 用代码按 `(score, -weight)` 推导最弱维度并与模型声明交叉校验，不一致时以代码结果覆盖并 `logger.warning`；② 权重注入 prompt 改为中性诚实表述（权重仅用于加权总分、请一致评分），并加注释标明"prompt 影响打分分布未经 A/B 验证"。两项均为行为修复，不改变 WS 接口与双 Agent 架构约束。
