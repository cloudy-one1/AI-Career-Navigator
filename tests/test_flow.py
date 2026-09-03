"""
test_flow.py —— v7.0 面试流程状态显式化

核心诉求：把"接下来该做什么"从六个分散的实例方法里收敛成一个纯函数 decide_next()，
让分支判定第一次能被单测覆盖（对应 README「已知局限」的"测试偏纯函数、覆盖不到流程决策"）。

测试分两层：
1. 纯函数层：decide_next 的每条分支与优先级（不需要构造会话）
2. 一致性层：session.decide() 与既有 should_follow_up 的结论必须一致 ——
   保证"新增的纯函数"与"正在生效的旧逻辑"没有分歧
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

    def test_follow_up_when_round_avg_low(self):
        assert decide_next(snap(round_avg_below_threshold=True)).action == NextAction.GENERATE_FOLLOW_UP

    def test_model_next_question_suppresses_low_score_follow_up(self):
        """模型明确说"下一题"时，低分不再强行追问（v6.0 尊重模型决策）。"""
        d = decide_next(snap(round_avg_below_threshold=True, next_action="next_question"))
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
        """诊断给了追问文本 → 两边都应判定为追问。"""
        s = _make_session()
        _answered_round(s)
        diag = {"follow_up_question": "能具体说说性能提升了多少吗？"}
        assert s.should_follow_up(s.last_answer_text, diag) is True
        # 用同一份诊断喂给快照，否则两边看到的数据不同（一致性断言失去意义）
        assert s.decide(has_follow_up_question=True).action == NextAction.GENERATE_FOLLOW_UP

    def test_decide_agrees_when_no_follow_up_signal(self):
        """没有追问信号、轮次也达标 → 两边都应判定为不追问。"""
        s = _make_session()
        _answered_round(s)
        # 先让本轮"达标"，否则会走补题分支而到不了"推进/结束"
        s.round_diagnoses = [{
            "overall_score": 4.5,
            "dimensions": {k: 4 for k in DIM_KEYS},
            "follow_up_question": "",
            "next_action": "next_question",
        }]
        diag = {"follow_up_question": "", "next_action": "next_question"}
        assert s.should_follow_up(s.last_answer_text, diag) is False
        # 与 should_follow_up 用同一份诊断做快照输入，避免"两边看到的数据不同"
        assert s.decide(next_action=diag.get("next_action"),
                        has_follow_up_question=False).action == NextAction.ADVANCE_ROUND

    def test_decide_closing_round_never_follows_up(self):
        """收尾轮：既有方法返回 False，纯函数也必须 FINISH 而不是追问。"""
        s = _make_session()
        _answered_round(s)
        s.current_round = len(s.rounds) - 1          # 最后一轮 = 收尾轮
        assert s.is_closing_round() is True
        assert s.should_follow_up(s.last_answer_text, None) is False
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
        assert s.decide(round_passed=True, round_avg_below_threshold=False,
                        has_follow_up_question=False).action != NextAction.GENERATE_FOLLOW_UP
        # 假如这次回答很短 —— 预演应生效，且不该真的改动会话状态
        assert s.decide(answer_too_short=True).action == NextAction.GENERATE_FOLLOW_UP
        assert len(s.last_answer_text) >= config.FOLLOW_UP_MIN_LENGTH
