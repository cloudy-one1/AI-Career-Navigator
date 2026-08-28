"""
v6.2: LLM 面试话术输出净化（借鉴 GrillMind 的 interviewOutput.js 净化规则）。

为什么需要：面试话术有两条消费路径——TTS 朗读 与 前端渲染。
模型偶发输出 Markdown、舞台提示、垫词，会造成三类可见缺陷：

  - Markdown：`**重点**` 被 TTS 念成"星号星号重点星号星号"；
  - 括号动作：`（微笑）`、`*停顿*` 被原样念出，破坏面试官人设；
  - 垫词开头：`好的，那么……` 起手，削弱面试官的专业感与压迫感。

本模块是**工程兜底**：Prompt 侧已有输出约束（OUTPUT_CONSTRAINTS），
但模型并非 100% 遵守，净化在拿到文本后确定性再清一遍。

设计边界：
  - 只净化**面试官话术**（题目 / 追问 / 评语 / 改写回答），不处理候选人回答；
  - 括号处理用动作词表命中，避免误删 `Redis（缓存）` 这类术语解释。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ===== Prompt 侧输出约束（注入面试官 / 诊断 / 改写 的 system prompt）=====

OUTPUT_CONSTRAINTS = """【输出文本硬性约束】
你产出的所有面向候选人的自然语言文本（题目、追问、评语、改写回答）必须遵守：
1. 禁 Markdown：不要用 **加粗**、# 标题、- 列表、`代码块`、> 引用、[链接]() 等任何标记；
2. 禁括号动作：不要写"（微笑）""（停顿）""*清嗓子*"这类舞台提示，也不要写旁白；
3. 禁垫词开头：不要用"好的""嗯""啊""那么""这个""接下来""首先"等垫词起手，
   第一句话必须直接进入实质内容；
