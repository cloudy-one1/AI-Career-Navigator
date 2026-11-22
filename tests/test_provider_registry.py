"""
Provider 注册表自动探测测试（v6.0，对标 career-copilot PROVIDER_REGISTRY / createProvider）。

覆盖：validate_api_key（canonical 迁移）/ AI_PROVIDER_RESOLVED 自动探测 /
未知 provider 回退 / LLMClient auto 解析 / switch_provider（auto + Key 校验告警）。

注意：config.AI_PROVIDER 是导入期捕获的类属性，测试用 monkeypatch.setattr 直接改
单例属性（config.LLM_* 属性读取 self.AI_PROVIDER，monkeypatch 结束后自动还原）。
"""

import json
from unittest.mock import patch, MagicMock

from backend.config import config, validate_api_key
from backend.llm_client import LLMClient, _api_key_issue


class TestValidateApiKeyCanonical:
    """Key 校验 canonical 实现在 config 层，llm_client._api_key_issue 为兼容别名。"""

    def test_alias_identity(self):
        assert _api_key_issue is validate_api_key

    def test_messages_unchanged(self):
        assert validate_api_key("") == "API Key 未配置"
        assert validate_api_key("sk-1234567890abcdef") is None


class TestProviderKeyIssue:
    def test_valid_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123456")
        assert config.provider_key_issue("deepseek") is None

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        assert "未配置" in config.provider_key_issue("deepseek")

    def test_unknown_provider(self):
        assert config.provider_key_issue("no_such") is not None


class TestAutoResolve:
    def test_explicit_provider_passthrough(self):
        assert config.AI_PROVIDER_RESOLVED == config.AI_PROVIDER

    def test_auto_picks_first_valid_key(self, monkeypatch):
        monkeypatch.setattr(config, "AI_PROVIDER", "auto")
        for env in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-valid-123")
        assert config.AI_PROVIDER_RESOLVED == "qwen"

    def test_auto_no_key_falls_back_deepseek(self, monkeypatch):
        monkeypatch.setattr(config, "AI_PROVIDER", "auto")
        for env in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY",
                    "ZHIPU_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(env, raising=False)
        assert config.AI_PROVIDER_RESOLVED == "deepseek"

    def test_unknown_provider_falls_back_deepseek(self, monkeypatch):
        monkeypatch.setattr(config, "AI_PROVIDER", "not_a_provider")
        assert config.AI_PROVIDER_RESOLVED == "deepseek"

    def test_global_llm_api_key_wins_first_registered(self, monkeypatch):
        # LLM_API_KEY 全局覆盖时，auto 探测应命中注册表第一个后端
        monkeypatch.setattr(config, "AI_PROVIDER", "auto")
        monkeypatch.setenv("LLM_API_KEY", "sk-global-valid-123")
        assert config.AI_PROVIDER_RESOLVED == "deepseek"


class TestLLMClientAuto:
    def test_client_resolves_auto(self, monkeypatch):
        monkeypatch.setattr(config, "AI_PROVIDER", "auto")
        for env in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY"):
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setenv("ZHIPU_API_KEY", "sk-zhipu-valid-123")
        client = LLMClient(provider="auto")
        assert client.provider == "zhipu"

    def test_client_explicit_provider_unchanged(self):
        client = LLMClient(provider="deepseek")
        assert client.provider == "deepseek"

    def test_switch_provider_auto(self):
        client = LLMClient(provider="deepseek")
        assert client.switch_provider("auto") is True
        assert client.provider in config.AI_PROVIDERS

    def test_switch_provider_unknown_rejected(self):
        client = LLMClient(provider="deepseek")
        assert client.switch_provider("no_such") is False
        assert client.provider == "deepseek"

    def test_switch_provider_bad_key_warns(self, caplog):
        client = LLMClient(provider="deepseek")
        with patch("backend.llm_client.config.provider_key_issue", return_value="API Key 未配置"):
            assert client.switch_provider("openai") is True
            assert any("API Key" in r.message for r in caplog.records)


class TestProviderApiAuto:
    """v8.24 回归：AI_PROVIDER=auto 时管理面板不能 500，switch-provider 接受 auto。

    事故背景：config.py 与 .env.example 都宣称支持 auto，但
    list_providers 直接 config.AI_PROVIDERS[config.AI_PROVIDER] 下标 →
    KeyError 500；switch_provider 又拒绝 auto——"auto" 在管理面板上是半接线状态。
    """

    def test_list_providers_with_auto(self, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.main import app

        monkeypatch.setattr(config, "AI_PROVIDER", "auto")
        resp = TestClient(app).get("/api/providers")
        assert resp.status_code == 200, f"auto 下 /api/providers 不得 500: {resp.status_code}"
        body = resp.json()
        assert body["current"]["id"] == config.AI_PROVIDER_RESOLVED
        assert sum(1 for p in body["providers"] if p["is_current"]) == 1

    def test_health_reports_resolved_provider(self, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.main import app

        monkeypatch.setattr(config, "AI_PROVIDER", "auto")
        resp = TestClient(app).get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["provider"] == config.AI_PROVIDER_RESOLVED

    def test_switch_provider_accepts_auto(self, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.routers import state

        monkeypatch.setattr(config, "AI_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        old_client, old_engine = state.llm_client, state.diagnosis_engine
        try:
            resp = TestClient(app).post("/api/switch-provider", json={"provider": "auto"})
            assert resp.status_code == 200, resp.text
            # 就地探测的结果是显式后端，而非把 "auto" 原样塞回 config
            assert resp.json()["provider"] == "deepseek"
            assert config.AI_PROVIDER == "deepseek"
        finally:
            state.llm_client, state.diagnosis_engine = old_client, old_engine

    def test_switch_provider_auto_without_any_key_rejected(self, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.main import app

        monkeypatch.setattr(config, "AI_PROVIDER", "deepseek")
        for env in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY",
                    "ZHIPU_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(env, raising=False)
        resp = TestClient(app).post("/api/switch-provider", json={"provider": "auto"})
        assert resp.status_code == 400
        assert "auto" in resp.json()["detail"]


class TestChatJsonTolerant:
    """chat_json 应借四级容错就地修复轻微畸形输出，不再浪费候选降级。

    注意：直接替换 _candidates 为 mock 候选（_call_with_fallback 走 cand.client，
    而非 self.client），确保测试绝不发起真实网络请求，也不触发真实 fallback 链。
    """

    @staticmethod
    def _client_with_output(content: str) -> tuple[LLMClient, MagicMock]:
        from backend.llm_client import _Candidate

        client = LLMClient(provider="deepseek")
        client.api_key = "sk-valid-key-123"  # 绕过 Key 短路
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = resp
        client._candidates = [_Candidate("deepseek", "deepseek-chat", mock_openai, MagicMock())]
        return client, mock_openai

    def test_repairs_trailing_comma(self):
        client, mock_openai = self._client_with_output('{"a": 1, "b": [1, 2,]}')
        data = client.chat_json("s", "u")
        assert data == {"a": 1, "b": [1, 2]}
        mock_openai.chat.completions.create.assert_called_once()  # 未发生候选降级

    def test_repairs_fenced_output(self):
        client, _ = self._client_with_output('```json\n{"ok": true}\n```')
        assert client.chat_json("s", "u") == {"ok": True}

    def test_unrepairable_returns_error_dict(self):
        client, _ = self._client_with_output("完全不是 JSON")
        data = client.chat_json("s", "u")
        assert "error" in data
        json.dumps(data)  # 可序列化
