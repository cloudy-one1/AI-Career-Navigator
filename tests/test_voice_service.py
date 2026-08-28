"""backend/voice_service.py — MiMo 云端语音服务单元测试（chat/completions 协议）。"""
import base64
from unittest.mock import patch, MagicMock

import pytest

from backend.voice_service import VoiceService


@pytest.fixture
def svc():
    """构造一个 VoiceService 实例，默认未配置 Key（与 .env 解耦，测试不依赖真实 Key）。"""
    svc = VoiceService()
    svc.api_key = ""
    return svc


# ── key 校验 ──
def test_disabled_without_key(svc):
    assert svc.enabled is False


def test_enabled_with_key(svc):
    svc.api_key = "sk-test-key"
    assert svc.enabled is True


def test_enabled_with_mimo_prefix(svc):
    svc.api_key = "mimo-abc"
    assert svc.enabled is True


def test_enabled_ignores_whitespace(svc):
    svc.api_key = "  sk-test-key  "
    assert svc.enabled is True


# ── 音色映射 ──
def test_resolve_voice_defaults(svc):
    """None/空/default/未知音色均回退到配置默认音色。"""
    assert svc._resolve_voice(None) == svc.default_voice
    assert svc._resolve_voice("") == svc.default_voice
    assert svc._resolve_voice("default") == svc.default_voice
    assert svc._resolve_voice("不存在的音色") == svc.default_voice


def test_resolve_voice_keeps_preset(svc):
    """官方预置音色原样保留（大小写敏感）。"""
    assert svc._resolve_voice("冰糖") == "冰糖"
    assert svc._resolve_voice("茉莉") == "茉莉"
    assert svc._resolve_voice("mimo_default") == "mimo_default"
    assert svc._resolve_voice("Mia") == "Mia"
    assert svc._resolve_voice("Dean") == "Dean"


# ── TTS：未配 Key 直接降级 ──
def test_synthesize_without_key_returns_not_used(svc):
    res = svc.synthesize("你好")
    assert res.used is False
    assert "MIMO_API_KEY" in res.message


def test_synthesize_empty_text(svc):
    svc.api_key = "sk-test-key"
    res = svc.synthesize("   ")
    assert res.used is True  # 已配置则视为"已尝试"，但标记空文本
    assert "空" in res.message


# ── TTS：成功返回 Base64 WAV ──
def test_synthesize_success(svc):
    svc.api_key = "sk-test-key"
    fake_audio = base64.b64encode(b"FAKE_WAV_BYTES").decode("ascii")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"audio": {"data": fake_audio}}}]
    }
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.synthesize("你好")
    assert res.used is True
    assert res.format == "wav"
    assert res.audio_b64 == fake_audio
    # 校验请求体（chat/completions 协议）
    _, kwargs = fake_client.post.call_args
    assert kwargs["json"]["model"] == svc.tts_model
    messages = kwargs["json"]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[1] == {"role": "assistant", "content": "你好"}
    assert kwargs["json"]["audio"] == {"format": "wav", "voice": svc.default_voice}
    assert kwargs["headers"]["api-key"] == "sk-test-key"
    assert "Authorization" not in kwargs["headers"]


def test_synthesize_uses_requested_voice(svc):
    svc.api_key = "sk-test-key"
    fake_audio = base64.b64encode(b"X").decode("ascii")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"audio": {"data": fake_audio}}}]
    }
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.synthesize("你好", voice="茉莉")
    assert res.used is True
    _, kwargs = fake_client.post.call_args
    assert kwargs["json"]["audio"]["voice"] == "茉莉"


def test_synthesize_strips_data_url_prefix(svc):
    """兼容 audio.data 带 data:audio/wav;base64, 前缀的形态。"""
    svc.api_key = "sk-test-key"
    fake_audio = base64.b64encode(b"FAKE_WAV").decode("ascii")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"audio": {"data": f"data:audio/wav;base64,{fake_audio}"}}}]
    }
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.synthesize("你好")
    assert res.used is True
    assert res.audio_b64 == fake_audio


def test_synthesize_missing_audio_field(svc):
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": [{"message": {"content": "无音频"}}]}
    fake_resp.text = "{}"
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.synthesize("你好")
    assert res.used is False
    assert "音频" in res.message


def test_synthesize_http_error(svc):
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 500
    fake_resp.text = "boom"
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.synthesize("你好")
    assert res.used is False
    assert "500" in res.message


def test_synthesize_timeout(svc):
    svc.api_key = "sk-test-key"
    from httpx import TimeoutException
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.side_effect = TimeoutException("timeout")

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.synthesize("你好")
    assert res.used is False
    assert "超时" in res.message


# ── ASR：未配 Key 直接降级 ──
def test_transcribe_without_key(svc):
    res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "MIMO_API_KEY" in res.message


def test_transcribe_empty_audio(svc):
    svc.api_key = "sk-test-key"
    res = svc.transcribe(b"")
    assert res.ok is False
    assert "音频为空" in res.message


# ── ASR：成功返回文本 ──
def test_transcribe_success(svc):
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": "你好世界"}}]
    }
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.transcribe(b"audio-bytes", "rec.webm", "audio/webm")
    assert res.ok is True
    assert res.text == "你好世界"
    # 校验请求体（chat/completions + input_audio data URL）
    _, kwargs = fake_client.post.call_args
    payload = kwargs["json"]
    assert payload["model"] == svc.asr_model
    assert payload["asr_options"] == {"language": svc.asr_language}
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "input_audio"
    expected_url = f"data:audio/webm;base64,{base64.b64encode(b'audio-bytes').decode('ascii')}"
    assert content[0]["input_audio"]["data"] == expected_url
    assert kwargs["headers"]["api-key"] == "sk-test-key"


def test_transcribe_success_list_content(svc):
    """兼容 content 为 [{"text": ...}] 列表形态。"""
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": [{"text": "你好"}, {"text": "世界"}]}}]
    }
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.transcribe(b"audio")
    assert res.ok is True
    assert res.text == "你好世界"


def test_transcribe_empty_result_text(svc):
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"choices": [{"message": {"content": "   "}}]}
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "未识别" in res.message


def test_transcribe_http_error(svc):
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 429
    fake_resp.text = "rate limited"
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "429" in res.message


def test_transcribe_bad_json(svc):
    svc.api_key = "sk-test-key"
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.side_effect = ValueError("bad json")
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post.return_value = fake_resp

    with patch("backend.voice_service.httpx.Client", return_value=fake_client):
        res = svc.transcribe(b"audio")
    assert res.ok is False
    assert "格式" in res.message
