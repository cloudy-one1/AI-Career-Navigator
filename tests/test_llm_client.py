"""
LLM API Key 校验器单元测试。

覆盖四类用例：空 Key / 占位符模板 / 含非 ASCII 字符 / 正常 Key，
以及 chat* 方法对无效 Key 的短路返回（友好中文错误，且不发起网络请求）。
"""
import json
from unittest.mock import patch

import pytest

from backend.llm_client import LLMClient, _api_key_issue


class TestApiKeyIssue:
    """纯函数 _api_key_issue：四类用例"""

    def test_empty_key(self):
        assert _api_key_issue("") == "API Key 未配置"

    def test_placeholder_key(self):
        assert _api_key_issue("sk-your-deepseek-key-here") == "API Key 是占位符模板，请填写真实 Key"
        assert _api_key_issue("sk-xxxx") == "API Key 是占位符模板，请填写真实 Key"

    def test_non_ascii_key(self):
        issue = _api_key_issue("sk-你的真实Key")
        assert "非 ASCII" in issue

    def test_valid_key(self):
        assert _api_key_issue("sk-1234567890abcdef") is None


class TestChatShortCircuit:
    """无效 Key 时 chat* 方法短路返回友好中文错误，不发起网络请求"""

    @staticmethod
    def _client_with_bad_key() -> LLMClient:
        client = LLMClient(provider="deepseek")
        client.api_key = "sk-你的真实Key"
        return client

    def test_chat_short_circuit(self):
        client = self._client_with_bad_key()
        with patch.object(client.client.chat.completions, "create") as mock_create:
            raw = client.chat("system", "user")
        mock_create.assert_not_called()
        data = json.loads(raw)
        assert "error" in data
        assert "API Key" in data["error"]
        assert "DEEPSEEK_API_KEY" in data["error"]

    def test_chat_stream_short_circuit(self):
        client = self._client_with_bad_key()
        with patch.object(client.client.chat.completions, "create") as mock_create:
            chunks = list(client.chat_stream("system", "user"))
        mock_create.assert_not_called()
        assert len(chunks) == 1
        data = json.loads(chunks[0])
        assert "error" in data
        assert "DEEPSEEK_API_KEY" in data["error"]

    @pytest.mark.asyncio
    async def test_chat_stream_async_short_circuit(self):
        client = self._client_with_bad_key()
        chunks = []
        async for chunk in client.chat_stream_async("system", "user"):
            chunks.append(chunk)
        assert len(chunks) == 1
        data = json.loads(chunks[0])
        assert "error" in data
        assert "DEEPSEEK_API_KEY" in data["error"]


class TestClientTimeout:
    """v8.10：每个 OpenAI/AsyncOpenAI 客户端都必须带显式超时。

    此前三处构造点都不传 timeout，落到 SDK 默认的 600s：上游挂起即把面试主循环
    钉死十分钟，而且 SDK 只在超时/报错之后才会换下一个 fallback 候选 —— 也就是
    说"没有超时"实际等于"降级链一起失效"。
    """

    def test_main_clients_have_bounded_timeout(self):
        from backend.config import config
        client = LLMClient()
        assert config.LLM_TIMEOUT > 0
        for cli in (client.client, client.async_client):
            assert getattr(cli, "timeout", None) is not None, "客户端未设置超时"
            assert float(cli.timeout) <= 120, f"超时过长：{cli.timeout}"

    def test_fallback_candidates_inherit_timeout(self, monkeypatch):
        """fallback 候选同样要有限时，否则降级到备用模型后又挂 600s。"""
        monkeypatch.setenv("LLM_FALLBACK_CHAIN", "deepseek:deepseek-chat,qwen:qwen-plus")
        monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-test-key-abcdef")
        client = LLMClient()
        assert len(client._candidates) >= 2, "fallback 候选未被构造"
        for cand in client._candidates:
            assert float(cand.client.timeout) <= 120
            assert float(cand.async_client.timeout) <= 120
