"""
WebSocket 面试主循环集成测试（v7.3.1）—— 钉住 interview_ws.py 的 4 条主路径。

背景：v7.2.2 把 WS 主循环从 main.py 拆到 routers/interview_ws.py 后，它是唯一
没有测试直接钉住的核心路径（拆分后覆盖率仅 ~8%）。本文件走「真实 FastAPI WS
管线 + 最小 FakeSession」钉协议行为，不调 LLM：

1. ping → pong（答题等待循环内响应心跳，不推进面试状态）
2. switch_mode → mode_change（合法模式生效；非法模式回错误但连接不断）
3. 结束口令 → interview_end_signal → 照常生成完整报告（status=completed，口令不计分）
4. 断连 → 已答部分落部分报告（status=interrupted）→ finally 清理 active_sessions

FakeSession 只实现 interview_ws.py 实际触碰的会话接口——它本身就是 WS 层对
会话层那份隐性依赖契约的显式清单；真实 InterviewSession 的接口签名漂移时
这里会先炸，正好倒逼同步。

握手契约（4001 未授权 / 4000 会话不存在）一并钉住，见 TestHandshake。
"""
import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.config import config
from backend.db import get_report, get_session, save_session
from backend.routers import state

SESSION_ID = "ws-itest-session"

# 单帧等待上限：正常路径毫秒级返回，超时即视为服务端中断（见 _recv_with_timeout）
_RECV_TIMEOUT = 10.0

ANSWER_1 = "我最有把握的是基于 Django 的电商订单系统，我负责订单状态机与支付对账，峰值 QPS 三千。"
ANSWER_EXTRA = "补一道的话，我会讲对账的幂等设计：以订单号加状态版本号做唯一约束。"
END_SIGNAL = "结束面试，谢谢"


# ===== FakeSession：WS 层依赖契约的最小实现 =====

