"""backend/main.py — /api/voice/tts 与 /api/voice/asr 代理路由测试。"""
import base64
from unittest.mock import patch

from backend.voice_service import voice_service, TTSUsage, ASRResult


# ── TTS 路由 ──
def test_voice_tts_requires_text(client):
    resp = client.post("/api/voice/tts", json={"text": "   "})
    assert resp.status_code == 400


def test_voice_tts_without_key_degrades(client):
    # 未配置 MIMO_API_KEY -> used=false，前端据此降级浏览器（与 .env 解耦，显式置空）
    with patch.object(voice_service, "api_key", ""):
        resp = client.post("/api/voice/tts", json={"text": "你好"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["used"] is False
    assert "MIMO_API_KEY" in data["message"]


def test_voice_tts_success(client):
    fake_bytes = b"FAKE_WAV"
    with patch.object(voice_service, "api_key", "sk-test-key"), \
         patch.object(voice_service, "synthesize", return_value=TTSUsage(
             used=True, audio_b64=base64.b64encode(fake_bytes).decode("ascii"), format="wav", message=""
         )):
        resp = client.post("/api/voice/tts", json={"text": "你好世界", "voice": "冰糖"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["used"] is True
    assert data["audio_b64"] == base64.b64encode(fake_bytes).decode("ascii")


def test_voice_tts_success_failure_path(client):
    with patch.object(voice_service, "api_key", "sk-test-key"), \
         patch.object(voice_service, "synthesize", return_value=TTSUsage(
             used=False, message="MiMo TTS 请求失败（500）"
         )):
        resp = client.post("/api/voice/tts", json={"text": "你好"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["used"] is False
    assert "500" in data["message"]


# ── ASR 路由 ──
def test_voice_asr_without_key_degrades(client):
    with patch.object(voice_service, "api_key", ""):
        resp = client.post("/api/voice/asr", files={"file": ("rec.webm", b"audio-bytes", "audio/webm")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "MIMO_API_KEY" in data["message"]


def test_voice_asr_empty_file(client):
    with patch.object(voice_service, "api_key", "sk-test-key"):
        resp = client.post("/api/voice/asr", files={"file": ("rec.webm", b"", "audio/webm")})
    assert resp.status_code == 400


def test_voice_asr_success(client):
    with patch.object(voice_service, "api_key", "sk-test-key"), \
         patch.object(voice_service, "transcribe", return_value=ASRResult(
             ok=True, text="这是我的回答", message=""
         )):
        resp = client.post("/api/voice/asr", files={"file": ("rec.webm", b"audio-bytes", "audio/webm")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["text"] == "这是我的回答"


def test_voice_asr_failure_path(client):
    with patch.object(voice_service, "api_key", "sk-test-key"), \
         patch.object(voice_service, "transcribe", return_value=ASRResult(
             ok=False, text="", message="MiMo ASR 请求超时"
         )):
        resp = client.post("/api/voice/asr", files={"file": ("rec.webm", b"audio-bytes", "audio/webm")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "超时" in data["message"]
