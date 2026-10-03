"""
test_flow.py —— v7.0 面试流程状态显式化；v8.21 起为推进决策唯一出处的守护层。

decide_next() 已收敛"接下来该做什么"的全部规则（v8.21 把 should_follow_up
老方法的规则逐条并入，取舍记录在 v8.21 提交描述的规则 diff 清单），
生产主循环按它分派副作用。

测试分两层：
1. 纯函数层：decide_next 的每条分支与优先级（不需要构造会话）
2. 接线层：session.decide() 从真实会话状态取数（诊断文本 / 低分 / 过短），
   保证快照装配没漏字段——每条老路径既有行为在纯函数侧有对应用例
"""

from unittest.mock import AsyncMock, MagicMock

from backend.config import config
from backend.dimension_weights import DIM_KEYS
from backend.interview_engine.flow import (
    FlowDecision,
    FlowSnapshot,
    FlowState,
    NextAction,
    decide_next,
    with_overrides,
)
from backend.interview_engine.session import InterviewSession


# ===== 1. 纯函数分支 =====

def snap(**kw) -> FlowSnapshot:
    """构造一个"默认处于本轮题目已问完、等待结算"的快照。"""
    base = FlowSnapshot(
        flow_state=FlowState.DECIDING_NEXT,
        current_round=0,
        total_rounds=3,
        is_closing_round=False,
        question_idx=2,
        questions_in_round=2,      # 已问完（idx == count）
        answered_in_round=2,
        extra_added=0,
        max_extra=2,
        round_passed=True,
        below_min_questions=False,
        follow_up_count=0,
        follow_up_max=3,
    )
    return with_overrides(base, **kw)


class TestDecideNextBranches:
    def test_more_questions_await_answer(self):
        """本轮还有题 → 直接出，不进结算。"""
        d = decide_next(snap(question_idx=0, questions_in_round=3))
        assert d.action == NextAction.AWAIT_ANSWER
        assert d.next_state == FlowState.WAITING_ANSWER

    def test_recovery_takes_priority_over_follow_up_limit(self):
        """连续不会答的保护性干预必须能突破追问上限。

        这是 v6.3 的修复点：若排在 follow_up_exhausted 之后，
        保护机制恰好会在最需要它的第三次追问时被拦掉。
        """
        d = decide_next(snap(follow_up_count=3, recovery_streak=3))
        assert d.action == NextAction.OFFER_RECOVERY

    def test_recovery_not_repeated_once_advised(self):
        d = decide_next(snap(follow_up_count=3, recovery_streak=3,
                             recovery_advice_done=True))
        assert d.action != NextAction.OFFER_RECOVERY

    def test_closing_round_finishes_without_follow_up(self):
        """收尾轮强控：不再追问、不再补题。"""
        d = decide_next(snap(is_closing_round=True, has_follow_up_question=True))
        assert d.action == NextAction.FINISH
        assert d.next_state == FlowState.FINISHED

    def test_closing_round_still_asks_remaining_questions(self):
        d = decide_next(snap(is_closing_round=True, question_idx=0,
                             questions_in_round=2))
        assert d.action == NextAction.AWAIT_ANSWER

    def test_follow_up_when_diagnosis_provides_question(self):
        assert decide_next(snap(has_follow_up_question=True)).action == NextAction.GENERATE_FOLLOW_UP

    def test_follow_up_when_answer_too_short(self):
        assert decide_next(snap(answer_too_short=True)).action == NextAction.GENERATE_FOLLOW_UP

    def test_follow_up_even_when_questions_remain(self):
        """v8.21 收敛钉子（D1）：每题答完都可能追问，与"是否还有未问题目"无关。

        老路径时序是 答 → 诊 → 可能追问 → 下一题；纯函数原版把追问判定放在
        "本轮题目已问完"之后，会漏掉中间题的追问——切换时以老路径为准。
        """
        d = decide_next(snap(question_idx=0, questions_in_round=3,
                             has_follow_up_question=True))
        assert d.action == NextAction.GENERATE_FOLLOW_UP

    def test_mid_round_moves_on_without_follow_up_signal(self):
        """中间题答完、无追问信号 → 出下一题（而不是稀里糊涂进入结算）。"""
        d = decide_next(snap(question_idx=0, questions_in_round=3))
        assert d.action == NextAction.AWAIT_ANSWER
        assert d.next_state == FlowState.WAITING_ANSWER

    def test_follow_up_when_answer_score_low(self):
        """v8.21 收敛钉子（D8）：低分追问以单题分为口径（老路径），不是轮均分。"""
        assert decide_next(snap(answer_score_below_threshold=True)).action == \
            NextAction.GENERATE_FOLLOW_UP

    def test_model_next_question_suppresses_low_score_follow_up(self):
        """模型明确说"下一题"时，低分不再强行追问（v6.0 尊重模型决策）。"""
        d = decide_next(snap(answer_score_below_threshold=True, next_action="next_question"))
        assert d.action != NextAction.GENERATE_FOLLOW_UP

    def test_short_answer_still_forced_even_if_model_says_next(self):
        """但回答过短必须强制追问 —— 防止"敷衍答案"被模型放行。"""
        d = decide_next(snap(answer_too_short=True, next_action="next_question"))
        assert d.action == NextAction.GENERATE_FOLLOW_UP

    def test_follow_up_limit_respected(self):
        d = decide_next(snap(follow_up_count=3, has_follow_up_question=True))
        assert d.action != NextAction.GENERATE_FOLLOW_UP

    def test_extra_question_when_round_not_passed(self):
        d = decide_next(snap(round_passed=False, extra_added=0, max_extra=2))
        assert d.action == NextAction.GENERATE_EXTRA

    def test_no_extra_when_quota_used_up(self):
        d = decide_next(snap(round_passed=False, extra_added=2, max_extra=2))
        assert d.action != NextAction.GENERATE_EXTRA

    def test_min_questions_enforced(self):
        d = decide_next(snap(round_passed=True, below_min_questions=True))
        assert d.action == NextAction.GENERATE_EXTRA

    def test_advance_round_in_middle(self):
        d = decide_next(snap(current_round=0, total_rounds=3))
        assert d.action == NextAction.ADVANCE_ROUND
        assert d.next_state == FlowState.ADVANCING_ROUND

    def test_finish_on_last_round(self):
        assert decide_next(snap(current_round=2, total_rounds=3)).action == NextAction.FINISH

    def test_zero_rounds_terminates_instead_of_looping(self):
        """轮次配置为空时必须终止，不能返回"推进"（否则调用方空转）。

        与 Gua 项目 "totalRounds<=0 按配置错误终止" 同一思路。
        """
        d = decide_next(snap(total_rounds=0))
        assert d.action == NextAction.FINISH
        assert "配置" in d.reason

    def test_decision_carries_reason(self):
        """每条决策都带理由 —— 这是可观测性的基础。"""
        for d in (
            decide_next(snap(has_follow_up_question=True)),
            decide_next(snap(current_round=2)),
            decide_next(snap(round_passed=False, max_extra=1)),
        ):
            assert isinstance(d, FlowDecision)
            assert d.reason


