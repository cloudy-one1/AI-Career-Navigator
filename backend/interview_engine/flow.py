"""
面试流程状态与推进决策（L3，纯逻辑，无 IO）。

为什么要单独拆出这个文件：

推进逻辑原本散落在 InterviewSession 的若干方法里（should_follow_up /
has_more_questions_in_round / check_round_quality / should_add_extra_question /
is_closing_round / advance_round）。它们各自都能工作，但组合起来有三个问题：

1. **"接下来该做什么"没有唯一出处** —— 追问、补题、推进、收尾的判定分散在
   六处，改任何一条规则都要先确认另外五处是否也依赖它。
2. **不可单测** —— 都是实例方法，测一条分支要先构造完整会话对象
   （轮次配置、诊断历史、LLM 桩）。
3. **不可观测** —— "面试当前在第几步"只存在于内存对象里，进程一重启就没了。

这里的做法是：把决策**输入**收敛成不可变的纯数据快照 FlowSnapshot，
把决策**输出**收敛成枚举 NextAction，中间所有规则写成一个无副作用的纯函数
decide_next()。副作用（改状态、写库、发消息）仍然留在 InterviewSession 里。

注意：本文件不替代既有方法。decide_next() 先用于"预演与可观测"，
再由调用方逐步改为以它为准 —— 两者行为一致由 tests/test_flow.py 守护。

需求文档：docs/week8_面试流程状态显式化_需求.md
设计参照：docs/Gua-AI-interview-深度研读.md §2.2（节点只做动作，路由由条件边决定）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FlowState(str, Enum):
    """面试流程的显式位置。

    与 Gua 项目的 LangGraph 节点命名对齐（plan/ask/answer/...）便于对照理解，
    但我们不引入图框架 —— 这里只是把"程序计数器"显式化并持久化。
    """

    INIT = "init"                          # 会话刚创建，题目尚未生成
    ASKING = "asking"                      # 正在生成当前问题
    WAITING_ANSWER = "waiting_answer"      # 已出题，等待候选人回答
    DIAGNOSING = "diagnosing"              # 正在诊断该回答
    DECIDING_NEXT = "deciding_next"        # 诊断完成，判定下一步
    GENERATING_FOLLOW_UP = "generating_follow_up"   # 生成追问中
    ADVANCING_ROUND = "advancing_round"    # 正在推进轮次
    CLOSING = "closing"                    # 收尾阶段（强控：不再追问/补题）
    FINISHED = "finished"                  # 已结束


class NextAction(str, Enum):
    """decide_next 的输出：下一步该做什么（不含"怎么做"，那是调用方的事）。"""

    AWAIT_ANSWER = "await_answer"          # 出当前题，等待回答
    GENERATE_FOLLOW_UP = "follow_up"       # 生成追问
    GENERATE_EXTRA = "extra_question"      # 本轮未达标，追加补强题
    ADVANCE_ROUND = "advance_round"        # 推进到下一轮
    FINISH = "finish"                      # 结束面试
    OFFER_RECOVERY = "offer_recovery"      # 连续不会答 → 给"换方向"建议


@dataclass(frozen=True)
class FlowSnapshot:
    """推进决策所需的全部输入（纯数据，不含任何对象引用）。

    刻意只放"判定需要的东西"：把整个 session 传进来也能算，但那样这个函数
    就永远无法单测了 —— 构造快照的成本远低于构造会话。
    """

    flow_state: FlowState = FlowState.INIT

    # 轮次维度
    current_round: int = 0                 # 当前轮下标
    total_rounds: int = 0                  # 轮次总数
    is_closing_round: bool = False         # 收尾轮（工程强控：不再追问/补题）

    # 本轮题目维度
    question_idx: int = 0                  # 当前题在本轮中的下标
    questions_in_round: int = 0            # 本轮题目总数（含已追加）
    answered_in_round: int = 0             # 本轮已答题数

    # 追加题维度
    extra_added: int = 0
    max_extra: int = 0
    round_passed: bool = False             # 本轮均分是否达到推进阈值
    below_min_questions: bool = False      # 本轮答题数是否还没到下限

    # 追问维度
    follow_up_count: int = 0
    follow_up_max: int = 3

    # 本轮回答质量（非纯规则的部分由调用方先算好再传进来）
    has_follow_up_question: bool = False   # 诊断已产出追问文本
    next_action: Optional[str] = None      # 诊断 next_action：follow_up/next_question/complete
    answer_too_short: bool = False         # 回答长度低于追问下限
    round_avg_below_threshold: bool = False  # 低分（兜底强制追问用）

    # 不会答恢复（v6.3）
    recovery_streak: int = 0
    recovery_skip_threshold: int = 3
    recovery_advice_done: bool = False

    @property
    def has_more_questions(self) -> bool:
        return self.question_idx < self.questions_in_round

    @property
    def follow_up_exhausted(self) -> bool:
        return self.follow_up_count >= self.follow_up_max

    @property
    def is_last_round(self) -> bool:
        return self.total_rounds > 0 and self.current_round >= self.total_rounds - 1


@dataclass(frozen=True)
class FlowDecision:
    """决策结果：动作 + 目标状态 + 理由。

    reason 是为了可观测性 —— 日志/前端可以直接展示"为什么走到这一步"，
    不必回到六个方法里逐个反推。
    """

    action: NextAction
    next_state: FlowState
    reason: str


def decide_next(s: FlowSnapshot) -> FlowDecision:
    """给定快照，决定下一步动作。**纯函数：无 IO、无随机、无全局状态。**

    判定顺序即优先级；调整顺序等于调整业务规则，请谨慎。
    """
    # ① 保护性干预优先：连续"不会答"达阈值时给换方向建议。
    #    刻意排在追问上限之前 —— 否则它恰好会被"第 N 次追问"拦掉，
    #    保护机制在最需要它的时刻失效（v6.3 的修复点）。
    if s.recovery_streak >= s.recovery_skip_threshold and not s.recovery_advice_done:
        return FlowDecision(
            NextAction.OFFER_RECOVERY, FlowState.GENERATING_FOLLOW_UP,
            f"连续 {s.recovery_streak} 次表示不会答，主动建议换方向",
        )

    # ② 收尾轮强控：不再追问、不再补题，答完即收束。
    if s.is_closing_round:
        if s.has_more_questions:
            return FlowDecision(NextAction.AWAIT_ANSWER, FlowState.WAITING_ANSWER,
                                "收尾阶段：出下一题（不再追问）")
        return FlowDecision(NextAction.FINISH, FlowState.FINISHED,
                            "收尾阶段题目已出完，结束面试")

    # ③ 本轮还有未提问的题目 → 直接出，不进入轮次结算。
    if s.has_more_questions:
        return FlowDecision(NextAction.AWAIT_ANSWER, FlowState.WAITING_ANSWER,
                            f"本轮还有 {s.questions_in_round - s.question_idx} 题未问")

    # ④ 本轮题目已问完：先看还能不能/需不需要追问。
    if not s.follow_up_exhausted:
        if s.has_follow_up_question:
            return FlowDecision(NextAction.GENERATE_FOLLOW_UP,
                                FlowState.GENERATING_FOLLOW_UP,
                                "诊断给出了追问文本")
        if s.answer_too_short:
            return FlowDecision(NextAction.GENERATE_FOLLOW_UP,
                                FlowState.GENERATING_FOLLOW_UP,
                                "回答过短，强制追问以防敷衍被放行")
        if s.round_avg_below_threshold and s.next_action not in ("next_question", "complete"):
            return FlowDecision(NextAction.GENERATE_FOLLOW_UP,
                                FlowState.GENERATING_FOLLOW_UP,
                                "本轮均分偏低，按阈值规则追问")

    # ⑤ 不再追问：结算本轮 —— 未达标且还能追加 → 补强题；否则推进下一轮。
    if not s.round_passed and s.extra_added < s.max_extra:
        return FlowDecision(NextAction.GENERATE_EXTRA, FlowState.ASKING,
                            "本轮未达推进阈值，追加补强题")
    if s.below_min_questions:
        return FlowDecision(NextAction.GENERATE_EXTRA, FlowState.ASKING,
                            "本轮答题数未达下限，继续出题")

    if s.is_last_round:
        return FlowDecision(NextAction.FINISH, FlowState.FINISHED,
                            "已是最后一轮且无待办，结束面试")

    # 兜底：轮次配置为空（total_rounds<=0）时不应无限循环 —— 与 Gua 项目
    # "totalRounds<=0 按配置错误终止"同一思路，只是这里没有配置可查，
    # 因此退化为"结束"，由调用方记录告警。
    if s.total_rounds <= 0:
        return FlowDecision(NextAction.FINISH, FlowState.FINISHED,
                            "轮次配置为 0，按异常终止（题目未配置）")

    return FlowDecision(NextAction.ADVANCE_ROUND, FlowState.ADVANCING_ROUND,
                        "本轮结算完成，推进到下一轮")


def with_overrides(s: FlowSnapshot, **overrides) -> FlowSnapshot:
    """返回改了若干字段的新快照（原快照不可变）。

    存在的理由：调用方要"预演"（例如把诊断结果临时塞进去看会怎么走），
    但 FlowSnapshot 是 frozen 的，逐字段构造既啰嗦又容易漏。
    """
    from dataclasses import replace

    return replace(s, **overrides)
