"""
启发式内容检查模块（课程项目级，非安全边界）。

重要说明（诚实定性，2026-08）：
本模块基于关键词 / 正则的「启发式」匹配，用于拦截最幼稚的注入尝试、
重复刷屏与明显的内容污染。它**不是**一道安全边界：
- 假阴性：换说法、错别字、同义词、中英混杂、Base64 / 拼音 / 编码变形均可绕过；
- 假阳性：与正常业务语言重叠的句式仍可能被误伤（已尽量收窄，并把歧义句式
         降级为"软告警"——仅记录日志、不阻断流程）。
- 输出检查（check_output）：检测到 Prompt 片段泄漏仅记录日志、不阻断、不脱敏，
  只有监控价值、无防护价值；请求原样返回前端。请勿将其理解为输出安全边界。
任何认真的攻击者都能绕过此处检查。生产环境应依赖认证 / 授权、服务端可信边界、
模型侧的指令隔离等机制，而非客户端关键词过滤。

v2.1: 新增重复检测 + 质量校验 + 记忆污染检查。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ==========================================================
# 启发式输入检查 —— 硬拦截集合（高置信攻击句式）
# ==========================================================
# 仅保留「系统指令动词 + 角色逃逸 / 提示词盗取 / 越狱 / 特殊 token」等
# 与正常面试回答重叠度低的模式。命中即拒绝。
# 威胁模型说明（诚实收敛，2026-08）：本产品是中文求职者用中文回答面试问题的场景，
# 纯英文句式（如 "you are a"、"ignore previous"、"do anything now"）命中率近零，
# 属"看起来全面"而非基于真实使用场景的风险建模，已于本次移除；
# 保留跨语言有效的 token / 特殊字符 / jailbreak / DAN / system prompt 模式，
# 以及中文语义等价的高置信攻击句式（这些在中文场景下仍可能命中）。
INJECTION_PATTERNS_HARD = [
    # --- 角色逃逸 / 遗忘指令 ---
    r"忽略\s*(之前的|上述|上面|所有|一切)",
    r"忘记\s*(之前的|上述|上面|所有|一切|你)",
    r"你\s*(现在|其实|实际)\s*(是|变成了|成为了)",
    r"你的(任务|角色|职责|身份)\s*(是|变成了|换成了)",
    r"你(不再|不要)\s*(是|扮演|假装|作为|当|装)",
    r"system\s*prompt",
    r"(扮演|假装|模拟)\s*(一个|一位)",
    r"重新定义(你的|自己)",
    r"切换(角色|身份|人格)",

    # --- Prompt 盗取 ---
    r"(告诉|透露|说出|输出|打印|显示)\s*(我|一下)\s*你的\s*(提示词|prompt|指令|规则|设定)",
    r"你的\s*(提示词|prompt|指令|规则|system|系统提示)\s*(是|有|包括)",
    r"what\s*(is|are|was)\s*your\s*(prompt|instructions|system)",
    r"show\s*me\s*your\s*(prompt|instructions|system)",
    r"(重复|复述|再说|讲出)\s*(上述|以上|你的|一下|一遍)",
    r"把\s*(你的|上面|之前)\s*的\s*(话|内容|文字|指令|规则)\s*(再说|重复|输出|打印)",
    r"你收到\s*(什么|哪些|什么)\s*(指令|提示|规则)",
    r"你被\s*(如何|怎么|怎样)\s*(设定|配置|定义)",
    r"原始\s*(提示|prompt|指令|规则)",

    # --- 越狱 / DAN ---
    # 注：必须带 \b 边界且匹配完整短语 "DAN mode"。裸 r"DAN(\s*mode)?" 会以
    # 子串方式误伤正常技术词（如 Pydantic、abundant、redundant），
    # 已在真实面试回答中复现误拦截（2026-08 全链路验证发现）。
    r"\bDAN\s*mode\b",
    r"jailbreak",
    r"不需要\s*(遵守|执行|服从|理会)",
    r"无视\s*(规则|限制|设定|指令|约束)",
    r"突破\s*(限制|设定|规则)",
    r"绕过\s*(安全|限制|规则)",
    r"任何\s*(规则|限制|设定)\s*(都不|不再)",
    r"没有\s*(任何|什么)\s*(规则|限制|约束)",
    r"解除\s*(所有|一切)\s*(限制|约束|规则)",

    # --- 内容注入（面试流程操控）---
    r"以上\s*(回答|内容|诊断|分析)\s*(是|都)\s*(错误|不对|有问题)",
    r"正确\s*(答案|回答|做法)\s*(是|应该|应当)",
    r"\{\{\{",
    r"\}\}\}",
    r"<\|.*?\|>",
    r"\[INST\].*?\[/INST]",
    r"<\|im_start\|>",
    r"<\|im_end\|>",

    # --- 编码绕过 ---
    r"\\x[0-9a-fA-F]{2}",
    r"\\u[0-9a-fA-F]{4}",

    # --- 面试专用注入 ---
    r"(跳过|绕过|快进)\s*(这道|这题|这个|所有)\s*(问题|题目|面试)",
    r"(直接|马上)\s*(给我|显示)\s*(答案|评分|结果|报告)",
    r"(结束|终止|退出)\s*(面试|当前)",
    r"修改\s*(评分|结果|诊断|评价)",
    r"提高\s*(我的|这次)\s*(评分|分数)",
]

# ==========================================================
# 启发式输入检查 —— 软告警集合（歧义句式，仅记录不拦截）
# ==========================================================
# 这些句式与正常业务语言（如管理经历、项目复盘、个人决心）高度重叠，
# 命中时仅打日志告警，不阻断流程，以避免误伤真实回答。
INJECTION_PATTERNS_SOFT = [
    r"从\s*现在\s*开始",                       # 正常表达："从现在开始我负责这个模块"
    r"你必须\s*(输出|生成|回答)",               # 候选人描述对团队的要求，非对 AI 下指令
    r"我要求你\s*(输出|生成|说|回答|给出)",     # 仅当真的对 AI 下指令时才有意义
    r"一定\s*(要|必须)\s*(输出|说|生成)",       # 强烈语气但非攻击
]

_INJECTION_RE_HARD = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in INJECTION_PATTERNS_HARD]
_INJECTION_RE_SOFT = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in INJECTION_PATTERNS_SOFT]


def check_input(text: str) -> tuple[bool, list[str]]:
    """
    启发式检查用户输入是否命中高置信注入模式。
    ⚠️ 非安全边界：可被换说法 / 编码 / 同义绕过。仅拦截最幼稚尝试。
    Returns: (is_safe, matched_hard_patterns)
    """
    if not text:
        return False, ["输入为空"]

    if len(text) > 10000:
        return False, ["输入过长"]

    matched = []
    for i, pattern in enumerate(_INJECTION_RE_HARD):
        if pattern.search(text):
            matched.append(INJECTION_PATTERNS_HARD[i])

    # 软告警：仅记录，不影响 is_safe，避免误伤正常回答
    soft = []
    for i, pattern in enumerate(_INJECTION_RE_SOFT):
        if pattern.search(text):
            soft.append(INJECTION_PATTERNS_SOFT[i])
    if soft:
        logger.warning(f"[内容检查-软告警] 命中 {len(soft)} 条歧义模式(不阻断): {text[:200]}")

    is_safe = len(matched) == 0
    if not is_safe:
        logger.warning(f"[内容检查] 硬命中 {len(matched)} 条模式，输入前200字: {text[:200]}")

    return is_safe, matched


# ==========================================================
# 启发式输出检查 —— Prompt 片段泄露（仅告警，不阻断）
# ==========================================================
# 说明：输出是本地 LLM 产生的诊断文本，泄露 System Prompt 片段不影响安全边界，
# 此处仅做记录，便于排查模型是否越界输出了内部指令。

LEAK_PATTERNS = [
    (r"system\s*prompt", "system prompt 关键词"),
    (r"你是(一(位|个))?.*面试.*诊断师", "Diagnostician 角色泄露"),
    (r"你的唯一职责是诊断", "诊断师职责片段泄露"),
    (r"你是一位(严格\s*的\s*)?面试回答(改写|重写|优化)专家", "Rewriter 角色泄露"),
    (r"diagnostician", "诊断师标识泄露"),
    (r"rewriter", "改写器标识泄露"),
    (r"你(的|是).*面试官", "面试官角色泄露"),
    (r"<\|im_start\|>", "特殊token泄露"),
    (r"<\|im_end\|>", "特殊token泄露"),
]
# 2026-08-27 整改：移除「诊断维度 / STAR 方法 / 量化程度 / 岗位相关性 / 逻辑连贯性」五条
# ——这些是诊断输出的正常业务术语（维度名、方法论名），命中率为 100%，属于必然误报。
# 保留角色/标识类规则用于观测真实 prompt 泄露。

_LEAK_RE = [(re.compile(p, re.IGNORECASE), desc) for p, desc in LEAK_PATTERNS]


def check_output(text: str) -> tuple[bool, list[str]]:
    """
    检查 AI 响应是否包含 prompt 片段泄漏。

    诚实说明（2026-08）：本函数**仅监控、不阻断、不脱敏**——命中后只记录日志，
    调用方（diagnosis_engine.run_diagnosis_streaming）同样只记日志、不拦截、不改写，
    泄漏内容原样返回前端。因此它是可观测性手段，不是输出安全边界；切勿在答辩中
    将其描述为"第 N 层防护"。若需在泄漏时脱敏/阻断，属于产品化阶段事项（当前不做）。
    Returns: (is_safe, leaked_descriptions)
    """
    if not text:
        return True, []

    leaked = []
    for pattern, desc in _LEAK_RE:
        if pattern.search(text):
            leaked.append(desc)

    is_safe = len(leaked) == 0
    if not is_safe:
        logger.warning(f"[内容检查] 输出泄露检测命中(仅记录): {leaked}")

    return is_safe, leaked


# ==========================================================
# 状态异常校验（重复回答 + 基础质量）
# ==========================================================

# 连续相同回答的阈值
MAX_IDENTICAL_ANSWERS = 2
# 回答变化率阈值（相邻回答的相似度超过此值视为重复）
SIMILARITY_THRESHOLD = 0.85


def check_repeated_answer(current: str, history: list[str]) -> tuple[bool, str]:
    """
    检测候选人是否在重复提交相同/高度相似的回答。
    Returns: (is_safe, reason)
    """
    if not history:
        return True, ""

    # 完全相同的回答
    identical_count = sum(1 for a in history if a == current)
    if identical_count >= MAX_IDENTICAL_ANSWERS:
        return False, "连续提交相同回答，疑似自动化行为"

    # 高度相似检查（简易 Jaccard)
    current_words = set(current.split())
    if not current_words:
        return True, ""

    for prev in history[-2:]:  # 只检查最近 2 条
        prev_words = set(prev.split())
        if not prev_words:
            continue
        intersection = len(current_words & prev_words)
        union = len(current_words | prev_words)
        similarity = intersection / union if union > 0 else 0
        if similarity > SIMILARITY_THRESHOLD:
            return False, "回答与之前高度相似，请提供新的内容"

    return True, ""


def check_answer_quality(answer: str) -> tuple[bool, str]:
    """
    基础质量校验：非空、非纯符号、非明显垃圾内容。
    Returns: (is_valid, reason)
    """
    if not answer or not answer.strip():
        return False, "回答为空"

    stripped = answer.strip()

    # 过短（纯应付）
    if len(stripped) < 3:
        return False, "回答过短"

    # 纯符号/数字
    if re.match(r'^[\d\W_]+$', stripped):
        return False, "回答内容无效"

    # 纯乱码（连续重复字符超过 10 个）
    if re.search(r'(.)\1{10,}', stripped):
        return False, "回答包含大量重复字符"

    return True, ""


# ==========================================================
# 记忆 / 上下文防污染（启发式，非安全边界）
# ==========================================================

MEMORY_POLLUTION_PATTERNS = [
    # 试图改写历史记录
    r"(之前|刚才|前面)\s*(的|那个|那次)\s*(回答|答案|诊断|评分)\s*(是|要|需要)\s*(改|修改|更正|纠正)",
    r"把\s*(之前|前面|历史)\s*(的|那个)\s*(回答|答案|诊断)\s*(改|换成|替换)",
    r"(撤销|取消|撤回)\s*(之前|刚才|上一次)\s*(的|那个)\s*(回答|诊断|评分)",
    r"重(新|置)\s*(所有|全部|整个)\s*(面试|回答|记录|历史)",
    r"(清除|清空|删除|抹掉)\s*(面试|历史|记录|之前的)",
    r"就当\s*(我|刚才|之前)\s*(没|没有)\s*(说|回答|写)",
    r"假装\s*(刚才|之前|上面)\s*(的|那个)\s*(回答|问题)\s*(不|没)",
    r"(回到|返回|跳回)\s*(上一题|上一轮|之前|开始)",
    r"reset\s*(session|history|interview)",
    r"undo\s*(last|previous)",
    # 试图修改系统上下文
    r"(修改|更换|替换)\s*(简历|JD|岗位|岗位描述)",
    r"(我的)?\s*(简历|背景|经历)\s*(其实|实际)\s*(是|应为)",
]

_MEMORY_POLLUTION_RE = [re.compile(p, re.IGNORECASE) for p in MEMORY_POLLUTION_PATTERNS]


def check_memory_pollution(text: str) -> tuple[bool, list[str]]:
    """
    检测候选人是否试图污染/改写会话历史（启发式，仅拦截明显意图）。
    Returns: (is_safe, matched_patterns)
    """
    if not text:
        return True, []

    matched = []
    for i, pattern in enumerate(_MEMORY_POLLUTION_RE):
        if pattern.search(text):
            matched.append(MEMORY_POLLUTION_PATTERNS[i])

    is_safe = len(matched) == 0
    if not is_safe:
        logger.warning(f"[内容检查] 记忆污染检测命中: {matched}")

    return is_safe, matched


# ==========================================================
# 综合检查（串联上述启发式检查）
# ==========================================================

def full_check(
    text: str,
    history: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """
    执行全部启发式校验，任一硬规则不通过即拒绝。
    ⚠️ 这是课程项目级的「内容护栏」，不是安全边界；认真绕过者仍可规避。
    Returns: (pass_all, reject_reason)
    """
    # 1. 输入注入检测（硬拦截集合）
    safe, matched = check_input(text)
    if not safe:
        return False, f"输入包含不安全内容: {'; '.join(matched[:3])}"

    # 2. 质量校验
    valid, reason = check_answer_quality(text)
    if not valid:
        return False, reason

    # 3. 重复检测
    if history:
        safe, reason = check_repeated_answer(text, history)
        if not safe:
            return False, reason

    # 4. 记忆污染
    safe, matched = check_memory_pollution(text)
    if not safe:
        return False, f"检测到试图修改历史的操作: {'; '.join(matched[:2])}"

    return True, ""


def sanitize_input(text: str) -> str:
    """轻量级输入清洗：截断过长输入，移除零宽字符。"""
    if not text:
        return text

    # 限制长度
    text = text[:5000]

    # 移除零宽度字符（可能用于绕过检测）
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]', '', text)

    return text