class TestSnapshotImmutability:
    def test_with_overrides_does_not_mutate(self):
        s = snap()
        s2 = with_overrides(s, follow_up_count=9)
        assert s.follow_up_count == 0
        assert s2.follow_up_count == 9

    def test_derived_properties(self):
        assert snap(question_idx=1, questions_in_round=3).has_more_questions
        assert not snap(question_idx=3, questions_in_round=3).has_more_questions
        assert snap(follow_up_count=3, follow_up_max=3).follow_up_exhausted
        assert snap(current_round=2, total_rounds=3).is_last_round
        assert not snap(total_rounds=0).is_last_round


# ===== 2. 与既有逻辑的一致性 =====

def _make_session():
    llm = MagicMock()
    llm.chat = MagicMock(return_value="生成追问")
    diag = MagicMock()
    diag.diagnose = AsyncMock(return_value={
        "overall_score": 4,
        "dimensions": {k: 4 for k in DIM_KEYS},
        "dimension_details": {k: {"comment": "c"} for k in DIM_KEYS},
        "follow_up_question": "",
    })
    return InterviewSession(
        session_id="s1",
        resume_text="3 年 Python 开发经验",
        jd_text="招聘 Python 后端工程师",
        llm_client=llm,
        diagnosis_engine=diag,
        db=MagicMock(),
    )


def _answered_round(s: InterviewSession) -> None:
    """把会话摆到"本轮题目已问完、回答足够长"的结算点。

    回答长度必须超过 config.FOLLOW_UP_MIN_LENGTH（30 字），否则会命中
    "回答过短 → 强制追问"这条规则，测不到本来想测的分支。
    """
    s.round_questions = [{"question": "q1"}, {"question": "q2"}]
    s.current_question_idx = 2
    long_answer = ("我负责订单系统的重构，把核心接口从单体拆分为三个服务，"
                   "并用 Redis 缓存把查询耗时从 800 毫秒降到 200 毫秒左右")
    s.round_answers = [long_answer, long_answer]
    s.last_answer_text = long_answer


