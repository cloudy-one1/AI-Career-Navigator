"""
诊断引擎：双 Agent（Diagnostician + Rewriter）+ 流式输出。
v2 新增：流式诊断 + 追问触发信号。
v2.6 新增：
  - 诊断维度权重按 JD 动态注入，overall_score 改为加权平均
  - Diagnostician 直接产出 follow_up_question，追问与诊断合并为一次流式往返
  - 流式诊断产出与非流式一致的标准化结构，供 WebSocket 直接使用
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from .security import check_output
from .dimension_weights import (
    DEFAULT_WEIGHTS,
    DIM_KEYS,
    DIM_NAMES,
    describe_weights,
    weighted_score,
)

logger = logging.getLogger(__name__)

# ===== Diagnostician Prompt =====

DIAGNOSTICIAN_SYSTEM_PROMPT = """你是一位严格的面试回答诊断师。
你的唯一职责是诊断候选人的面试回答质量，给出客观评分。
你从以下五个维度依次分析，每个维度给出 1-5 分及简短评语：

1. STAR 完整度：是否包含 Situation/Task/Action/Result 四要素
2. 量化程度：是否有具体数据支撑（百分比、数值、时间跨度等）
3. 逻辑连贯性：因果链条是否清晰，要点之间是否衔接自然
4. 岗位相关性：回答是否紧扣岗位需求，展示了匹配的能力
5. 专业深度：是否体现了对技术/领域知识的深层理解，而非停留表面描述

【本次评估的维度权重】
{weight_desc}
注意：上述权重仅用于最终结果的加权总分计算，不要求你改变任一维度的打分标准。
请对每个维度独立、一致地评分（1-5 分），不要因为权重高低而放宽或收紧某个维度的评分。
（诚实说明：权重是否通过本 prompt 影响你的打分分布，未经 A/B 实验验证；
唯一确定生效的地方是后端的加权平均分公式，prompt 中的权重描述只是透明告知，不应偏置你的判断。）

【追问要求】
如果回答存在明显短板（任一维度 ≤ 2 分，或回答明显空泛缺少细节），
请在 follow_up_question 中给出一句真实面试官会问的追问，
追问要针对最薄弱的那个维度，自然、简短、直击要害，不超过 50 字。
如果回答质量已经足够（各维度均 ≥ 3 分且内容具体），follow_up_question 输出空字符串。

输出必须是严格的 JSON 格式：
{{
  "star_completeness": {{"score": 1-5, "comment": "评语"}},
  "quantification": {{"score": 1-5, "comment": "评语"}},
  "logic_coherence": {{"score": 1-5, "comment": "评语"}},
  "job_relevance": {{"score": 1-5, "comment": "评语"}},
  "professional_depth": {{"score": 1-5, "comment": "评语"}},
  "weakest_dimension": "五个维度 key 中得分最低的那个",
  "follow_up_question": "针对薄弱点的追问，无需追问时为空字符串",
  "overall_comment": "一句话综合评语",
  "risk_points": ["风险点1：如名词堆砌/方案空洞/逻辑矛盾等", "风险点2"]
}}

评分标准：
- 5分：优秀，结构完整、数据充分、逻辑严密、高度匹配
- 4分：良好，个别维度稍有不足
- 3分：一般，有明显短板
- 2分：较差，多个维度存在严重问题
- 1分：非常差，基本不具备面试回答要素"""

DIAGNOSTICIAN_USER_PROMPT = """请诊断以下面试回答：

【面试问题】{question}

【候选人回答】{answer}

{evidence}

【候选人简历（供参考）】{resume}

【岗位描述（供参考）】{jd}
{type_guidance}
{mode_instructions}
请按五个维度逐一分析，输出 JSON。"""

# ===== v2.7: 题型差异化评估指引 =====

_QUESTION_TYPE_GUIDANCE = {
    "self_intro": """【本题型：自我介绍】
