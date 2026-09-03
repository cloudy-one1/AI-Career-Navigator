"""
诊断维度动态权重 v2.6
根据 JD 分析五个诊断维度的相对重要性，输出加权配置。

设计约束：
- 诊断维度不可变，此模块只调整各维度的**权重**，不新增/删除维度。
- 权重和恒为 1.0，缺省退化为等权（0.20 x 5），保证行为向后兼容。
"""

import asyncio
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

DIM_KEYS = [
    "star_completeness",
    "quantification",
    "logic_coherence",
    "job_relevance",
    "professional_depth",
]

DIM_NAMES = {
    "star_completeness": "STAR 完整度",
    "quantification": "量化程度",
    "logic_coherence": "逻辑连贯性",
    "job_relevance": "岗位相关性",
    "professional_depth": "专业深度",
}

# 等权基线：无 JD 或分析失败时使用
DEFAULT_WEIGHTS = {k: 0.20 for k in DIM_KEYS}

# 单维权重的合理区间，防止 LLM 输出极端值把某一维度压到无效
MIN_WEIGHT = 0.10
MAX_WEIGHT = 0.40

WEIGHT_SYSTEM_PROMPT = """你是一位面试评估体系设计专家。
你的任务是根据岗位描述（JD），判断在评估该岗位候选人的面试回答时，
以下五个诊断维度各自应占多大权重。

五个维度的含义：
1. star_completeness（STAR 完整度）：回答是否具备情境-任务-行动-结果的完整结构
2. quantification（量化程度）：是否用具体数据、指标佐证成果
3. logic_coherence（逻辑连贯性）：因果链条是否清晰、表达是否有条理
4. job_relevance（岗位相关性）：回答是否紧扣该岗位的核心能力要求
5. professional_depth（专业深度）：回答是否体现对技术/领域知识的深层理解，而非停留在表面描述

权重判断参考：
- 偏数据/算法/增长/运营类岗位 → 量化程度更重要
- 偏架构/研发/技术攻坚岗位 → 逻辑连贯性 + 专业深度更重要
- 偏管理/项目/咨询/售前岗位 → STAR 完整度 + 岗位相关性更重要
- 岗位技能要求写得非常具体、门槛明确 → 岗位相关性 + 专业深度更重要
- 基础/初级岗位 → STAR 完整度更重要；高级/资深岗位 → 专业深度更重要

输出严格 JSON，五个权重之和必须等于 1.0，每个权重在 0.10 到 0.40 之间：
{
  "weights": {
    "star_completeness": 0.20,
    "quantification": 0.20,
    "logic_coherence": 0.20,
    "job_relevance": 0.20,
    "professional_depth": 0.20
  },
  "reason": "一句话说明为什么这样分配（不超过 60 字）"
}"""

WEIGHT_USER_PROMPT = """请为以下岗位设计五个诊断维度的权重：

【岗位描述】
{jd}

请输出 JSON。"""


def normalize_weights(raw: dict | None) -> dict:
    """
    将任意权重字典规整为合法权重：
    - 补齐缺失维度
    - 非数值/负数视为无效
    - 裁剪到 [MIN_WEIGHT, MAX_WEIGHT]
    - 归一化到和为 1.0
    """
    if not isinstance(raw, dict):
        return dict(DEFAULT_WEIGHTS)

    cleaned = {}
    for k in DIM_KEYS:
        v = raw.get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = DEFAULT_WEIGHTS[k]
        if v <= 0:
            v = DEFAULT_WEIGHTS[k]
        cleaned[k] = min(max(v, MIN_WEIGHT), MAX_WEIGHT)

    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)

    return {k: round(v / total, 4) for k, v in cleaned.items()}