class FakeSession:
    """单轮、两题（第二题由质量补题注入）的最小会话桩。

    接口名与真实 InterviewSession 一一对应：WS 层多碰一个不存在的属性，
    测试立即 AttributeError——这份"会炸"就是契约测试的价值。
    """

    def __init__(self, trigger_extra_question: bool = False):
        self.trigger_extra = trigger_extra_question  # 仅断连测试开启：首答不达标触发补题
        self.style = "friendly"
        self.mode = "simulation"
        self.stage = "phone_screen"
        self.rounds = [{"round_index": 1, "name": "技术面"}]
        self.round_questions = [{
            "question": "介绍一下你最有把握的项目",
            "intent": "考察项目真实性与表达结构",
            "is_extra": False,
            "focus_dimension": "skills",
            "focus_dimension_name": "技术能力",
            "question_type": "open",
            "is_pressure": False,
            "topic": "",
        }]
        self.current_question_idx = 0
        # round_start 帧要读 session.current_round（真实 InterviewSession 为 int 轮次下标）
        self.current_round = 0
        self.is_finished = False
        self.answered_count = 0
        self.answer_history: list[dict] = []
        self.all_diagnoses: list[dict] = []
        self.pending_difficulty = None
        self.pending_follow_up = ""
        self.extra_questions_added = 0
        self.flow_states: list[str] = []
        self.memory_points: list = []
        self.switched: list[tuple] = []
        self.server_thinking_calls: list[float] = []   # v8.6: 服务端墙钟差
        self._quality_calls = 0

    # —— 启动阶段 ——
    def set_long_term_memory(self, points):
        self.memory_points = list(points)

    async def init_weights(self):
        return {"weights": {}, "source": "default"}

    def get_interviewer_change_event(self):
        return None

    def current_round_info(self):
        return {"name": self.rounds[0]["name"]}

    async def generate_questions(self):
        pass  # 题目已预置

    def has_more_questions_in_round(self):
        return self.current_question_idx < len(self.round_questions)

    @property
    def current_question(self):
        return self.round_questions[self.current_question_idx]

    def set_flow_state(self, state_):
        self.flow_states.append(state_.value if hasattr(state_, "value") else str(state_))

    # —— 答题等待循环 ——
    def switch_mode(self, mode, stage=None):
        if mode:
            self.mode = mode
        if stage:
            self.stage = stage
        self.switched.append((mode, stage))
        return {"mode": self.mode, "stage": self.stage, "message": "已切换"}

    def is_skill_active(self):
        return False

    async def stream_answer(self, answer_text, from_voice=False, thinking_seconds=0):
        # 契约：diagnosis_done 之前的块由 WS 层原样透传，diagnosis_done 自身被截留
        yield {"type": "stream_token", "data": {"text": "正在诊断…"}}
        diag = {
            "question": self.current_question["question"],
            "overall_score": 3.5,
            "weakest_dimension": "skills",
            "weakest_dimension_name": "技术能力",
            "real_interview_impact": "结构清晰，建议补充量化结果",
        }
        self.all_diagnoses.append(diag)
        self.answer_history.append({"question": diag["question"], "answer": answer_text})
        self.answered_count += 1
        yield {"type": "diagnosis_done", "data": diag}

    def should_follow_up(self, answer_text, diag):
        return False

    def annotate_server_thinking(self, server_seconds):
        """v8.6: 服务端墙钟差校验。

        契约成员：WS 层每收一次回答就会调用它。桩里缺这个方法，
        WS 侧立即 AttributeError —— 这正是本桩存在的意义（见类注释）。
        """
        self.server_thinking_calls.append(server_seconds)

    # —— 每题诊断后推送的实时面板数据来源 ——
    def question_basis(self, q) -> str:
        """v6.4 出题依据：真实实现为确定性拼装；桩返回空串（前端不渲染 chip）。"""
        return ""

    def radar_snapshot(self) -> dict:
        return {"average": {}, "latest": {}}

    def weakness_payload(self) -> dict:
        return {"tags": [], "counts": {}, "recovery_active": False}

    # —— 质量驱动推进：默认首答即达标收轮；仅断连测试开启补题分支 ——
    def check_round_quality(self):
        self._quality_calls += 1
        if self.trigger_extra and self._quality_calls == 1:
            return {"passed": False, "can_add_extra": True, "reason": "本轮均分未达标"}
        return {"passed": True, "can_add_extra": False, "reason": "达标"}

    async def generate_extra_question(self):
        self.extra_questions_added += 1
        extra = {
            "question": ANSWER_EXTRA[:14] + "？",
            "intent": "定向补强薄弱维度",
            "is_extra": True,
            "focus_dimension": "engineering",
            "focus_dimension_name": "工程质量",
        }
        self.round_questions.append(extra)
        return extra

    # —— 收尾 ——
    def is_closing_round(self):
        return False

    def _current_round_avg_score(self):
        return 3.5

    def advance_round(self):
        self.current_question_idx = len(self.round_questions)
        self.is_finished = True  # 单轮配置：收轮即结束

    def build_report(self):
        return {
            "overall_score": 3.5,
            "dimension_averages": {},
            "scoring": {"weights": {}},
            "qa_breakdown": [],
        }


# ===== fixtures 与工具 =====

