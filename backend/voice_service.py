"""
小米 MiMo 云端语音服务（TTS 合成 / ASR 识别）。

v4.2: 前端语音交互升级为"MiMo 云端优先 + 浏览器原生降级"双引擎。
本模块封装 MiMo 官方 API（OpenAI 兼容 chat/completions 协议）的语音能力，
密钥仅存于后端 .env，前端通过 main.py 的 /api/voice/* 代理路由间接调用，避免密钥泄漏。

语音作为"输入/输出替代层"，不参与诊断内核：
  - TTS: 文本 -> mimo-v2.5-tts (chat/completions) -> WAV 字节（Base64 传输）
  - ASR: 音频字节 -> mimo-v2.5-asr (chat/completions, input_audio data URL) -> 转写文本

协议要点（MiMo 官方文档 / ppy-web/tts-mimo 源码核实）：
  - 认证头: api-key: <KEY>（sk- 开头为按量付费集群）
  - 端点:   POST {base}/chat/completions（TTS 与 ASR 统一走该端点，不走 OpenAI /audio/*）
  - TTS 请求体: {model, messages:[{role:user, content:风格提示},{role:assistant, content:文本}], audio:{format:wav, voice}}
  - TTS 响应:   choices[0].message.audio.data（Base64 WAV）
  - ASR 请求体: {model, messages:[{role:user, content:[{type:input_audio, input_audio:{data: data_url}}]}], asr_options:{language}}
  - ASR 响应:   choices[0].message.content（str 或 [{"text": ...}] 列表）

分层归属：L2/L3 业务服务，禁止依赖 L4（main）。见 CHARTER.md 分层契约。
"""

import base64
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import config

logger = logging.getLogger("voice_service")


@dataclass
class TTSUsage:
    """TTS 可用性结果：未配 Key / 请求失败时 used=False。"""
    used: bool
    audio_b64: Optional[str] = None          # 合成音频（Base64，WAV）
    format: str = "wav"
    message: str = ""


@dataclass
class ASRResult:
    """ASR 转写结果：未配 Key / 请求失败时 ok=False。"""
    ok: bool
    text: str = ""
    message: str = ""