针对此类问题，请特别关注：
- 结构是否清晰（时间线/能力模块/岗位匹配）
- 是否提炼了核心优势而非流水账
- 与岗位需求的关联度（展示了哪些匹配能力）
STAR 完整度在本题型中可适当降低要求（自我介绍不强制 STAR）。""",

    "knowledge": """【本题型：知识概念/技术基础】
针对此类问题，请特别关注：
- 专业深度：是否展示了底层原理的理解，而非停留在概念复述
- 是否结合了实际场景/案例来佐证理论认知
- 逻辑连贯性：概念之间的因果/层级关系是否清晰""",

    "project": """【本题型：项目经验】
针对此类问题，请特别关注：
- STAR 完整度：S/T/A/R 四要素是否齐全
- 量化程度：是否有具体数据（百分比/数值/时间）表征成果与影响
- 岗位相关性：项目技术与目标岗位所需技能的匹配程度""",

    "behavior": """【本题型：行为面试/软技能】
针对此类问题，请特别关注：
- 逻辑连贯性：叙事是否有清晰的因果链条
- 是否给出了具体事例而非空洞表态（"我做过" vs "我善于"）
- 回答是否体现了可迁移的能力素养而非背诵模板""",
}

# ===== Rewriter Prompt =====

REWRITER_SYSTEM_PROMPT = """你是一位面试回答改写专家。
你的任务是根据诊断结果，将候选人的原始回答改写成更优秀的版本。
改写不是推翻重做，而是在保留核心技术内容和真实经历的基础上：
1. 补充 STAR 结构中缺失的环节
2. 添加量化描述（如果原回答有提到但未量化的成果）
3. 理顺逻辑链条，让叙述更流畅
4. 突出与岗位需求的匹配点
5. 深化技术/领域知识的阐述（补充原回答中停留在表面的概念解释）

请优先修补诊断中得分最低、且权重较高的维度。

改写的长度应与原回答相近，不要过度扩充。
输出严格 JSON：
{
  "rewritten_answer": "改写后的回答",
  "key_changes": ["改动点1", "改动点2"]
}"""

REWRITER_USER_PROMPT = """请改写以下面试回答：

【原面试问题】{question}

【候选人原始回答】{answer}

【诊断结果】{diagnosis}

【本岗位维度权重】{weight_desc}

【候选人简历（供参考）】{resume}

【岗位描述（供参考）】{jd}

请输出改写后的回答和关键改动点。"""

# ===== v5.0: 证据硬规则 / 模式指令 / 不会答恢复 =====
# 对标 agent-interview-coach：追问与诊断必须"只能依据证据包或候选人亲述"，
# 杜绝凭常识硬编候选人经历。

EVIDENCE_USE_HARD_RULES = """【证据使用硬规则】
1. 你只能依据【本轮证据包】中的简历证据片段，或候选人本轮亲述，来评价/追问其项目与经历；
2. 大模型常识仅用于解释概念，严禁编造候选人的经历、项目细节或技术指标；
3. 证据包不足以支撑某个追问点时，应输出澄清式追问（"你刚才提到……能具体讲讲吗"），
   不要顺着候选人口述编造细节；
4. 若证据包与本轮亲述存在矛盾，务必指出矛盾点，这是真实面试官会抓的漏洞。"""

COACHING_RECOVERY_INSTRUCTION = """【不会答恢复流程】（候选人表示不会/不懂/没思路时进入）
请按以下顺序帮助候选人恢复：
1. 先讲清概念核心（通俗、简短）；
2. 给出该问题的项目表达骨架（一句话怎么组织）；
3. 提醒：简历中未支撑的细节不要硬说；
4. 只追问一个降阶问题（比原题简单，帮助找回思路）；
5. 保留薄弱点记录，但不要继续高压追问。"""

_MODE_INSTRUCTIONS = {
    "coach": "【教练模式】先补基础再追问：如果候选人回答暴露概念不牢，先讲清概念再追问，教学优先；评分照常进行。",
    "hardcore": """【拷打模式】你是高压面试官：
