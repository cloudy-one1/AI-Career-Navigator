"""
v6.3: 评分规则化修正项（借鉴 mock-interviewer 的 references/评分标准.md「加减分项」）。

为什么要有这一层：
  纯 LLM 评分有两个固有缺陷——
    1) **不可解释**：候选人问"为什么这题扣了分"，只能回答"模型觉得"；
    2) **不可复现**：同一条回答重跑一次，分数可能不同。
  加减分项是**可被确定性检测的行为信号**（有没有数字、有没有甩锅、是不是名词堆砌），
  用正则就能判定，因此：每条修正都带 evidence（命中的原文片段）、可复现、可测试。

设计边界（重要）：
  - 修正项**不是评分主体**，只是对 LLM 五维分的**微调**；
  - 每题总扣分封顶 MAX_PENALTY_PER_ANSWER，总加分封顶 MAX_BONUS_PER_ANSWER，
    单维度封顶 MAX_ABS_PER_DIMENSION —— 防止规则喧宾夺主；
  - 调整后分数夹紧到 [1, 5]，且**只作用于已评分（>0）的维度**：
    0 分表示"未评分/解析失败"，规则不得把没有分的维度抬起来。

诚实披露（两处局限，不要掩饰）：
  1. **维度映射是近似的**。原作四维度含「表达结构」「应变能力」，本项目五维度（宪章约束 3）
     没有对应项，因此「甩锅」「过度防御」这类应变类信号只能就近映射到 STAR 完整度 /
     逻辑连贯性，语义上并非严格等价。
  2. **存在双重惩罚风险**。模型若已因"没有数据"把量化程度打到 1 分，
     规则再 -1 会被夹紧到 1 分，等于无额外惩罚；但若模型给了 3 分而规则判定无数据，
     则构成"模型与规则各扣一次"。这是本设计的已知代价，换取的是可解释性。
     缓解手段是上述封顶机制，而非消除。

分层契约：本模块属 L2 领域层，仅依赖标准库，禁止 import L3/L4。
被 L3（diagnosis_engine）调用。
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ===== 维度 key（与 dimension_weights.DIM_KEYS 对齐，此处不 import 以避免层间耦合） =====
DIM_STAR = "star_completeness"
DIM_QUANT = "quantification"
DIM_LOGIC = "logic_coherence"
DIM_JOB = "job_relevance"
DIM_DEPTH = "professional_depth"

# ===== 封顶参数 =====
MAX_PENALTY_PER_ANSWER = 3.0    # 单条回答累计扣分上限
MAX_BONUS_PER_ANSWER = 2.0      # 单条回答累计加分上限
MAX_ABS_PER_DIMENSION = 2.0     # 单一维度累计调整绝对值上限
SCORE_FLOOR = 1.0
SCORE_CEIL = 5.0

# ===== 检测用正则 / 词表 =====

# 量化指标：数字 + 单位。命中即视为"有数据支撑"
_QUANTIFIED_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|倍|万|亿|ms|毫秒|qps|tps|人|天|小时|分钟|秒|k\b|w\b)",
    re.IGNORECASE,
)

# 带比例单位的数值（30% / 1.5 倍）—— 只统计这类，用于检测"同一指标出现两个不同数字"
# 为什么限定比例单位：绝对量（"优化了 3 个接口""耗时 200ms"）本就可以并存，
# 只有"提升了 30%"与"提升了 50%"这种同量纲比例冲突才是真正的自相矛盾。
_RATIO_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|倍)")

# 成果动词（无数值跟随也算，"提升了不少"同样属于该量化而未量化）
_OUTCOME_VERBS = ("提升", "提高", "降低", "减少", "增长", "下降", "缩短", "节省", "优化", "改善")

# 因果 / 推导连接词：出现说明回答有推演，不只是罗列
_CAUSAL_WORDS = ("因为", "所以", "导致", "从而", "因此", "于是", "结果", "带来", "使得", "由于", "这样一来")

# 步骤 / 展开词
_STEP_WORDS = ("首先", "其次", "然后", "最后", "第一", "第二", "步骤", "流程", "阶段")

# 不会答 / 示弱标记（与 session.UNCERTAIN_ANSWER_MARKERS 保持一致，此处独立定义以免 L2→L3 反向依赖）
_UNCERTAIN_MARKERS = (
    "不会", "不懂", "没思路", "答不上来", "不知道", "不清楚",
    "没做过", "不太了解", "不了解", "没接触过", "忘了",
)

# 坦诚后的学习方向词
_LEARNING_WORDS = ("后续", "接下来我会", "我会去", "打算", "需要补", "之后补充", "去学习", "查一下", "回去看", "补一下")

# 失败 / 教训词
_FAILURE_WORDS = ("失败", "踩坑", "教训", "返工", "走弯路", "事故", "搞砸", "回滚", "翻车")
# 反思 / 改进词
_REFLECT_WORDS = ("后来", "之后", "于是", "改进", "复盘", "总结", "重新", "吸取")

# 甩锅 / 外部归因词
_BLAME_WORDS = (
    "不是我负责", "不归我", "其他团队", "别的团队", "是他们", "别人做的",
    "产品要求的", "领导安排的", "不是我的问题", "跟我没关系", "前端的问题", "后端的问题",
)

# 串联词（跨项目/跨模块关联的信号）
_LINK_WORDS = ("同时", "另外", "还有", "以及", "与此", "类似地", "另一个", "同样的思路", "借鉴")

# 中文/英文实词（用于计算问题—回答的重叠度）
_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+#-]{1,}|[\u4e00-\u9fff]{2,4}")

# 并列分隔片段（名词堆砌检测）
_LIST_SPLIT_RE = re.compile(r"[、,，/]|以及|还有")


@dataclass
class Adjustment:
    """一条评分修正。"""

    key: str
    label: str
    dimension: str
    delta: float
    evidence: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "dimension": self.dimension,
            "delta": self.delta,
            "evidence": self.evidence,
        }


def _snippet(text: str, start: int, end: int, width: int = 12) -> str:
    """截取命中片段的上下文作为 evidence（截断到 40 字，避免污染报告）。"""
    left = max(0, start - width)
    right = min(len(text), end + width)
    frag = text[left:right].strip()
    if len(frag) > 40:
        frag = frag[:40] + "…"
    return frag


def _first_hit(text: str, words) -> tuple[str, int]:
    """返回 (命中词, 位置)；未命中返回 ("", -1)。"""
    for w in words:
        pos = text.find(w)
        if pos >= 0:
            return w, pos
    return "", -1


def _overlap_ratio(question: str, answer: str) -> float:
    """问题与回答的 2-gram 重叠率（Jaccard），用于检测答非所问。

    为什么用 2-gram 而不是"关键词命中"：中文回答常换同义表述，
    关键词硬匹配会把合理回答误判为跑题；2-gram 对同义替换更宽容，
    只在真正"说的完全不是一回事"时才给出低分。
    """
    def grams(s: str) -> set[str]:
        s = re.sub(r"\s+", "", s or "")
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()

    gq, ga = grams(question), grams(answer)
    if not gq or not ga:
        return 0.0
    return len(gq & ga) / len(gq | ga)


# ===================== 检测规则 =====================
# 每条规则返回 Adjustment 或 None。约定：matcher(question, answer) -> Adjustment | None


def _rule_no_quantification(q: str, a: str):
    """成果描述无量化：说了"提升"却没有任何数字。"""
    verb, pos = _first_hit(a, _OUTCOME_VERBS)
    if not verb or _QUANTIFIED_RE.search(a):
        return None
    return Adjustment("no_quantification", "成果描述未量化", DIM_QUANT, -1.0,
                      _snippet(a, pos, pos + len(verb)))


def _nearest_verb(prefix: str) -> str:
    """取前缀中**最后出现**的成果动词——离数值最近的那个才是这个数字的真正归属。

    为什么不能简单地"正则匹配动词+数值"：那样 "优化后性能提升了 30%" 会被
    开头的"优化"抢走（正则从左扫描），导致同一指标的两个数字被分到
    "优化"和"提升"两个桶里，矛盾永远检测不出来。
    """
    best, best_pos = "", -1
    for v in _OUTCOME_VERBS:
        pos = prefix.rfind(v)
        if pos > best_pos:
            best_pos, best = pos, v
    return best


def _rule_data_conflict(q: str, a: str):
    """数据前后矛盾：同一成果动词对应两个不同的比例值（如"提升 30%"与"提升 50%"）。"""
    pairs: dict[str, set[str]] = {}
    first_pos: dict[str, int] = {}
    for m in _RATIO_RE.finditer(a):
        verb = _nearest_verb(a[max(0, m.start() - 10):m.start()])
        if not verb:
            continue
        val = "".join(m.group(0).split())
        pairs.setdefault(verb, set()).add(val)
        first_pos.setdefault(verb, m.start())
    for verb, vals in pairs.items():
        if len(vals) >= 2:
            return Adjustment("data_conflict", "同一指标数据前后矛盾", DIM_QUANT, -2.0,
                              _snippet(a, first_pos[verb], first_pos[verb] + len(verb) + 12))
    return None


def _rule_term_stacking(q: str, a: str):
    """名词堆砌（背诵感）：罗列大量短词，但通篇没有因果/推导连接。"""
    if any(w in a for w in _CAUSAL_WORDS):
        return None
    segs = [s.strip() for s in _LIST_SPLIT_RE.split(a) if s and s.strip()]
    short = [s for s in segs if 2 <= len(s) <= 10]
    if len(short) < 5:
        return None
    return Adjustment("term_stacking", "技术名词堆砌、缺少因果展开", DIM_DEPTH, -1.0,
                      _snippet(a, 0, min(len(a), 30)))


def _rule_irrelevant(q: str, a: str):
    """答非所问：回答与问题的 2-gram 重叠极低。"""
    if len(a.strip()) < 40 or not q:
        return None
    if _overlap_ratio(q, a) >= 0.06:
        return None
    return Adjustment("irrelevant_answer", "回答与所问问题偏离", DIM_LOGIC, -1.0,
                      _snippet(a, 0, min(len(a), 30)))


def _rule_blame_shift(q: str, a: str):
    """甩锅：把结果或问题归因给外部，回避个人行动。"""
    word, pos = _first_hit(a, _BLAME_WORDS)
    if not word:
        return None
    return Adjustment("blame_shift", "归因外部、未说明个人行动", DIM_STAR, -1.0,
                      _snippet(a, pos, pos + len(word)))


def _rule_too_passive(q: str, a: str):
    """全程被动：回答过短，既无因果也无步骤，需要面试官不断追问才拼得出信息。"""
    if len(a.strip()) >= 60:
        return None
    if any(w in a for w in _CAUSAL_WORDS) or any(w in a for w in _STEP_WORDS):
        return None
    return Adjustment("too_passive", "回答过短且未展开", DIM_STAR, -1.0,
                      _snippet(a, 0, min(len(a), 30)))


def _rule_quantified(q: str, a: str):
    """量化充分：给出 2 个以上带单位的量化指标。"""
    hits = {m.group(0).strip().lower() for m in _QUANTIFIED_RE.finditer(a)}
    if len(hits) < 2:
        return None
    return Adjustment("quantified", "量化数据充分", DIM_QUANT, 1.0,
                      "、".join(list(hits)[:3]))


def _rule_cross_link(q: str, a: str):
    """跨项目串联：用关联词把多段经历/多个模块串起来讲，体现系统性思维。"""
    word, pos = _first_hit(a, _LINK_WORDS)
    if not word or len(a.strip()) < 100:
        return None
    return Adjustment("cross_project_link", "跨项目/跨模块串联表述", DIM_JOB, 1.0,
                      _snippet(a, pos, pos + len(word)))


def _rule_candid_gap(q: str, a: str):
    """坦诚不足并给出学习方向：承认不知道，同时说明怎么补。"""
    unc, upos = _first_hit(a, _UNCERTAIN_MARKERS)
    if not unc:
        return None
    lw, lpos = _first_hit(a, _LEARNING_WORDS)
    if not lw:
        return None
    return Adjustment("candid_gap", "坦诚不足并给出学习方向", DIM_DEPTH, 1.0,
                      _snippet(a, min(upos, lpos), max(upos, lpos) + 20))


def _rule_failure_reflection(q: str, a: str):
    """失败案例与反思：主动讲失败，并给出后续改进。"""
    fw, fpos = _first_hit(a, _FAILURE_WORDS)
    if not fw:
        return None
    rw, rpos = _first_hit(a, _REFLECT_WORDS)
    if not rw:
        return None
    return Adjustment("failure_reflection", "主动分享失败经历与反思", DIM_DEPTH, 1.0,
                      _snippet(a, min(fpos, rpos), max(fpos, rpos) + 20))


_RULES = (
    # 扣分项（按严重度排序，-2 项在前，便于封顶时优先保留）
    _rule_data_conflict,
    _rule_no_quantification,
    _rule_term_stacking,
    _rule_irrelevant,
    _rule_blame_shift,
    _rule_too_passive,
    # 加分项
    _rule_quantified,
    _rule_cross_link,
    _rule_candid_gap,
    _rule_failure_reflection,
)


def detect_adjustments(question: str, answer: str) -> list[Adjustment]:
    """检测一条回答中的全部加减分信号（确定性规则，无 LLM 调用）。

    返回按严重度排序的修正列表（扣分在前）。任何异常都被吞掉并返回已检出的部分——
    修正项是锦上添花，绝不能因为规则跑挂而阻断诊断主流程。
    """
    q = (question or "").strip()
    a = (answer or "").strip()
    if not a:
        return []

    found: list[Adjustment] = []
    for rule in _RULES:
        try:
            adj = rule(q, a)
        except Exception as e:  # noqa: BLE001
            logger.debug("评分修正规则 %s 执行跳过: %s", getattr(rule, "__name__", "?"), e)
            continue
        if adj:
            found.append(adj)

    # 互斥：数据前后矛盾时，不再给"量化充分"加分——
    # 自相矛盾的数据不算有效量化，同时给一加一减会让人看不懂分数是怎么来的。
    if any(a.key == "data_conflict" for a in found):
        found = [a for a in found if a.key != "quantified"]

    found.sort(key=lambda x: (x.delta, -abs(x.delta)))
    return _enforce_caps(found)


def _enforce_caps(adjustments: list[Adjustment]) -> list[Adjustment]:
    """施加三重封顶：单条回答总扣分 / 总加分 / 单维度绝对值。

    封顶后若某条调整为 0 则丢弃（它已被前面的调整吃满了额度）。
    """
    penalty_used = 0.0
    bonus_used = 0.0
    per_dim: dict[str, float] = {}
    out: list[Adjustment] = []

    for adj in adjustments:
        remaining_abs = MAX_ABS_PER_DIMENSION - abs(per_dim.get(adj.dimension, 0.0))
        if remaining_abs <= 0:
            continue
        if adj.delta < 0:
            allowed = min(abs(adj.delta),
                          MAX_PENALTY_PER_ANSWER - penalty_used,
                          remaining_abs)
            if allowed <= 0:
                continue
            adj.delta = -allowed
            penalty_used += allowed
        else:
            allowed = min(adj.delta,
                          MAX_BONUS_PER_ANSWER - bonus_used,
                          remaining_abs)
            if allowed <= 0:
                continue
            adj.delta = allowed
            bonus_used += allowed
        per_dim[adj.dimension] = per_dim.get(adj.dimension, 0.0) + adj.delta
        out.append(adj)

    return out


def apply_adjustments(dimensions: dict, adjustments: list[Adjustment]) -> dict:
    """把修正项作用到五维分数上，返回新字典（不修改入参）。

    规则：
      - 只作用于已评分（>0）的维度：0 分表示未评分/解析失败，规则无权抬升；
      - 夹紧到 [1, 5]，避免修正项把分数打出量纲。
    """
    out = dict(dimensions or {})
    if not out or not adjustments:
        return out
    for adj in adjustments:
        cur = out.get(adj.dimension)
        if not isinstance(cur, (int, float)) or cur <= 0:
            continue
        out[adj.dimension] = round(
            max(SCORE_FLOOR, min(SCORE_CEIL, float(cur) + adj.delta)), 2
        )
    return out


def adjustments_payload(adjustments: list[Adjustment]) -> list[dict]:
    """修正项的标准输出结构（进诊断结果与报告）。"""
    return [a.to_dict() for a in adjustments or []]


def describe_adjustments(adjustments: list[Adjustment]) -> str:
    """一行中文摘要，供报告/日志阅读。"""
    if not adjustments:
        return "无规则化修正"
    parts = [f"{a.label}{a.delta:+.0f}" for a in adjustments]
    return "；".join(parts)
