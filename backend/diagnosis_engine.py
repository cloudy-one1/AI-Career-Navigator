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

from backend.security import check_output
from backend.dimension_weights import (
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
权重反映该岗位对各维度的重视程度。权重高的维度请分析得更细致、评分更审慎，
但五个维度都必须给出独立评分，不得因权重低而省略。

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

【候选人简历（供参考）】{resume}

【岗位描述（供参考）】{jd}
{type_guidance}
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


def _build_diagnostician_system(weights: dict | None) -> str:
    """把动态权重注入 Diagnostician 系统提示词。"""
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

    # 弱项维度：优先用模型判断，非法则按"分数低 + 权重高"自行推断
    weakest = diagnosis.get("weakest_dimension", "")
    if weakest not in DIM_KEYS:
        valid = {k: v for k, v in dimensions.items() if v > 0}
        if valid:
            weakest = min(valid, key=lambda k: (valid[k], -w.get(k, 0.25)))
        else:
            weakest = ""

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
        "rewritten_answer": rewrite.get("rewritten_answer", ""),
        "key_changes": rewrite.get("key_changes", []) or [],
    }


# ===== 流式诊断（v2.6 主流程） =====

async def run_diagnosis_streaming(llm_client, question: str, answer: str,
                                  resume_text: str, jd_text: str,
                                  weights: dict | None = None,
                                  question_type: str = "mixed"
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

    # ---- Phase 1: Diagnostician ----
    yield {"type": "diagnosis_status",
           "data": {"phase": "diagnosing", "weight_desc": describe_weights(w)}}

    diag_prompt = DIAGNOSTICIAN_USER_PROMPT.format(
        question=question, answer=answer,
        resume=(resume_text or "")[:2000], jd=(jd_text or "")[:1000],
        type_guidance=type_guidance,
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
    把 LLMClient 的同步生成器包装为异步生成器，避免阻塞事件循环。
    逐块从工作线程取值，保证 WebSocket 心跳与并发会话不被卡死。
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    loop = asyncio.get_running_loop()
    _DONE = object()

    def _produce():
        try:
            for chunk in llm_client.chat_stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
        except Exception as e:  # noqa: BLE001
            logger.error(f"流式生成异常: {e}")
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(_DONE), loop).result()

    task = asyncio.get_running_loop().run_in_executor(None, _produce)
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item
    finally:
        await task


# ===== 兼容 v1 的非流式诊断 =====

async def run_diagnosis(llm_client, question: str, answer: str,
                        resume_text: str, jd_text: str,
                        weights: dict | None = None) -> dict:
    """
    非流式双 Agent 诊断（v1 兼容 + 降级路径）。
    返回 {diagnosis: {...}, rewrite: {...}}
    """
    w = weights or DEFAULT_WEIGHTS

    diag_prompt = DIAGNOSTICIAN_USER_PROMPT.format(
        question=question, answer=answer,
        resume=(resume_text or "")[:2000], jd=(jd_text or "")[:1000],
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
                       weights: dict | None = None) -> dict:
        """非流式诊断，返回标准化结果。"""
        raw = await run_diagnosis(
            llm_client=self.llm,
            question=question,
            answer=answer,
            resume_text=resume_text or "",
            jd_text=jd_text or "",
            weights=weights,
        )
        return normalize_result(raw.get("diagnosis", {}), raw.get("rewrite", {}), weights)

    # 向后兼容旧调用名
    async def diagnose_stream(self, question: str, answer: str,
                              resume_text: str = "", jd_text: str = "",
                              weights: dict | None = None) -> dict:
        return await self.diagnose(question, answer, resume_text, jd_text, weights)

    def stream(self, question: str, answer: str,
               resume_text: str = "", jd_text: str = "",
               weights: dict | None = None,
               question_type: str = "mixed") -> AsyncGenerator[dict, None]:
        """流式诊断，返回异步生成器（v2.6 WebSocket 主流程使用）。v2.7: 支持题型差异化。"""
        return run_diagnosis_streaming(
            llm_client=self.llm,
            question=question,
            answer=answer,
            resume_text=resume_text or "",
            jd_text=jd_text or "",
            weights=weights,
            question_type=question_type,
        )