- 优先抓名词堆砌、过度包装、项目真实性漏洞；
- 对每个关键术语都追问"你怎么做的/踩过什么坑/数据从哪来"；
- 评语更锐利，明确指出包装与实力的差距；
- risk_points 必须写明被抓到的具体漏洞。""",
    "interview_only": "【只面试模式】只问不解析：overall_comment 用一句话简短反馈（≤40字），维度评语保持简短；重点放在 follow_up_question 上。",
    "traditional": "",
    "simulation": "",
}

# 薄弱点标签：诊断结束后从评分/评语/风险点中提取，供跨轮累计与复盘使用
WEAKNESS_KEYWORDS = (
    "MCP", "LangGraph", "RAG", "向量数据库", "系统设计", "架构设计", "高并发",
    "分布式", "项目真实性", "名词堆砌", "过度包装", "逻辑矛盾", "量化不足",
    "STAR不完整", "岗位匹配度", "专业深度", "简历与回答不符",
)


def _extract_weakness_tags(diagnosis: dict, dimensions: dict) -> list[str]:
    """从诊断结果提取薄弱点标签（低分维度 + 评语/风险点关键词命中）。"""
    tags: list[str] = []
    # 1) 低分维度（≤2 分）直接映射为维度标签
    low_dim_tags = {
        "star_completeness": "STAR不完整",
        "quantification": "量化不足",
        "logic_coherence": "逻辑矛盾",
        "job_relevance": "岗位匹配度",
        "professional_depth": "专业深度不足",
    }
    for key, score in dimensions.items():
        if 0 < score <= 2 and key in low_dim_tags:
            tags.append(low_dim_tags[key])
    # 2) 评语 / 风险点 / 追问中的关键词命中
    text = " ".join([
        str(diagnosis.get("overall_comment", "") or ""),
        *[str(x) for x in (diagnosis.get("risk_points", []) or [])],
        str(diagnosis.get("follow_up_question", "") or ""),
    ])
    for kw in WEAKNESS_KEYWORDS:
        if kw in text:
            tags.append(kw)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]


def _build_evidence_block(evidence_package: str) -> str:
    """把证据包文本转为诊断提示片段（空证据包则输出提示语）。"""
    if not evidence_package or not evidence_package.strip():
        return "【本轮证据包】本轮未注入简历证据。如候选人谈及经历，请用澄清式追问核实，不要编造。"
    return f"{evidence_package}\n\n{EVIDENCE_USE_HARD_RULES}"


def _build_mode_instructions(mode: str, recovery_requested: bool) -> str:
    """按模式组装诊断指令；recovery_requested 时追加不会答恢复流程。"""
    parts: list[str] = []
    if mode in _MODE_INSTRUCTIONS:
        parts.append(_MODE_INSTRUCTIONS[mode])
    if recovery_requested:
        parts.append(COACHING_RECOVERY_INSTRUCTION)
    return "\n\n".join(parts) if parts else ""


def _build_diagnostician_system(weights: dict | None) -> str:
    """把动态权重注入 Diagnostician 系统提示词。

    诚实说明：权重仅用于后端 weighted_score() 的加权总分；
    prompt 中的权重描述是否真正改变模型打分分布，未经 A/B 实验验证，
    因此 prompt 措辞已改为中性（不影响打分标准），避免制造"权重已影响评分"的假象。
    """
    w = weights or DEFAULT_WEIGHTS
    return DIAGNOSTICIAN_SYSTEM_PROMPT.format(weight_desc=describe_weights(w))


def _extract_json(raw: str) -> dict | None:
    """从可能带 markdown 围栏或前后缀文本的输出中提取 JSON。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _parse_diagnosis_fallback(raw_text: str) -> dict:
    """当 JSON 解析失败时，返回可识别的降级结构。"""
    return {
        "star_completeness": {"score": 0, "comment": "无法解析"},
        "quantification": {"score": 0, "comment": "无法解析"},
        "logic_coherence": {"score": 0, "comment": "无法解析"},
        "job_relevance": {"score": 0, "comment": "无法解析"},
        "professional_depth": {"score": 0, "comment": "无法解析"},
        "weakest_dimension": "",
        "follow_up_question": "",
        "overall_score": 0,
        "overall_comment": "诊断结果解析失败，请稍后重试",
    }