class TestSessionIntegration:
    def test_snapshot_defaults(self):
        s = _make_session()
        assert s.flow_state == FlowState.INIT
        now = s.snapshot()
        assert now.total_rounds == len(s.rounds)
        assert now.follow_up_count == 0
        assert now.flow_state == FlowState.INIT

    def test_set_flow_state_and_payload(self):
        s = _make_session()
        s.set_flow_state(FlowState.WAITING_ANSWER, answered=3)
        assert s.flow_state == FlowState.WAITING_ANSWER
        assert s.answered_count == 3
        payload = s.flow_payload()
        assert payload["flow_state"] == "waiting_answer"
        assert payload["answered_count"] == 3

    def test_snapshot_reflects_round_completion(self):
        s = _make_session()
        _answered_round(s)
        now = s.snapshot()
        assert now.has_more_questions is False
        assert now.answered_in_round == 2

    def test_decide_agrees_when_diagnosis_has_follow_up(self):
        """诊断给了追问文本 → 决策为追问。

        v8.21 起不再用 overrides 喂结论，而是把诊断真的放进会话状态——
        这测的是 snapshot() 的接线（diag → has_follow_up_question），
        快照漏装配字段时这里先炸。
        """
        s = _make_session()
        _answered_round(s)
        s.round_diagnoses = [{
            "overall_score": 4.0,
            "dimensions": {k: 4 for k in DIM_KEYS},
            "follow_up_question": "能具体说说性能提升了多少吗？",
        }]
        assert s.decide().action == NextAction.GENERATE_FOLLOW_UP

    def test_decide_moves_on_when_no_follow_up_signal(self):
        """没有追问信号、轮次也达标 → 推进下一轮。"""
        s = _make_session()
        _answered_round(s)
        s.round_diagnoses = [{
            "overall_score": 4.5,
            "dimensions": {k: 4 for k in DIM_KEYS},
            "follow_up_question": "",
            "next_action": "next_question",
        }]
        d = s.decide()
        assert d.action == NextAction.ADVANCE_ROUND

    def test_decide_closing_round_never_follows_up(self):
        """收尾轮：即使诊断给了追问文本也必须 FINISH 而不是追问。"""
        s = _make_session()
        _answered_round(s)
        s.current_round = len(s.rounds) - 1          # 最后一轮 = 收尾轮
        s.round_diagnoses = [{
            "overall_score": 2.0,
            "dimensions": {k: 2 for k in DIM_KEYS},
            "follow_up_question": "再展开讲讲？",
        }]
        assert s.is_closing_round() is True
        assert s.decide().action == NextAction.FINISH

    def test_decide_returns_extra_question_when_round_weak(self):
        """本轮未达标且还能补题 → 补强题（而不是稀里糊涂地推进）。

        follow_up_count 拉到上限，确保走到"轮次结算"而不是被追问分支拦下。
        """
        s = _make_session()
        _answered_round(s)
        s.current_round = 2        # 技术深度轮：max_extra_questions=2
        s.round_diagnoses = []     # 无诊断 → 均分 0，未达标
        s.follow_up_count = config.FOLLOW_UP_MAX_COUNT
        # 本轮必须允许补题：默认首轮（破冰环节）max_extra_questions=0，
        # 那里本来就该直接推进，测不出补题分支。
        round_cfg = s.current_round_info()
        assert int(round_cfg.get("max_extra_questions", 0) or 0) > 0
        d = s.decide()
        assert d.action == NextAction.GENERATE_EXTRA

    def test_overrides_allow_what_if(self):
        """overrides 支持"预演"：临时改输入而不动会话状态。"""
        s = _make_session()
        _answered_round(s)
        # 先摆到一个"不会追问"的基准态
        assert s.decide(round_passed=True, answer_score_below_threshold=False,
                        has_follow_up_question=False).action != NextAction.GENERATE_FOLLOW_UP
        # 假如这次回答很短 —— 预演应生效，且不该真的改动会话状态
        assert s.decide(answer_too_short=True).action == NextAction.GENERATE_FOLLOW_UP
        assert len(s.last_answer_text) >= config.FOLLOW_UP_MIN_LENGTH
