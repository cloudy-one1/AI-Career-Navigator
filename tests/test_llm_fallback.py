"""LLM 调用 fallback（优雅降级）单元测试 v4.3。

通过用 mock 候选覆盖 LLMClient._candidates，验证：
- 主候选成功直接返回；
- 主候选异常 / 返回不可用内容时自动切换备用候选；
- 全部失败时返回 error JSON；
- 流式在主候选未产出 chunk 即失败时无缝切换；已产出后失败则停止并推送 error chunk；
- LLM_FALLBACK_CHAIN 配置正确解析为有序候选。

调用方（chat / chat_json / chat_stream_async 等）签名与对外行为保持不变。
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.config import config
from backend.llm_client import LLMClient, _Candidate


# ===== mock 辅助 =====
def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


async def _async_stream(chunks):
    for c in chunks:
        yield c


async def _async_stream_raise(chunks, exc):
    for i, c in enumerate(chunks):
        yield c
        if i == 0:
            raise exc


def _candidate(text="ok", provider="p", model="m", error=None, stream_chunks=None):
    """构造 mock 候选。error: None / 'exc_before' / 'bad_json' / 'exc_after'。"""
    client = MagicMock()
    async_client = AsyncMock()
    chunks = stream_chunks if stream_chunks is not None else [text]
    if error == "exc_before":
        client.chat.completions.create.side_effect = RuntimeError("boom")
        async_client.chat.completions.create.side_effect = RuntimeError("boom")
    elif error == "bad_json":
        client.chat.completions.create.return_value = _resp("not a json")
        async_client.chat.completions.create.return_value = _async_stream([_chunk("not a json")])
    elif error == "exc_after":
        client.chat.completions.create.return_value = _resp(text)
        async_client.chat.completions.create.return_value = _async_stream_raise(
            [_chunk(c) for c in chunks], RuntimeError("mid")
        )
    else:
        client.chat.completions.create.return_value = _resp(text)
        async_client.chat.completions.create.return_value = _async_stream([_chunk(c) for c in chunks])
    return _Candidate(provider=provider, model=model, client=client, async_client=async_client)


def _client_with(candidates):
    client = LLMClient(provider="deepseek")
    client._candidates = candidates
    return client


class TestNonStreamFallback:
    def test_primary_success(self):
        client = _client_with([_candidate(text="A")])
        assert client.chat("s", "u") == "A"

    def test_fallback_on_exception(self):
        c1 = _candidate(error="exc_before")
        c2 = _candidate(text="B")
        client = _client_with([c1, c2])
        assert client.chat("s", "u") == "B"
        c1.client.chat.completions.create.assert_called_once()
        c2.client.chat.completions.create.assert_called_once()

    def test_all_fail_returns_error_json(self):
        c1 = _candidate(error="exc_before")
        c2 = _candidate(error="exc_before")
        client = _client_with([c1, c2])
        data = json.loads(client.chat("s", "u"))
        assert "error" in data
        assert "所有模型均调用失败" in data["error"]

    def test_chat_json_fallback_on_bad_json(self):
        c1 = _candidate(error="bad_json")
        c2 = _candidate(text='{"score": 4}')
        client = _client_with([c1, c2])
        assert client.chat_json("s", "u") == {"score": 4}

    def test_chat_json_all_bad_json(self):
        c1 = _candidate(error="bad_json")
        c2 = _candidate(error="bad_json")
        client = _client_with([c1, c2])
        assert "error" in client.chat_json("s", "u")


class TestStreamFallback:
    @pytest.mark.asyncio
    async def test_fallback_before_first_chunk(self):
        c1 = _candidate(error="exc_before")
        c2 = _candidate(text="B", stream_chunks=["B1", "B2"])
        client = _client_with([c1, c2])
        chunks = [c async for c in client.chat_stream_async("s", "u")]
        assert chunks == ["B1", "B2"]

    @pytest.mark.asyncio
    async def test_stop_after_mid_stream_failure(self):
        c1 = _candidate(error="exc_after", stream_chunks=["P1", "P2"])
        c2 = _candidate(text="B", stream_chunks=["B1"])
        client = _client_with([c1, c2])
        chunks = [c async for c in client.chat_stream_async("s", "u")]
        # 已产出 P1 后失败：不拼接备用，停止并报错
        assert chunks[0] == "P1"
        err = json.loads(chunks[1])
        assert "error" in err

    @pytest.mark.asyncio
    async def test_all_stream_fail(self):
        c1 = _candidate(error="exc_before")
        c2 = _candidate(error="exc_before")
        client = _client_with([c1, c2])
        chunks = [c async for c in client.chat_stream_async("s", "u")]
        err = json.loads(chunks[0])
        assert "所有模型流式调用均失败" in err["error"]


class TestFallbackChainConfig:
    def test_empty_chain(self, monkeypatch):
        monkeypatch.setenv("LLM_FALLBACK_CHAIN", "")
        assert config.LLM_FALLBACK_CHAIN == []

    def test_parse_chain(self, monkeypatch):
        monkeypatch.setenv("LLM_FALLBACK_CHAIN", "deepseek:deepseek-chat,qwen:qwen-plus")
        chain = config.LLM_FALLBACK_CHAIN
        assert len(chain) == 2
        assert chain[0] == {"provider": "deepseek", "model": "deepseek-chat",
                             "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
                             "base_url": "https://api.deepseek.com"}
        assert chain[1]["provider"] == "qwen" and chain[1]["model"] == "qwen-plus"

    def test_unknown_provider_skipped(self, monkeypatch):
        monkeypatch.setenv("LLM_FALLBACK_CHAIN", "unknown:x,deepseek:deepseek-chat")
        chain = config.LLM_FALLBACK_CHAIN
        assert len(chain) == 1
        assert chain[0]["provider"] == "deepseek"