def weighted_score(dimensions: dict, weights: dict | None) -> float:
    """
    按权重计算总分。dimensions 为 {维度: 分数}。
    只对实际存在且有效（>0）的维度加权，避免解析失败的 0 分拉低结果。
    """
    if not dimensions:
        return 0.0

    w = weights if weights else DEFAULT_WEIGHTS
    total_w = 0.0
    acc = 0.0
    for k, score in dimensions.items():
        try:
            s = float(score)
        except (TypeError, ValueError):
            continue
        if s <= 0:
            continue
        wk = float(w.get(k, DEFAULT_WEIGHTS.get(k, 0.20)))
        acc += s * wk
        total_w += wk

    if total_w <= 0:
        return 0.0
    return round(acc / total_w, 2)


def describe_weights(weights: dict) -> str:
    """生成人类可读的权重说明，用于注入 Prompt 与前端展示。"""
    parts = [f"{DIM_NAMES[k]} {weights.get(k, 0.20) * 100:.0f}%" for k in DIM_KEYS]
    return " / ".join(parts)


def top_dimension(weights: dict) -> str:
    """返回权重最高的维度 key。"""
    if not weights:
        return "job_relevance"
    return max(DIM_KEYS, key=lambda k: weights.get(k, 0))


async def analyze_jd_weights(llm_client, jd_text: str) -> dict:
    """
    分析 JD 得出五维度权重。
    先查缓存（基于 JD 文本 SHA256），未命中再调 LLM。
    返回 {"weights": {...}, "reason": str, "source": "llm"|"cache"|"default"}
    任何异常都退化为等权，不阻断面试流程。
    """
    # 中文 JD 信息密度高，8 字即可判断岗位方向（如"数据分析岗，要求量化"）
    if not jd_text or len(jd_text.strip()) < 8:
        logger.info("JD 文本过短或为空，采用五维等权评估")
        return {
            "weights": dict(DEFAULT_WEIGHTS),
            "reason": "未提供有效岗位描述，采用五维等权评估",
            "source": "default",
        }

    jd_normalized = jd_text.strip()[:2000]
    jd_hash = hashlib.sha256(jd_normalized.encode("utf-8")).hexdigest()

    # ─── 缓存检查 ───
    try:
        from .db import lookup_jd_weights
        cached = await lookup_jd_weights(jd_hash)
        if cached:
            logger.info(f"JD 权重命中缓存 (hash={jd_hash[:12]}...) → {describe_weights(cached['weights'])}")
            return cached
    except Exception as e:
        logger.debug(f"JD 权重缓存查询跳过: {e}")

    # ─── LLM 分析 ───
    try:
        raw = await asyncio.to_thread(
            llm_client.chat_json,
            WEIGHT_SYSTEM_PROMPT,
            WEIGHT_USER_PROMPT.format(jd=jd_normalized),
            0.2,
            600,
            "parse",   # v6.2: 任务级模型绑定（会话初始化链路）
        )
    except Exception as e:
        logger.warning(f"JD 权重分析调用失败，退化等权: {e}")
        return {
            "weights": dict(DEFAULT_WEIGHTS),
            "reason": "权重分析失败，采用五维等权评估",
            "source": "default",
        }

    if not isinstance(raw, dict) or raw.get("error"):
        logger.warning(f"JD 权重分析返回异常，退化等权: {str(raw)[:200]}")
        return {
            "weights": dict(DEFAULT_WEIGHTS),
            "reason": "权重分析结果无效，采用五维等权评估",
            "source": "default",
        }

    weights = normalize_weights(raw.get("weights"))
    reason = str(raw.get("reason", "")).strip() or "根据岗位描述动态分配"

    result = {"weights": weights, "reason": reason, "source": "llm"}

    # ─── 写入缓存 ───
    try:
        from .db import save_jd_weights
        await save_jd_weights(jd_hash, jd_normalized[:100], result)
    except Exception as e:
        logger.debug(f"JD 权重缓存写入跳过: {e}")

    logger.info(f"JD 动态权重: {describe_weights(weights)} | {reason}")
    return result
