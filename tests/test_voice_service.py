"""
voice_service.py 测试：TTS 合成、ASR 转写、密钥解析、启用开关。
通过 _fake_client 复用 httpx.Client 的 mock 构造，避免每个用例重复粘贴样板。

注意：VoiceService 构造无参，密钥来自 config.MIMO_API_KEY（单例，导入时加载）；
启用判定要求 key 以 sk-/mimo- 开头；_resolve_voice 为私有方法。
"""

import base64
from unittest.mock import patch, MagicMock
import pytest
from httpx import TimeoutException

from backend.config import config
from backend.voice_service import VoiceService


@pytest.fixture
def svc():
    return VoiceService()


def _fake_client(status=200, json_payload=None, text="{}", side_effect=None):
    """构造一个可进入 `with` 上下文、post 返回可控响应的 httpx.Client mock。"""
    fake_resp = MagicMock()
    fake_resp.status_code = status
    fake_resp.json.return_value = json_payload if json_payload is not None else {}
    fake_resp.text = text

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    if side_effect is not None:
        client.post.side_effect = side_effect
    else:
        client.post.return_value = fake_resp
    return client


# ----- 启用开关 -----

def test_enabled_true_with_sk_key(svc):
    svc.api_key = "sk-instance"
    assert svc.enabled is True


def test_enabled_false_without_key(svc):
    svc.api_key = ""
    assert svc.enabled is False


def test_api_key_loaded_from_config(svc):
    """构造时密钥来自配置单例"""
    assert svc.api_key == (config.MIMO_API_KEY or "").strip()


# ----- 音色解析（私有方法） -----

def test_resolve_voice_defaults(svc):
    assert svc._resolve_voice(None) == svc.default_voice
    assert svc._resolve_voice("") == svc.default_voice


def test_resolve_voice_keeps_preset(svc):
    assert svc._resolve_voice("茉莉") == "茉莉"


def test_resolve_voice_falls_back_for_unknown(svc):
    assert svc._resolve_voice("不存在的音色") == svc.default_voice


# ----- v6.0: 音色别名映射表（对标 career-copilot DASHSCOPE_VOICE_MAP） -----

def test_resolve_voice_alias_openai_style(svc):
    assert svc._resolve_voice("alloy") == "冰糖"
    assert svc._resolve_voice("onyx") == "Dean"
    assert svc._resolve_voice("shimmer") == "Mia"


def test_resolve_voice_alias_case_insensitive(svc):
    assert svc._resolve_voice("Nova") == "茉莉"
    assert svc._resolve_voice("ALLOY") == "冰糖"


def test_resolve_voice_gender_alias(svc):
    assert svc._resolve_voice("male") == "Dean"
    assert svc._resolve_voice("female") == "茉莉"


def test_resolve_voice_default_alias(svc):
    """显式 default 别名 → 配置默认音色，且不产生未知告警分支。"""
    assert svc._resolve_voice("default") == svc.default_voice


# ----- TTS 合成 -----

def test_synthesize_empty_text_short_circuits(svc):
    """空文本在启用判定前直接返回 used=True（跳过合成）"""
    res = svc.synthesize("")
    assert res.used is True
    assert "文本为空" in res.message


def test_synthesize_without_key_returns_not_used(svc):
    svc.api_key = ""
    res = svc.synthesize("你好")
    assert res.used is False
    assert "未配置" in res.message


def test_synthesize_success(svc):
    svc.api_key = "sk-test-key"
    fake_audio = base64.b64encode(b"FAKE_WAV_BYTES").decode("ascii")
    client = _fake_client(200, {"choices": [{"message": {"audio": {"data": fake_audio}}}]})
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.synthesize("你好")
    assert res.used is True
    assert res.format == "wav"
    assert res.audio_b64 == fake_audio
    _, kwargs = client.post.call_args
    assert kwargs["json"]["model"] == svc.tts_model
    messages = kwargs["json"]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[1] == {"role": "assistant", "content": "你好"}
    assert kwargs["json"]["audio"] == {"format": "wav", "voice": svc._resolve_voice(None)}
    assert kwargs["headers"]["api-key"] == "sk-test-key"


def test_synthesize_uses_requested_voice(svc):
    svc.api_key = "sk-test-key"
    fake_audio = base64.b64encode(b"X").decode("ascii")
    client = _fake_client(200, {"choices": [{"message": {"audio": {"data": fake_audio}}}]})
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.synthesize("你好", voice="茉莉")
    assert res.used is True
    _, kwargs = client.post.call_args
    assert kwargs["json"]["audio"]["voice"] == "茉莉"


def test_synthesize_strips_data_url_prefix(svc):
    svc.api_key = "sk-test-key"
    fake_audio = base64.b64encode(b"FAKE_WAV").decode("ascii")
    client = _fake_client(
        200, {"choices": [{"message": {"audio": {"data": f"data:audio/wav;base64,{fake_audio}"}}}]}
    )
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.synthesize("你好")
    assert res.used is True
    assert res.audio_b64 == fake_audio


def test_synthesize_missing_audio_field(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(200, {"choices": [{"message": {"content": "无音频"}}]}, text="{}")
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.synthesize("你好")
    assert res.used is False
    assert "音频" in res.message


def test_synthesize_http_error(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(500, {"choices": []}, text="boom")
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.synthesize("你好")
    assert res.used is False
    assert "500" in res.message


def test_synthesize_timeout(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(side_effect=TimeoutException("timeout"))
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.synthesize("你好")
    assert res.used is False
    assert "超时" in res.message


# ----- ASR 转写 -----

def test_transcribe_without_key(svc):
    svc.api_key = ""
    res = svc.transcribe(b"audio-bytes", "rec.webm", "audio/webm")
    assert res.ok is False
    assert "未配置" in res.message


def test_transcribe_empty_audio(svc):
    res = svc.transcribe(b"", "rec.webm", "audio/webm")
    assert res.ok is False
    assert "音频为空" in res.message


def test_transcribe_success(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(200, {"choices": [{"message": {"content": "你好世界"}}]})
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.transcribe(b"audio-bytes", "rec.webm", "audio/webm")
    assert res.ok is True
    assert res.text == "你好世界"
    _, kwargs = client.post.call_args
    payload = kwargs["json"]
    assert payload["model"] == svc.asr_model
    assert payload["asr_options"] == {"language": svc.asr_language}
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "input_audio"
    expected_url = f"data:audio/webm;base64,{base64.b64encode(b'audio-bytes').decode('ascii')}"
    assert content[0]["input_audio"]["data"] == expected_url
    assert kwargs["headers"]["api-key"] == "sk-test-key"


def test_transcribe_success_list_content(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(200, {"choices": [{"message": {"content": [{"text": "你好"}, {"text": "世界"}]}}]})
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.transcribe(b"audio")
    assert res.ok is True
    assert res.text == "你好世界"


def test_transcribe_empty_result_text(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(200, {"choices": [{"message": {"content": "   "}}]})
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "未识别" in res.message


def test_transcribe_http_error(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(429, {"choices": []}, text="rate limited")
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "429" in res.message


def test_transcribe_bad_json(svc):
    svc.api_key = "sk-test-key"
    client = _fake_client(200, None)
    client.post.return_value.json.side_effect = ValueError("bad json")
    with patch("backend.voice_service.httpx.Client", return_value=client):
        res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "格式" in res.message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