@pytest.fixture()
def ws_client(tmp_path, monkeypatch):
    """真实 app + 临时文件 DB + 预置 sessions 行（reports 表有外键）。

    形态与 test_api.py 的 client fixture 一致：sync 测试 + TestClient。
    """
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "ws_test.db"))
    monkeypatch.setattr(config, "MARKET_DB_PATH", str(tmp_path / "ws_market.db"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from backend.db import init_db
        from backend.market.store import init_market_db
        loop.run_until_complete(init_db())
        loop.run_until_complete(init_market_db())
        loop.run_until_complete(save_session(SESSION_ID))
    finally:
        loop.close()

    from backend.main import app
    with TestClient(app) as client:
        yield client
    state.active_sessions.clear()


@pytest.fixture()
def fake_session():
    return FakeSession()


def _recv_with_timeout(ws, timeout=_RECV_TIMEOUT):
    """带超时地读一帧。

    为什么必须加超时：TestClient 的 receive_json() 会无限阻塞。若服务端因
    FakeSession 契约漂移（缺属性/方法）抛异常中断，后续帧永远不来，测试
    会「永久挂起」而不报错——表现为"跑很久"且无任何线索，极难定位。
    这里把挂起转成超时后的明确 AssertionError，并直接点出最可能的原因。
    """
    box: dict = {}

    def _target():
        try:
            box["msg"] = ws.receive_json()
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    # daemon：超时后残留的阻塞线程不拖住解释器退出
    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AssertionError(
            f"等待服务端消息超时（{timeout}s）：服务端可能已异常中断。"
            "先查 interview_ws 是否抛异常（最常见原因：FakeSession 缺少会话层契约成员）。"
        )
    if "err" in box:
        raise box["err"]
    return box["msg"]


def _drain_until(ws, wanted, cap=60):
    """逐条读消息直到 wanted（类型集合）全部出现；返回收到的全部消息。"""
    got = []
    remaining = set(wanted)
    while remaining and len(got) < cap:
        msg = _recv_with_timeout(ws)
        got.append(msg)
        remaining.discard(msg.get("type", ""))
    assert not remaining, f"未等到 {remaining}，实际收到: {[m.get('type') for m in got]}"
    return got


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _wait_until(predicate, timeout=3.0, interval=0.05):
    """轮询等待服务端异步收尾（断连后落库 / finally 清理）完成。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _report_row():
    row = _run(get_report(SESSION_ID))
    if row is None:
        return None
    row["report"] = json.loads(row["report_json"])
    return row


def _session_row():
    return _run(get_session(SESSION_ID))


def _sessions_clean():
    return SESSION_ID not in state.active_sessions


# ===== 0. v8.6: 思考时长的服务端墙钟校验 + 按需改写 =====

class TestServerThinkingAnnotation:
    def test_annotated_once_per_answer(self, ws_client, fake_session):
        """每收一次回答，WS 层就把服务端墙钟差交给会话做交叉校验。"""
        state.active_sessions[SESSION_ID] = fake_session
        with ws_client.websocket_connect(f"/ws/interview/{SESSION_ID}") as ws:
            _drain_until(ws, {"interviewer_info", "dimension_weights", "round_start", "question"})
            ws.send_json({"type": "answer", "data": {"text": "我负责过订单系统重构"}})
            _drain_until(ws, {"diagnosis_result"})

            assert len(fake_session.server_thinking_calls) == 1
            # 墙钟差不可能是负数，也不该大到不合理（推题到收答只有几秒）
            assert 0 <= fake_session.server_thinking_calls[0] < 300


# 注：按需改写的 WS 转发路径不在此覆盖——答完一题后服务端会立刻推进到轮次收尾，
# 客户端再发 request_rewrite 与推进逻辑存在竞态，写在这里只会得到一条 flaky 用例。
# 改写的身份校验与流式产出的确定性部分在 tests/test_session.py::TestOnDemandRewrite
# 与 tests/test_diagnosis_engine.py::TestRewriteStreaming 覆盖。

# ===== 1. ping/pong =====

class TestPingPong:
    def test_ping_replies_pong_and_keeps_round_running(self, ws_client, fake_session):
        """心跳在答题等待循环内被响应，且不消耗题目/推进状态。"""
        state.active_sessions[SESSION_ID] = fake_session
        with ws_client.websocket_connect(f"/ws/interview/{SESSION_ID}") as ws:
            _drain_until(ws, {"interviewer_info", "dimension_weights", "round_start", "question"})

            for _ in range(2):  # 连发两次：心跳必须可重复且不改变循环状态
                ws.send_json({"type": "ping", "data": {}})
                msg = _recv_with_timeout(ws)
                assert msg == {"type": "pong", "data": {}}

            assert fake_session.answered_count == 0
            assert fake_session.flow_states[-1] == "waiting_answer"

            # 心跳之后面试照常走通（顺带钉住 4. 断连之外的正常完成路径）
            ws.send_json({"type": "answer", "data": {"text": ANSWER_1}})
            msgs = _drain_until(ws, {"interview_done"})
            types = [m["type"] for m in msgs]
            assert "diagnosis_result" in types
            assert "round_quality_check" in types
            assert "round_summary" in types

        assert _wait_until(_sessions_clean)
        row = _session_row()
        assert row["status"] == "completed"


# ===== 2. switch_mode =====

class TestSwitchMode:
    def test_valid_mode_switches_and_invalid_mode_errors_without_dropping(self,
                                                                          ws_client,
                                                                          fake_session):
        """合法模式回 mode_change 且会话状态真切换；非法模式回 error 但连接保持。"""
        state.active_sessions[SESSION_ID] = fake_session
        with ws_client.websocket_connect(f"/ws/interview/{SESSION_ID}") as ws:
            _drain_until(ws, {"question"})

            # 非法模式：回 error，连接不断，之后仍可正常答题
            ws.send_json({"type": "switch_mode", "data": {"mode": "bogus"}})
            err = _recv_with_timeout(ws)
            assert err["type"] == "error"
            assert "未知模式或阶段" in err["data"]["message"]
            assert fake_session.mode == "simulation"

            # 合法模式：回 mode_change，会话状态更新，pending_follow_up 被清空
            ws.send_json({"type": "switch_mode", "data": {"mode": "traditional"}})
            change = _recv_with_timeout(ws)
            assert change["type"] == "mode_change"
            assert change["data"]["mode"] == "traditional"
            assert fake_session.mode == "traditional"
            assert fake_session.pending_follow_up == ""

            ws.send_json({"type": "answer", "data": {"text": ANSWER_1}})
            _drain_until(ws, {"interview_done"})

        assert _wait_until(_sessions_clean)


# ===== 3. 结束口令 =====

class TestEndSignal:
    def test_end_command_skips_diagnosis_and_saves_full_report(self, ws_client, fake_session):
        """口令命中的回答不诊断、不计分，但报告照常生成且 status=completed。"""
        state.active_sessions[SESSION_ID] = fake_session
        with ws_client.websocket_connect(f"/ws/interview/{SESSION_ID}") as ws:
            _drain_until(ws, {"question"})

            ws.send_json({"type": "answer", "data": {"text": END_SIGNAL}})
            msgs = _drain_until(ws, {"interview_end_signal", "interview_done"})
            types = [m["type"] for m in msgs]
            assert "diagnosis_result" not in types  # 口令不进诊断
            assert fake_session.all_diagnoses == []
            assert fake_session.answered_count == 0

        assert _wait_until(_sessions_clean)
        row = _report_row()
        assert row is not None, "结束后必须落完整报告"
        assert row["report"]["overall_score"] == 3.5
        assert _session_row()["status"] == "completed"


# ===== 4. 断连存部分报告 + finally 清理 =====

class TestDisconnect:
    def test_disconnect_mid_interview_saves_partial_report_and_cleans_up(self, ws_client):
        """答完第一题、等第二题作答时断连：部分报告落库（interrupted）+ 会话引用清理。"""
        fake_session = FakeSession(trigger_extra_question=True)
        state.active_sessions[SESSION_ID] = fake_session
        with ws_client.websocket_connect(f"/ws/interview/{SESSION_ID}") as ws:
            _drain_until(ws, {"question"})

            # 第一题正常作答，质量不达标触发补题（顺带钉住 extra_question 分支）
            ws.send_json({"type": "answer", "data": {"text": ANSWER_1}})
            msgs = _drain_until(ws, {"extra_question"})
            assert fake_session.extra_questions_added == 1
            assert len(fake_session.all_diagnoses) == 1  # 已答部分必须存在，才有"部分报告"

            # 第二题展示后不回答，直接断连 → 服务端 receive 抛 WebSocketDisconnect
            _drain_until(ws, {"question"})
            ws.close()

            # 等待必须发生在 ws 上下文「内」：TestClient 在 with 退出时会中断服务端
            # 协程，而 CancelledError 不是 Exception（except Exception 抓不到），
            # 部分报告会被静默丢弃。这是 TestClient 的时序特性，生产 uvicorn 不作此中断。
            assert _wait_until(lambda: _report_row() is not None and _sessions_clean())

        row = _report_row()
        assert row["report"]["overall_score"] == 3.5
        assert _session_row()["status"] == "interrupted"


# ===== 握手契约 =====

class TestHandshake:
    def test_session_not_found_rejects_with_4000(self, ws_client):
        """未注册的 session_id：accept 后回 error 帧，再以 4000 关闭。"""
        with ws_client.websocket_connect("/ws/interview/no-such-session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "会话不存在" in msg["data"]["message"]
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_json()
            assert ei.value.code == 4000

    def test_handshake_needs_no_token(self, ws_client, fake_session):
        """v8.3: 握手不再要求任何凭据——连接不带 token 也能正常进入面试循环。

        此前 token 是必填 query 参数，缺它的连接会在 accept 之前被 4001 拒绝；
        现在 URL 上什么都不带也应当照常收到首帧。
        """
        state.active_sessions[SESSION_ID] = fake_session
        with ws_client.websocket_connect(f"/ws/interview/{SESSION_ID}") as ws:
            msg = _recv_with_timeout(ws)
            assert msg["type"] == "interviewer_info"