4. 纯文本平铺：需要列举时用"第一、第二"或自然过渡，不要用符号列表；
5. 技术术语保留原样（如 P99、Redis、RAG），不要加任何装饰符号。"""

# ===== 舞台提示动作词（命中则整段括号删除）=====
_ACTION_WORDS = (
    "微笑", "笑", "停顿", "暂停", "清嗓", "咳嗽", "沉默", "点头", "摇头",
    "叹气", "皱眉", "环顾", "看表", "喝水", "扶额", "敲桌", "深呼吸",
    "稍等", "思考", "记录", "写字", "起身", "走近", "压低声音", "提高音量",
    "放慢语速", "加快语速", "语气一转", "眼睛一亮", "翻看简历", "放下简历",
    "身体前倾", "靠回椅背", "冷笑", "干咳", "轻笑", "鼓掌", "举手", "打断",
    "插话", "顿了顿", "侧身", "转身", "指了指", "看了一眼",
    "pause", "smile", "laugh", "sigh", "cough", "silence", "clears throat",
)

# ===== 垫词（句首命中则剥离）=====
_LEADING_FILLERS = (
    "好的好的", "好的", "好嘞", "好", "行吧", "行", "嗯嗯", "嗯", "呃", "啊",
    "哦", "噢", "那么", "这个", "那个", "接下来", "首先", "其次", "然后",
    "okay", "ok", "well", "so", "alright", "now", "hmm", "uh", "um",
)

_MD_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.DOTALL)
_MD_ITALIC = re.compile(r"(?<![\w*])(\*|_)(?![\s*_])(.+?)(?<![\s*_])\1(?![\w*_])", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_QUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_MD_CODE_FENCE = re.compile(r"^\s{0,3}```[^\n]*\n?", re.MULTILINE)
_MD_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]*\)")
_MD_HR = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$", re.MULTILINE)
_ACTION_PAREN = re.compile(r"[（(\[【]\s*([^（(\[【）)\]】\n]{1,16})\s*[)）\]】]")
# *停顿* / _停顿_ 形式：必须在去 Markdown 之前处理 ——
# 若先去掉斜体标记，舞台提示的符号没了、内容（"停顿"）却留在正文里，反而更糟。
_ACTION_ASTERISK = re.compile(r"(\*|_)([^*_\n]{1,16})\1")
# 去 Markdown 后可能残留的孤立标记（如 **（微笑）** 删掉提示后剩下的 **）
_ORPHAN_MARK = re.compile(r"(\*{2,}|_{2,}|`{1,3})")
_SPACE_AROUND_CN = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def _is_action(text: str) -> bool:
    """判断括号内容是否为舞台提示（动作词命中）。"""
    s = text.strip()
    if not s:
        return True
    low = s.lower()
    return any(w in low for w in _ACTION_WORDS)


def strip_markdown(text: str) -> str:
    """去除常见 Markdown 标记，保留纯文本语义。"""
    if not text:
        return ""
    s = text
    s = _MD_CODE_FENCE.sub("", s)
    s = _MD_INLINE_CODE.sub(r"\1", s)
    s = _MD_LINK.sub(r"\1", s)
    s = _MD_HEADING.sub("", s)
    s = _MD_QUOTE.sub("", s)
    s = _MD_BULLET.sub("", s)
    s = _MD_HR.sub("", s)
    s = _MD_BOLD.sub(r"\2", s)
    s = _MD_ITALIC.sub(r"\2", s)
    # 配对的标记已处理完，剩下的连续标记多半是舞台提示被删后的残留
    return _ORPHAN_MARK.sub("", s)


def strip_stage_actions(text: str) -> str:
    """删除舞台提示，保留术语括号（如 Redis（缓存））。

    支持两种写法：括号形式（（微笑）/ [停顿]）与强调形式（*停顿* / _停顿_）。
    """
    if not text:
        return ""
    s = _ACTION_ASTERISK.sub(lambda m: "" if _is_action(m.group(2)) else m.group(0), text)
    return _ACTION_PAREN.sub(lambda m: "" if _is_action(m.group(1)) else m.group(0), s)


def strip_leading_fillers(text: str, max_rounds: int = 3) -> str:
    """剥离句首垫词：'好的，那么，我们开始' → '我们开始'。"""
    if not text:
        return ""
    s = text.strip()
    for _ in range(max_rounds):
        hit = False
        for filler in _LEADING_FILLERS:
            if s.lower().startswith(filler.lower()):
                rest = s[len(filler):].lstrip()
                # 垫词后必须跟标点或空格才剥离，避免误伤 "好问题""那么大的系统"
                if rest[:1] in ("", ",", "，", "、", ".", "。", "!", "！", "?", "？", " ", ":", "："):
                    s = rest.lstrip("，,、。.：: ").strip()
                    hit = True
                    break
        if not hit:
            break
    return s


# ===== v6.3: 恢复态答案泄漏检测 =====
# 候选人说"不会"进入恢复流程时，面试官话术只能引导、不能报答案——
# 直接给答案会让候选人失去这次练习机会（面试中没人在你卡住时递答案）。
# 注意边界：系统确实会提供"参考答案"，但那走 Rewriter 独立通道（改写卡片），
# 与面试官话术是两条路径；这里只管后者。
_ANSWER_LEAK_PATTERNS = (
    "参考答案", "正确答案", "标准答案", "完整答案",
    "应该这样回答", "你应该回答", "你可以这样答", "答案是",
    "这段话应该", "正确的说法是", "完整表述如下", "满分回答",
)


def contains_answer_leak(text: str) -> bool:
    """检测文本是否出现"直接给出答案"的模式（恢复态话术的红线）。

    只做模式匹配，不做语义判断：宁可漏判（交给 Prompt 约束），
    也不要把正常引导误判为泄漏——误判会导致把合理的引导话术替换掉。
    """
    if not text or not isinstance(text, str):
        return False
    return any(p in text for p in _ANSWER_LEAK_PATTERNS)


def sanitize_spoken_text(text: str, strip_fillers: bool = True) -> str:
    """
    净化面向候选人的自然语言文本（题目 / 追问 / 评语 / 改写回答）。

    流程：去舞台提示（先于 Markdown，否则斜体标记被剥掉后只剩动作词）
          → 去 Markdown → 去垫词开头 → 收尾空白整理。
    输入非字符串或空串时原样返回，绝不抛异常（净化失败不能阻断面试）。
    """
    if not text or not isinstance(text, str):
        return text if isinstance(text, str) else ""
    s = strip_stage_actions(text)
    s = strip_markdown(s)
    if strip_fillers:
        s = strip_leading_fillers(s)
    s = _SPACE_AROUND_CN.sub(" ", s)
    s = _MULTI_NEWLINE.sub("\n\n", s)
    return s.strip()