class VoiceService:
    """MiMo 语音能力封装（chat/completions 协议，httpx 同步调用在独立线程池执行）。"""

    # 官方预置音色（VALUE 大小写敏感）；mimo_default 在中国集群等同 冰糖
    PRESET_VOICES = frozenset({
        "mimo_default", "冰糖", "茉莉", "苏打", "白桦",
        "Mia", "Chloe", "Milo", "Dean",
    })

    def __init__(self) -> None:
        self.api_key = config.MIMO_API_KEY.strip()
        self.base_url = config.MIMO_BASE_URL.rstrip("/")
        self.tts_model = config.MIMO_TTS_MODEL
        self.asr_model = config.MIMO_ASR_MODEL
        self.timeout = config.MIMO_TIMEOUT
        self.default_voice = (config.MIMO_TTS_VOICE or "冰糖").strip()
        self.asr_language = (config.MIMO_ASR_LANGUAGE or "auto").strip()
        self.tts_style = (config.MIMO_TTS_STYLE or "").strip()

    @property
    def enabled(self) -> bool:
        """是否已配置 MiMo Key（前端据此决定是否优先走云端）。"""
        key = self.api_key.strip()
        return bool(key) and key.startswith(("sk-", "mimo-"))

    def _headers(self) -> dict:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _resolve_voice(self, voice: Optional[str]) -> str:
        """将请求音色名映射到官方预置音色；非法/缺省值回退到配置默认音色。"""
        name = (voice or "").strip()
        if name in self.PRESET_VOICES:
            return name
        if name and name != "default":
            logger.info("未知音色 %r，回退默认音色 %r", name, self.default_voice)
        return self.default_voice

    # ── TTS：文本 -> 音频 ──
    def synthesize(self, text: str, voice: Optional[str] = None) -> TTSUsage:
        """调用 mimo-v2.5-tts 合成语音，返回 Base64 编码的 WAV 音频。"""
        text = (text or "").strip()
        if not text:
            return TTSUsage(used=True, message="文本为空，跳过合成")
        if not self.enabled:
            return TTSUsage(used=False, message="未配置 MIMO_API_KEY")

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.tts_model,
            "messages": [
                {"role": "user", "content": self.tts_style},
                {"role": "assistant", "content": text},
            ],
            "audio": {"format": "wav", "voice": self._resolve_voice(voice)},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self._headers(), json=payload)
            if resp.status_code != 200:
                logger.warning("MiMo TTS 失败 status=%s body=%s", resp.status_code, resp.text[:300])
                return TTSUsage(used=False, message=f"MiMo TTS 请求失败（{resp.status_code}）")
            audio_b64 = self._extract_tts_audio(resp)
            if not audio_b64:
                return TTSUsage(used=False, message="MiMo TTS 响应缺少音频数据")
            return TTSUsage(used=True, audio_b64=audio_b64)
        except httpx.TimeoutException:
            logger.warning("MiMo TTS 超时")
            return TTSUsage(used=False, message="MiMo TTS 请求超时")
        except httpx.HTTPError as exc:
            logger.warning("MiMo TTS 网络错误: %s", exc)
            return TTSUsage(used=False, message="MiMo TTS 网络错误")
        except ValueError:
            logger.warning("MiMo TTS 响应解析失败")
            return TTSUsage(used=False, message="MiMo TTS 响应格式错误")

    def _extract_tts_audio(self, resp: httpx.Response) -> Optional[str]:
        """从 chat/completions 响应中提取音频 Base64（兼容 data URL 前缀）。"""
        try:
            data = resp.json()
            audio_b64 = data["choices"][0]["message"]["audio"]["data"]
        except (KeyError, IndexError, TypeError):
            logger.warning("MiMo TTS 响应结构异常 body=%s", resp.text[:300])
            return None
        if not isinstance(audio_b64, str):
            return None
        # 兼容可能带前缀的形态：data:audio/wav;base64,XXXX
        if audio_b64.startswith("data:audio"):
            audio_b64 = audio_b64.split(";base64,", 1)[-1]
        return audio_b64.strip()

    # ── ASR：音频 -> 转写文本 ──
    def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm",
                   mime: str = "audio/webm") -> ASRResult:
        """调用 mimo-v2.5-asr 转写语音。音频以 data URL 形式放入 messages。"""
        if not audio_bytes:
            return ASRResult(ok=False, message="音频为空")
        if not self.enabled:
            return ASRResult(ok=False, message="未配置 MIMO_API_KEY")

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        data_url = f"data:{mime or 'audio/wav'};base64,{b64}"
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.asr_model,
            "messages": [
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": data_url}},
                ]},
            ],
            "asr_options": {"language": self.asr_language},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self._headers(), json=payload)
            if resp.status_code != 200:
                logger.warning("MiMo ASR 失败 status=%s body=%s", resp.status_code, resp.text[:300])
                return ASRResult(ok=False, message=f"MiMo ASR 请求失败（{resp.status_code}）")
            text = self._extract_asr_text(resp)
            if not text:
                return ASRResult(ok=False, message="MiMo ASR 未识别到有效内容")
            return ASRResult(ok=True, text=text)
        except httpx.TimeoutException:
            logger.warning("MiMo ASR 超时")
            return ASRResult(ok=False, message="MiMo ASR 请求超时")
        except httpx.HTTPError as exc:
            logger.warning("MiMo ASR 网络错误: %s", exc)
            return ASRResult(ok=False, message="MiMo ASR 网络错误")
        except ValueError:
            logger.warning("MiMo ASR 响应解析失败")
            return ASRResult(ok=False, message="MiMo ASR 响应格式错误")

    def _extract_asr_text(self, resp: httpx.Response) -> str:
        """从 chat/completions 响应中提取转写文本（兼容 str 与 [{"text":...}] 两种形态）。"""
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("MiMo ASR 响应结构异常 body=%s", resp.text[:300])
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content if isinstance(p, dict)]
            return "".join(parts).strip()
        return ""


# 单例实例，供 main.py 路由与测试复用
voice_service = VoiceService()
