"""任务分级超时（v8.15）。

LLM_TIMEOUT 是全局上限：报告/职业规划这类慢任务 60s 常不够，此前只能整体调大，
等于给实时链路也放开了等待上限。v8.15 引入 LLM_TASK_TIMEOUTS（与 v6.2 任务级
模型绑定同构）——绑定换的是"用哪个模型"，分级超时换的是"等多久"。

实现要点：超时经每次 create() 的**按请求参数**下发（OpenAI SDK 支持按请求覆盖
客户端缺省），客户端构造时烤死的全局值只作缺省。端到端用例直接断言 create()
收到的 timeout 值——若有人把按请求下发改回"只在构造时设置"，本文件即红。
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend import llm_client as llm_client_mod
from backend.config import config

# ==================== 1. LLM_TASK_TIMEOUTS 解析 ====================

class TestTaskTimeoutsParsing:
    def test_unset_returns_empty(self, monkeypatch):
        monkeypatch.delenv("LLM_TASK_TIMEOUTS", raising=False)
        assert config.LLM_TASK_TIMEOUTS == {}

    def test_valid_config(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 180, "career": 120.5}')
        assert config.LLM_TASK_TIMEOUTS == {"report": 180.0, "career": 120.5}

    def test_unknown_task_skipped(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 180, "unknown_task": 30}')
        assert config.LLM_TASK_TIMEOUTS == {"report": 180.0}

    def test_non_numeric_skipped(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": "abc", "career": 120}')
        assert config.LLM_TASK_TIMEOUTS == {"career": 120.0}

    def test_non_positive_skipped(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 0, "career": -5, "parse": 90}')
        assert config.LLM_TASK_TIMEOUTS == {"parse": 90.0}

    def test_invalid_json_ignored(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{not-a-json')
        assert config.LLM_TASK_TIMEOUTS == {}

    def test_non_object_ignored(self, monkeypatch):
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '[180, 120]')
        assert config.LLM_TASK_TIMEOUTS == {}


# ==================== 2. resolve_task_timeout ====================

class TestResolveTaskTimeout:
    def test_default_is_llm_timeout(self, monkeypatch):
        monkeypatch.delenv("LLM_TASK_TIMEOUTS", raising=False)
        monkeypatch.setenv("LLM_TIMEOUT", "45")
        client = llm_client_mod.LLMClient()
        assert client.resolve_task_timeout("report") == 45.0
        assert client.resolve_task_timeout(None) == 45.0

    def test_task_override_wins(self, monkeypatch):
        monkeypatch.setenv("LLM_TIMEOUT", "60")
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 180}')
        client = llm_client_mod.LLMClient()
        assert client.resolve_task_timeout("report") == 180.0
        assert client.resolve_task_timeout("diagnosis") == 60.0  # 未配置任务不受影响


# ==================== 3. 端到端：timeout 落到 create() ====================

def _fake_response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
    )


def _fake_pool(recorded: dict) -> list:
    """构造一个候选池：create() 记录最近一次调用的全部 kwargs 并返回可用 JSON 响应。"""
    def create(**kw):
        recorded["kwargs"] = kw
        return _fake_response()

    async def async_create(**kw):
        recorded["kwargs"] = kw
        return _async_iter([SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="x"))])])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    fake_async_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=async_create)))
    return [SimpleNamespace(provider="deepseek", model="m1",
                            client=fake_client, async_client=fake_async_client)]


def _async_iter(items):
    async def _gen():
        for it in items:
            yield it
    return _gen()


def _make_client():
    with patch.object(llm_client_mod, "_api_key_issue", return_value=None):
        return llm_client_mod.LLMClient()


class TestTimeoutReachesCreate:
    """端到端：分级超时必须真的传到 OpenAI SDK 的 create() 调用上。"""

    def test_non_stream_report_gets_task_timeout(self, monkeypatch):
        monkeypatch.delenv("LLM_TIMEOUT", raising=False)
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 180}')
        client = _make_client()
        recorded: dict = {}
        client._candidates = _fake_pool(recorded)

        out = client.chat("sys", "user", task="report")
        assert json.loads(out) == {"ok": True}
        assert recorded["kwargs"]["timeout"] == 180.0

    def test_non_stream_default_timeout_without_task(self, monkeypatch):
        monkeypatch.setenv("LLM_TIMEOUT", "60")
        monkeypatch.delenv("LLM_TASK_TIMEOUTS", raising=False)
        client = _make_client()
        recorded: dict = {}
        client._candidates = _fake_pool(recorded)

        client.chat("sys", "user")
        assert recorded["kwargs"]["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_async_stream_gets_task_timeout(self, monkeypatch):
        monkeypatch.delenv("LLM_TIMEOUT", raising=False)
        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 180}')
        client = _make_client()
        recorded: dict = {}
        client._candidates = _fake_pool(recorded)

        chunks = [c async for c in client.chat_stream_async("sys", "user", task="report")]
        assert chunks == ["x"]
        assert recorded["kwargs"]["timeout"] == 180.0

    def test_falsify_flip(self, monkeypatch):
        """证伪锚点：改 env 里的任务超时，create() 收到的值必须跟着变。"""
        monkeypatch.delenv("LLM_TIMEOUT", raising=False)
        client = _make_client()
        recorded: dict = {}
        client._candidates = _fake_pool(recorded)

        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 100}')
        client.chat("sys", "user", task="report")
        assert recorded["kwargs"]["timeout"] == 100.0

        monkeypatch.setenv("LLM_TASK_TIMEOUTS", '{"report": 200}')
        client.chat("sys", "user", task="report")
        assert recorded["kwargs"]["timeout"] == 200.0
