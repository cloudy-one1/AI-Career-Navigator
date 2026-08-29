"""
面试技能（Skill）：**有状态的多轮交互能力单元**（v6.5，借鉴 interviewerAgent `internal/skill`）。

与既有 `switch_mode` 的区别（为什么要另起一层）：
  - **模式**（simulation/coach/hardcore/...）是整场的语气与流程设定，切换后一直生效，
    且没有"什么时候结束"的概念；
  - **技能**是临时插入的一段有状态流程：有进入条件、步骤状态、完成条件，
    走完自动退回普通面试。这正是本项目此前缺的一层。

借鉴的接口（`internal/skill/skill.go`，7 方法）：
    Name / Description / Priority / CanActivate / BuildSystemPrompt / OnTurnEnd / IsComplete

两点刻意不照抄原版：
1. **触发方式**：原版靠纯关键词 `strings.Contains`（还穷举 `"和…的区别"` / `"和...区别"`
   这类变体），在真实面试里会把"Redis 和 Memcached 我都不太熟"这种普通回答
   误判成技能触发。本项目**默认显式触发**（前端入口 / WS 消息），
   `can_activate` 仅在 `SKILL_AUTO_MATCH=true` 时参与自动匹配。
2. **结束反馈**：原版技能完成只清 `ActiveSkill`，不告诉用户。本项目完成时返回
   `closing_message`，由工程层推送"已回到正式面试"，避免候选人不知道自己还在技能里。

分层：L3（纯逻辑，无 IO、无 LLM 调用；由 session 编排）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SkillContext:
    """技能执行上下文，跨轮共享（会话持有一份，随会话持久化语义一致）。"""

    def __init__(self, session_id: str = "", mode: str = "simulation",
                 weak_tags: list[str] | None = None):
        self.session_id = session_id
        self.mode = mode
        self.weak_tags: list[str] = list(weak_tags or [])
        self.step: int = 1          # 当前步数（1 起）
        self.metadata: dict = {}    # 技能私有状态

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "weak_tags": list(self.weak_tags),
            "step": self.step,
            "metadata": dict(self.metadata),
        }


class SkillBase:
    """技能基类：有状态的多轮交互。子类实现 name/description/priority + 三个回调。"""

    name = "base"
    description = ""
    priority = 0            # 数值越大越优先（自动匹配时的选择顺序）

    # ===== 生命周期 =====

    def can_activate(self, ctx: SkillContext, trigger: str) -> bool:
        """是否应该激活（仅 SKILL_AUTO_MATCH=true 时使用）。"""
        return False

    def build_prompt(self, ctx: SkillContext) -> str:
        """当前步的 system prompt 片段（由会话层以最高优先级注入）。"""
        return ""

    def on_turn_end(self, ctx: SkillContext, candidate_reply: str) -> None:
        """一轮结束后推进状态（默认：步数 +1）。"""
        ctx.step += 1

    def is_complete(self, ctx: SkillContext) -> bool:
        return ctx.step > self.total_steps()

    def total_steps(self) -> int:
        return 1

    # ===== 展示文案（工程层确定性输出，不消耗 LLM） =====

    def opening_message(self, ctx: SkillContext) -> str:
        return f"已进入「{self.description}」，完成后会自动回到正式面试。"

    def closing_message(self, ctx: SkillContext) -> str:
        return "技能环节结束，我们回到正式面试。"


# ─────────────────────────────────────────────────────────────
# 技能 1：快速测验
# ─────────────────────────────────────────────────────────────

class QuickQuizSkill(SkillBase):
    """连出 5 道选择题，即时判对错并解释，最后给总分。

    为什么值得有：整场面试都是开放式问答，缺少"快速定位知识盲区"的手段；
    测验把盲区检测压缩到 5 轮内，且即时反馈本身就是学习动作。
    """

    name = "quick_quiz"
    description = "快速测验：5 道选择题，即时判分与讲解"
    priority = 80
    TOTAL = 5

    def can_activate(self, ctx: SkillContext, trigger: str) -> bool:
        text = (trigger or "").lower()
        return any(k in text for k in ("测验", "测试一下", "quiz", "来几道题", "考考我", "刷题"))

    def total_steps(self) -> int:
        return self.TOTAL

    def build_prompt(self, ctx: SkillContext) -> str:
        weak = ""
        if ctx.weak_tags:
            weak = f"，重点围绕候选人的薄弱点：{'、'.join(ctx.weak_tags[:3])}"
        return f"""【快速测验模式】你正在主持一轮快速测验（第 {ctx.step}/{self.TOTAL} 题）{weak}。
规则：
1. 每次只出一道四选一题目（A/B/C/D），不要一次给完 5 道；
2. 候选人作答后，先说对错，再用 1~2 句讲清为什么（讲原理，不只对答案）；
3. 若对方答错，指出对应的知识盲区，但不要展开成长篇讲解；
4. 出完第 {self.TOTAL} 题并讲评后，用一句话给出总分与最该补的一点。
语气：像面试官临时加测，简洁、直接、不带客套。"""

    def closing_message(self, ctx: SkillContext) -> str:
        return "测验结束，我们回到正式面试。"


# ─────────────────────────────────────────────────────────────
# 技能 2：概念讲解（Socratic）
# ─────────────────────────────────────────────────────────────

class ConceptTeachSkill(SkillBase):
    """Socratic 式概念讲解：先问已知 → 类比讲解 → 小练习验证 → 确认掌握。

    与 coach 模式的分工：coach 是**整场**都先教后问（模式层）；
    本技能是面试中途卡壳时**临时插入** 2~4 轮讲解，讲完立刻回到面试。
    """

    name = "concept_teach"
    description = "概念讲解：苏格拉底式引导，讲完即回到面试"
    priority = 70
    MAX_ROUNDS = 4
    _DONE_MARKERS = ("理解了", "明白了", "懂了", "清楚了", "会了")

    def can_activate(self, ctx: SkillContext, trigger: str) -> bool:
        text = (trigger or "").lower()
        return any(k in text for k in ("解释一下", "不太懂", "教我", "什么是", "帮我理解", "不明白"))

    def total_steps(self) -> int:
        return self.MAX_ROUNDS

    def build_prompt(self, ctx: SkillContext) -> str:
        return f"""【概念讲解模式】候选人对某个概念卡住了，用苏格拉底式引导讲清它（第 {ctx.step}/{self.MAX_ROUNDS} 轮）。