def normalize_result(diagnosis: dict, rewrite: dict, weights: dict | None) -> dict:
    """
    把 Diagnostician / Rewriter 的原始 JSON 规整为前端与状态机共用的标准结构。
    v2.6: overall_score 改为按权重加权，并附带 weakest_dimension / follow_up_question。
    """
    w = weights or DEFAULT_WEIGHTS
    diagnosis = diagnosis or {}
    rewrite = rewrite or {}

    dimensions = {}
    details = {}
    for key in DIM_KEYS:
        item = diagnosis.get(key)
        if isinstance(item, dict):
            try:
                score = float(item.get("score", 0))
            except (TypeError, ValueError):
                score = 0.0
            comment = str(item.get("comment", ""))
        else:
            # 兼容 LLM 直接给数字的情况
            try:
                score = float(item)
            except (TypeError, ValueError):
                score = 0.0
            comment = ""
        dimensions[key] = score
        details[key] = {"score": score, "comment": comment}

    overall = weighted_score(dimensions, w)

    # 弱项维度：代码按"低分 + 高权重"推导，与模型声明交叉校验。
    # 用代码结果兜底模型声明，消除"模型声明合法但与真实分数不符"的信任边界
    # （该边界会导致追问打偏、前端"最薄弱维度"标签与实际分数对不上）。
    valid_dims = {k: v for k, v in dimensions.items() if v > 0}
    code_weakest = (
        min(valid_dims, key=lambda k: (valid_dims[k], -w.get(k, 0.25)))
        if valid_dims else ""
    )
    model_weakest = str(diagnosis.get("weakest_dimension", "")).strip()
    if model_weakest in DIM_KEYS and model_weakest == code_weakest:
        weakest = model_weakest
    else:
        if model_weakest in DIM_KEYS:
            # 声明 key 合法但与真实最低分维度不符 → 以真实分数覆盖
            logger.warning(
                f"模型 weakest_dimension({model_weakest}) 与真实最低分维度"
                f"({code_weakest}) 不符，已按真实分数重算"
            )
        weakest = code_weakest

    follow_up = str(diagnosis.get("follow_up_question", "") or "").strip()

    # v2.7: 提取风险点
    rp = diagnosis.get("risk_points", [])
    if isinstance(rp, str):
        risk_points = [rp] if rp else []
    elif isinstance(rp, list):
        risk_points = [str(x) for x in rp if x]
    else:
        risk_points = []

    return {
        "dimensions": dimensions,
        "dimension_details": details,
        "weights": dict(w),
        "weight_desc": describe_weights(w),
        "overall_score": overall,
        "overall_comment": diagnosis.get("overall_comment", ""),
        "weakest_dimension": weakest,
        "weakest_dimension_name": DIM_NAMES.get(weakest, ""),
        "follow_up_question": follow_up,
        "risk_points": risk_points,
        "weakness_tags": _extract_weakness_tags(diagnosis, dimensions),
        "rewritten_answer": rewrite.get("rewritten_answer", ""),
        "key_changes": rewrite.get("key_changes", []) or [],
    }


# ===== 流式诊断（v2.6 主流程） =====

