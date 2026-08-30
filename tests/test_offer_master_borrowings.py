"""
v6.1 借鉴 offerMaster 的能力落地测试：
  1. is_end_signal 结束面试退出口令检测（对应 offerMaster rules.py）
  2. 诊断 prompt 的 ASR 转写容错注入 + 追问"引用原话"硬约束
  3. voice_service TTS LRU 缓存（同文本只合成一次）
  4. TTS/STT Provider 协议抽象与工厂回退
  5. 复盘报告 HTML 导出端点（MD→HTML，浏览器打印即 PDF）
"""

import base64
from unittest.mock import patch, MagicMock

import pytest

from backend.config import config
from backend.voice_service import (
    VoiceService, voice_service, get_tts_provider, get_stt_provider,
    TTSProvider, STTProvider,
)
from backend.diagnosis_engine import (
    DIAGNOSTICIAN_SYSTEM_PROMPT,
    VOICE_TRANSCRIPTION_NOTE,
    _build_diagnostician_system,
)
from backend.interview_engine.session import is_end_signal, END_INTERVIEW_KEYWORDS


# ----- 1. 结束面试退出口令 -----

class TestIsEndSignal:
    def test_chinese_keywords(self):
        for kw in ("结束面试", "面试到此结束", "我想结束了，谢谢"):
            assert is_end_signal(kw) is True

    def test_english_keywords_case_insensitive(self):
        assert is_end_signal("OK, let's End Interview now") is True
        assert is_end_signal("STOP INTERVIEW") is True

    def test_normal_answer_not_signal(self):
        assert is_end_signal("这个项目的难点在于高并发下的缓存一致性……") is False
        assert is_end_signal("") is False
        assert is_end_signal(None) is False
        assert is_end_signal("   ") is False

    def test_keyword_registry_nonempty(self):
        assert len(END_INTERVIEW_KEYWORDS) >= 5


# ----- 2. 诊断 prompt：ASR 容错 + 追问引用原话 -----

class TestDiagnosisPromptBorrowings:
    def test_followup_must_quote_answer(self):
        """追问必须显式引用候选人回答原话（借鉴 offerMaster 的 anti-套路约束）"""
        assert "显式引用候选人回答" in DIAGNOSTICIAN_SYSTEM_PROMPT
        assert "套路式追问" in DIAGNOSTICIAN_SYSTEM_PROMPT

    def test_voice_note_injected_when_from_voice(self):
        sys_prompt = _build_diagnostician_system(None, from_voice=True)
        assert "语音转写容错" in sys_prompt
        assert "SaaS" in sys_prompt  # 转写误差示例
        assert VOICE_TRANSCRIPTION_NOTE in sys_prompt

    def test_voice_note_absent_by_default(self):
        sys_prompt = _build_diagnostician_system(None, from_voice=False)
        assert VOICE_TRANSCRIPTION_NOTE not in sys_prompt
        assert "语音转写容错" not in sys_prompt


# ----- 3. TTS LRU 缓存 -----

def _fake_client(status=200, json_payload=None):
    fake_resp = MagicMock()
    fake_resp.status_code = status
    fake_resp.json.return_value = json_payload or {}
    fake_resp.text = "{}"
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.return_value = fake_resp
    return client


class TestTTSCache:
    def test_same_text_synthesizes_once(self):
        """同文本 + 同音色第二次命中缓存，不再发起 HTTP 请求"""
        svc = VoiceService()
        svc.api_key = "sk-test-key"
        svc._tts_cache.clear()
        fake_audio = base64.b64encode(b"FAKE_WAV").decode("ascii")
        client = _fake_client(200, {"choices": [{"message": {"audio": {"data": fake_audio}}}]})
        with patch("backend.voice_service.httpx.Client", return_value=client):
            first = svc.synthesize("你好面试官")
            second = svc.synthesize("你好面试官")
        assert first.used and second.used
        assert client.post.call_count == 1
        assert second.audio_b64 == first.audio_b64

    def test_different_voice_bypasses_cache(self):
        svc = VoiceService()
        svc.api_key = "sk-test-key"
        svc._tts_cache.clear()
        fake_audio = base64.b64encode(b"FAKE_WAV").decode("ascii")
        payload = {"choices": [{"message": {"audio": {"data": fake_audio}}}]}
        client = _fake_client(200, payload)
        with patch("backend.voice_service.httpx.Client", return_value=client):
            svc.synthesize("同一句话", "茉莉")
            svc.synthesize("同一句话", "苏打")
        assert client.post.call_count == 2

    def test_lru_eviction(self):
        svc = VoiceService()
        svc.api_key = "sk-test-key"
        svc._tts_cache.clear()
        fake_audio = base64.b64encode(b"X").decode("ascii")
        client = _fake_client(200, {"choices": [{"message": {"audio": {"data": fake_audio}}}]})
        with patch("backend.voice_service.httpx.Client", return_value=client):
            for i in range(svc.TTS_CACHE_MAX + 5):
                svc.synthesize(f"文本-{i}")
        assert len(svc._tts_cache) <= svc.TTS_CACHE_MAX

    def test_failure_not_cached(self):
        """合成失败不缓存：下次调用仍会重试"""
        svc = VoiceService()
        svc.api_key = "sk-test-key"
        svc._tts_cache.clear()
        client = _fake_client(500, {})
        with patch("backend.voice_service.httpx.Client", return_value=client):
            svc.synthesize("会失败的话")
            assert len(svc._tts_cache) == 0


# ----- 4. Provider 协议与工厂 -----

class TestVoiceProviderFactory:
    def test_default_returns_mimo(self):
        assert get_tts_provider() is voice_service
        assert get_stt_provider() is voice_service

    def test_unknown_provider_falls_back(self):
        assert get_tts_provider("not-exist") is voice_service
        assert get_stt_provider("not-exist") is voice_service

    def test_satisfies_protocol(self):
        """实现类满足运行时协议检查（runtime_checkable）"""
        assert isinstance(voice_service, TTSProvider)
        assert isinstance(voice_service, STTProvider)


# ----- 5. 复盘报告 HTML 导出 -----

class TestReportHtmlExport:
    @pytest.fixture
    def client(self, tmp_path):
        import asyncio
        from backend.config import config as cfg
        import backend.db as db_mod

        cfg.DB_PATH = str(tmp_path / "test_interview.db")
        cfg.MARKET_DB_PATH = str(tmp_path / "test_market.db")
        db_mod._db = None

        from backend.db import init_db
        from backend.market.store import init_market_db

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(init_db())
            loop.run_until_complete(init_market_db())
        finally:
            loop.close()

        from backend.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_export_html_404_for_missing_report(self, client):
        resp = client.get("/api/reports/no-such-session/export.html")
        assert resp.status_code == 404

    def test_export_html_renders_markdown(self, client, tmp_path):
        """已存报告 → HTML 包含渲染后的标题与打印按钮"""
        import asyncio
        import backend.db as db_mod

        report = {
            "overall_avg": 3.8,
            "interview_mode": "拟真模式",
            "rounds": [],
            "dimension_averages": {},
            "scoring": {"weights": {}},
        }
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 先落一条 session，保证 reports.session_id 外键引用有效
            loop.run_until_complete(db_mod.save_session("sess-html"))
            loop.run_until_complete(db_mod.save_report("sess-html", report))
        finally:
            loop.close()

        resp = client.get("/api/reports/sess-html/export.html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "面试复盘报告" in resp.text
        assert "window.print" in resp.text

    def test_config_provider_keys_exist(self):
        assert config.VOICE_TTS_PROVIDER == "mimo"
        assert config.VOICE_STT_PROVIDER == "mimo"