步骤：
1. 先问候选人目前对这个概念理解到哪一步（摸清已有认知，不要一上来就灌输）；
2. 基于他的回答做针对性讲解，优先用生活化类比；
3. 出一个小练习验证是否真的理解；
4. 确认掌握后即结束讲解，交回正式面试。
约束：
- 多用"你觉得呢""如果换个场景呢"这类开放式引导，不要直接给结论；
- 累计不超过 {self.MAX_ROUNDS} 轮，讲完就走，不要恋战；
- 严禁展开成一篇技术文档——这是面试现场，不是课堂。"""

    def on_turn_end(self, ctx: SkillContext, candidate_reply: str) -> None:
        if any(m in (candidate_reply or "") for m in self._DONE_MARKERS):
            ctx.metadata["teach_done"] = True
        ctx.step += 1

    def is_complete(self, ctx: SkillContext) -> bool:
        return bool(ctx.metadata.get("teach_done")) or ctx.step > self.MAX_ROUNDS

    def opening_message(self, ctx: SkillContext) -> str:
        return "好的，这个概念我先带你过一遍，讲完我们继续面试。"


# ─────────────────────────────────────────────────────────────
# 技能 3：技术对比
# ─────────────────────────────────────────────────────────────

class TechCompareSkill(SkillBase):
    """按 5 个维度逐层对比两个技术方案，最后给出选型判断框架。

    价值：真实面试里"X 和 Y 有什么区别"是高频题，候选人普遍只会背差异点；
    逐维度过一遍能暴露"知道结论但说不清取舍"的问题。
    """

    name = "tech_compare"
    description = "技术对比：5 个维度逐层对比两个方案，最后给选型框架"
    priority = 50

    DIMENSIONS = (
        "使用场景与定位",
        "性能特性（吞吐/延迟/资源占用）",
        "一致性与可靠性保证",
        "运维复杂度与生态",
        "实际选型建议（给出 3 条判断标准）",
    )

    def can_activate(self, ctx: SkillContext, trigger: str) -> bool:
        text = (trigger or "").lower()
        return any(k in text for k in ("区别", "对比", "哪个好", " vs ", "两者", "选型"))

    def total_steps(self) -> int:
        return len(self.DIMENSIONS)

    def build_prompt(self, ctx: SkillContext) -> str:
        idx = min(ctx.step, len(self.DIMENSIONS)) - 1
        current = self.DIMENSIONS[max(0, idx)]
        return f"""【技术对比模式】你在带候选人逐维度对比两个技术方案（第 {ctx.step}/{len(self.DIMENSIONS)} 维：{current}）。
本轮动作：
1. 先问候选人对「{current}」这一维怎么看；
2. 等他回答后，补上他漏掉的关键点、纠正错误认知；
3. 用一个具体场景说明这一维在真实选型里怎么影响决策。
全部维度走完后，帮他总结"面试时如何回答对比题"的通用框架（结构 + 取舍视角）。
约束：一次只推进一个维度，不要一次把 5 维全问完。"""

    def on_turn_end(self, ctx: SkillContext, candidate_reply: str) -> None:
        ctx.step += 1

    def is_complete(self, ctx: SkillContext) -> bool:
        return ctx.step > len(self.DIMENSIONS)


# ─────────────────────────────────────────────────────────────
# 注册中心
# ─────────────────────────────────────────────────────────────

class SkillRegistry:
    """技能注册中心：按优先级排序，支持按名取用与（可选）自动匹配。"""

    def __init__(self, skills: list[SkillBase] | None = None):
        self._skills: list[SkillBase] = list(skills or [])
        self._sort()

    def _sort(self) -> None:
        self._skills.sort(key=lambda s: -s.priority)

    def register(self, skill: SkillBase) -> None:
        if any(s.name == skill.name for s in self._skills):
            logger.warning(f"技能重名，忽略重复注册: {skill.name}")
            return
        self._skills.append(skill)
        self._sort()

    def get(self, name: str) -> SkillBase | None:
        return next((s for s in self._skills if s.name == name), None)

    def match(self, ctx: SkillContext, trigger: str) -> SkillBase | None:
        """按优先级返回第一个 can_activate 为真的技能（自动匹配专用）。"""
        for s in self._skills:
            try:
                if s.can_activate(ctx, trigger):
                    return s
            except Exception as e:  # noqa: BLE001
                logger.warning(f"技能 {s.name} 激活判定异常: {e}")
        return None

    def list(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "priority": s.priority,
                "total_steps": s.total_steps(),
            }
            for s in self._skills
        ]


def default_registry() -> SkillRegistry:
    return SkillRegistry([QuickQuizSkill(), ConceptTeachSkill(), TechCompareSkill()])