async def run_diagnosis_streaming(llm_client, question: str, answer: str,
                                  resume_text: str, jd_text: str,
                                  weights: dict | None = None,
                                  question_type: str = "mixed",
                                  evidence_package: str = "",
                                  mode: str = "simulation",
                                  recovery_requested: bool = False,
                                  ) -> AsyncGenerator[dict, None]:
    """
    流式执行双 Agent 诊断，逐条 yield dict 消息（由调用方转发给 WebSocket）。

    消息类型：
      {"type": "diagnosis_status", "data": {"phase": "diagnosing"}}
      {"type": "diagnosis_chunk",  "data": {"text": "片段"}}
      {"type": "diagnosis_status", "data": {"phase": "rewriting"}}
      {"type": "rewrite_chunk",    "data": {"text": "片段"}}
      {"type": "diagnosis_done",   "data": {标准化结果}}

    v2.7: question_type 用于注入题型差异化评估指引。
    注意：双 Agent 仍是两次独立调用，不合并（架构约束）。
    """
    w = weights or DEFAULT_WEIGHTS
    type_guidance = _QUESTION_TYPE_GUIDANCE.get(question_type, "")
    evidence_block = _build_evidence_block(evidence_package)
    mode_instructions = _build_mode_instructions(mode, recovery_requested)

    # ---- Phase 1: Diagnostician ----
    yield {"type": "diagnosis_status",
           "data": {"phase": "diagnosing", "weight_desc": describe_weights(w)}}

    diag_prompt = DIAGNOSTICIAN_USER_PROMPT.format(
        question=question, answer=answer,
        evidence=evidence_block,
        resume=(resume_text or "")[:2000], jd=(jd_text or "")[:1000],
        type_guidance=type_guidance,
        mode_instructions=mode_instructions,
    )

    diag_chunks: list[str] = []
    async for chunk in _astream(
        llm_client,
        _build_diagnostician_system(w),
        diag_prompt,
        temperature=0.3,
        max_tokens=1500,
    ):
        diag_chunks.append(chunk)
        yield {"type": "diagnosis_chunk", "data": {"text": chunk}}

    diag_raw = "".join(diag_chunks)

    safe, leaked = check_output(diag_raw)
    if not safe:
        logger.warning(f"诊断输出检测到泄漏: {leaked}")

    diagnosis = _extract_json(diag_raw) or _parse_diagnosis_fallback(diag_raw)

    # ---- Phase 2: Rewriter ----
    yield {"type": "diagnosis_status", "data": {"phase": "rewriting"}}

    rewrite_prompt = REWRITER_USER_PROMPT.format(
        question=question, answer=answer,
        diagnosis=json.dumps(diagnosis, ensure_ascii=False),
        weight_desc=describe_weights(w),
        resume=(resume_text or "")[:2000], jd=(jd_text or "")[:1000],
    )

    rewrite_chunks: list[str] = []
    async for chunk in _astream(
        llm_client,
        REWRITER_SYSTEM_PROMPT,
        rewrite_prompt,
        temperature=0.6,
        max_tokens=1500,
    ):
        rewrite_chunks.append(chunk)
        yield {"type": "rewrite_chunk", "data": {"text": chunk}}

    rewrite_raw = "".join(rewrite_chunks)

    safe2, leaked2 = check_output(rewrite_raw)
    if not safe2:
        logger.warning(f"改写输出检测到泄漏: {leaked2}")

    rewrite = _extract_json(rewrite_raw) or {
        "rewritten_answer": rewrite_raw.strip(),
        "key_changes": [],
    }

    yield {"type": "diagnosis_done",
           "data": normalize_result(diagnosis, rewrite, w)}


