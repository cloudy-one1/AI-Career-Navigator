"""
安全防护模块：参考 MockMate 5 层体系，实现 4 层核心防护。
v2.1: 新增状态校验 + 记忆防污染 + 增强注入检测 + 重复检测。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ==========================================
# 第 1 层：输入注入检测（增强版，50+ 模式）
# ==========================================

INJECTION_PATTERNS = [
    # --- 角色逃逸 ---
    r"忽略\s*(之前的|上述|上面|所有|一切)",
    r"忘记\s*(之前的|上述|上面|所有|一切|你)",
    r"你\s*(现在|其实|实际)\s*(是|变成了|成为了)",
    r"你的(任务|角色|职责|身份)\s*(是|变成了|换成了)",
    r"你(不再|不要)\s*(是|扮演|假装|作为|当|装)",
    r"system\s*prompt",
    r"(扮演|假装|模拟)\s*(一个|一位)",
    r"you\s*are\s*(a|an|now|actually)",
    r"ignore\s*(previous|above|all|instructions)",
    r"forget\s*(previous|above|all|instructions)",
    r"do\s*not\s*(act|pretend|roleplay)",
    r"from\s*now\s*on\s*you\s*(are|will)",
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

    # --- 越狱/DAN ---
    r"从\s*现在\s*开始",
    r"你\s*现在\s*(自由|解放)了",
    r"DAN(\s*mode)?",
    r"jailbreak",
    r"不需要\s*(遵守|执行|服从|理会)",
    r"无视\s*(规则|限制|设定|指令|约束)",
    r"突破\s*(限制|设定|规则)",
    r"绕过\s*(安全|限制|规则)",
    r"任何\s*(规则|限制|设定)\s*(都不|不再)",
    r"do\s*anything\s*now",
    r"没有\s*(任何|什么)\s*(规则|限制|约束)",
    r"解除\s*(所有|一切)\s*(限制|约束|规则)",

    # --- 内容注入 ---
    r"以上\s*(回答|内容|诊断|分析)\s*(是|都)\s*(错误|不对|有问题)",
    r"正确\s*(答案|回答|做法)\s*(是|应该|应当)",
    r"我要求你\s*(输出|生成|说|回答|给出)",
    r"你必须\s*(输出|生成|回答)",
    r"一定\s*(要|必须)\s*(输出|说|生成)",
    r"\{\{\{",
    r"\}\}\}",
    r"<\|.*?\|>",        # 特殊 token 标记
    r"\[INST\].*?\[/INST\]",  # Llama 指令格式
    r"<\|im_start\|>",
    r"<\|im_end\|>",

    # --- 编码绕过 ---
    r"\\x[0-9a-fA-F]{2}",   # 十六进制转义
    r"\\u[0-9a-fA-F]{4}",   # Unicode 转义

    # --- 面试专用注入 ---
    r"(跳过|绕过|快进)\s*(这道|这题|这个|所有)\s*(问题|题目|面试)",
    r"(直接|马上)\s*(给我|显示)\s*(答案|评分|结果|报告)",
    r"(结束|终止|退出)\s*(面试|当前)",
    r"修改\s*(评分|结果|诊断|评价)",
    r"提高\s*(我的|这次)\s*(评分|分数)",
]

# 编译所有正则
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in INJECTION_PATTERNS]


def check_input(text: str) -> tuple[bool, list[str]]:
    """
    检查用户输入是否包含注入关键词。
    Returns: (is_safe, matched_patterns)
    """
    if not text:
        return False, ["输入为空"]

    if len(text) > 10000:
        return False, ["输入过长"]

    matched = []
    for i, pattern in enumerate(_INJECTION_RE):
        if pattern.search(text):
            matched.append(INJECTION_PATTERNS[i])

    is_safe = len(matched) == 0
    if not is_safe:
        logger.warning(f"[安全] 注入检测命中 {len(matched)} 条规则，输入前200字: {text[:200]}")

    return is_safe, matched


# ==========================================
# 第 2 层：输出泄露检测
# ==========================================

LEAK_PATTERNS = [
    (r"system\s*prompt", "system prompt 关键词"),
    (r"你是(一(位|个))?.*面试.*诊断师", "Diagnostician 角色泄露"),
    (r"你的唯一职责是诊断", "诊断师职责片段泄露"),
    (r"你是一位(严格\s*的\s*)?面试回答(改写|重写|优化)专家", "Rewriter 角色泄露"),
    (r"diagnostician", "诊断师标识泄露"),
    (r"rewriter", "改写器标识泄露"),
    (r"你(的|是).*面试官", "面试官角色泄露"),
    (r"诊断维度", "诊断维度关键词泄露"),
    (r"STAR\s*(完整|原则|结构|方法)", "STAR 方法关键词泄露"),
    (r"量化程度", "维度关键词泄露"),
    (r"岗位相关性", "维度关键词泄露"),
    (r"逻辑连贯性", "维度关键词泄露"),
    (r"<\|im_start\|>", "特殊token泄露"),
    (r"<\|im_end\|>", "特殊token泄露"),
]

_LEAK_RE = [(re.compile(p, re.IGNORECASE), desc) for p, desc in LEAK_PATTERNS]


def check_output(text: str) -> tuple[bool, list[str]]:
    """
    检查 AI 响应是否包含 prompt 泄漏。
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
        logger.warning(f"[安全] 输出泄露检测命中: {leaked}")

    return is_safe, leaked


# ==========================================
# 第 3 层：状态异常校验
# ==========================================

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


# ==========================================
# 第 4 层：记忆/上下文防污染
# ==========================================

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
    检测候选人是否试图污染/改写会话历史。
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
        logger.warning(f"[安全] 记忆污染检测命中: {matched}")

    return is_safe, matched


# ==========================================
# 综合安全检查
# ==========================================

def full_check(
    text: str,
    history: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """
    执行全部安全校验，任一不通过即拒绝。
    Returns: (pass_all, reject_reason)
    """
    # 1. 注入检测
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
