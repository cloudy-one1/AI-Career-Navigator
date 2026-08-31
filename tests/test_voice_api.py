"""backend/main.py — /api/voice/tts 与 /api/voice/asr 代理路由测试。"""
import base64
from unittest.mock import patch

from backend.config import config
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


# ── v7.4: 录音体积回归 ──
# 前端 maxDurationMs=120000（约 1~2MB 音频），但 /api/voice/asr 此前不在
# RequestSizeLimitMiddleware._UPLOAD_PATHS 白名单里，走的是普通请求的 1MB 额度，
# 长录音必然 413——而 413 返回后前端只 toast 一句"识别失败"，用户录的回答直接丢失。

def test_voice_asr_allows_upload_sized_body(client, monkeypatch):
    """>1MB（普通请求额度）但 <MAX_UPLOAD_BYTES 的录音必须放行。"""
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 2 * 1024 * 1024)
    payload = b"x" * (1200 * 1024)
    with patch.object(voice_service, "api_key", "sk-test-key"), \
         patch.object(voice_service, "transcribe", return_value=ASRResult(
             ok=True, text="识别成功", message=""
         )):
        resp = client.post("/api/voice/asr", files={"file": ("rec.webm", payload, "audio/webm")})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_voice_asr_rejects_oversized_body(client, monkeypatch):
    """超长录音必须尽早 413，不得转发上游白等 MiMo 超时。

    两道防线读同一个 config 值，但拦截点不同（互为补充，不是冗余）：
      - 中间件按 Content-Length 拦 —— 常规上传走这里；
      - 路由层按实际读到的 body 长度拦 —— 分块传输没有 Content-Length 时中间件会跳过，
        此时路由层是唯一防线。
    """
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    with patch.object(voice_service, "api_key", "sk-test-key"), \
         patch.object(voice_service, "transcribe", return_value=ASRResult(
             ok=True, text="不应到达", message=""
         )) as mocked:
        resp = client.post("/api/voice/asr", files={"file": ("rec.webm", b"x" * 4096, "audio/webm")})
    assert resp.status_code == 413
    mocked.assert_not_called()      # 关键：不得把注定失败的请求转发给 MiMo