async def _astream(llm_client, system_prompt: str, user_prompt: str,
                   temperature: float, max_tokens: int) -> AsyncGenerator[str, None]:
    """
    异步流式诊断：直接 await 底层 AsyncOpenAI 流式客户端逐块产出。
    v3.2: 移除原线程池 + asyncio.Queue + run_coroutine_threadsafe().result() 桥接
    （该桥接是为适配同步 SDK 引入的技术债，且 worker 线程 .result() 在队列满时
    可能永久挂起 → 线程泄漏）。改用 AsyncOpenAI 后无阻塞、无跨线程桥接。
    """
    try:
        async for chunk in llm_client.chat_stream_async(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk
    except Exception as e:  # noqa: BLE001
        logger.error(f"流式生成异常: {e}")


# ===== 兼容 v1 的非流式诊断 =====

async def run_diagnosis(llm_client, question: str, answer: str,
                        resume_text: str, jd_text: str,
                        weights: dict | None = None,
                        evidence_package: str = "",
                        mode: str = "simulation",
                        recovery_requested: bool = False,
                        question_type: str = "mixed") -> dict:
    """
    非流式双 Agent 诊断（v1 兼容 + 降级路径）。
    返回 {diagnosis: {...}, rewrite: {...}}
    v5.0: 支持证据包 / 模式指令 / 不会答恢复注入。
    """
    w = weights or DEFAULT_WEIGHTS
    evidence_block = _build_evidence_block(evidence_package)
    mode_instructions = _build_mode_instructions(mode, recovery_requested)
    type_guidance = _QUESTION_TYPE_GUIDANCE.get(question_type, "")

    diag_prompt = DIAGNOSTICIAN_USER_PROMPT.format(
        question=question, answer=answer,
        evidence=evidence_block,
        resume=(resume_text or "")[:2000], jd=(jd_text or "")[:1000],
        type_guidance=type_guidance,
        mode_instructions=mode_instructions,
    )
    diag_raw = await asyncio.to_thread(
        llm_client.chat,
        _build_diagnostician_system(w),
        diag_prompt,
        0.3,
        1500,
        {"type": "json_object"},
    )
    diagnosis = _extract_json(diag_raw) or _parse_diagnosis_fallback(diag_raw)

    rewrite_prompt = REWRITER_USER_PROMPT.format(
        question=question, answer=answer,
        diagnosis=json.dumps(diagnosis, ensure_ascii=False),
        weight_desc=describe_weights(w),
        resume=(resume_text or "")[:2000], jd=(jd_text or "")[:1000],
    )
    rewrite_raw = await asyncio.to_thread(
        llm_client.chat,
        REWRITER_SYSTEM_PROMPT,
        rewrite_prompt,
        0.5,
        1500,
        {"type": "json_object"},
    )
    rewrite = _extract_json(rewrite_raw) or {
        "rewritten_answer": (rewrite_raw or "").strip(),
        "key_changes": [],
    }

    return {"diagnosis": diagnosis, "rewrite": rewrite}


# ===== 诊断引擎类（供 InterviewSession 使用）=====

class DiagnosisEngine:
    """
    双 Agent 诊断引擎封装类。
    供 InterviewSession 调用，屏蔽底层流式/非流式细节。
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def diagnose(self, question: str, answer: str,
                       resume_text: str = "", jd_text: str = "",
                       weights: dict | None = None,
                       evidence_package: str = "",
                       mode: str = "simulation",
                       recovery_requested: bool = False,
                       question_type: str = "mixed") -> dict:
        """非流式诊断，返回标准化结果。v5.0: 支持证据包/模式/恢复注入。"""
        raw = await run_diagnosis(
            llm_client=self.llm,
            question=question,
            answer=answer,
            resume_text=resume_text or "",
            jd_text=jd_text or "",
            weights=weights,
            evidence_package=evidence_package,
            mode=mode,
            recovery_requested=recovery_requested,
            question_type=question_type,
        )
        return normalize_result(raw.get("diagnosis", {}), raw.get("rewrite", {}), weights)

    # 向后兼容旧调用名
    async def diagnose_stream(self, question: str, answer: str,
                              resume_text: str = "", jd_text: str = "",
                              weights: dict | None = None,
                              evidence_package: str = "",
                              mode: str = "simulation",
                              recovery_requested: bool = False) -> dict:
        return await self.diagnose(question, answer, resume_text, jd_text, weights,
                                   evidence_package, mode, recovery_requested)

    def stream(self, question: str, answer: str,
               resume_text: str = "", jd_text: str = "",
               weights: dict | None = None,
               question_type: str = "mixed",
               evidence_package: str = "",
               mode: str = "simulation",
               recovery_requested: bool = False) -> AsyncGenerator[dict, None]:
        """流式诊断，返回异步生成器（v2.6 WebSocket 主流程使用）。
        v2.7: 支持题型差异化；v5.0: 支持证据包/模式/恢复注入。"""
        return run_diagnosis_streaming(
            llm_client=self.llm,
            question=question,
            answer=answer,
            resume_text=resume_text or "",
            jd_text=jd_text or "",
            weights=weights,
            question_type=question_type,
            evidence_package=evidence_package,
            mode=mode,
            recovery_requested=recovery_requested,
        )
