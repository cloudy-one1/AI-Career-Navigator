"""v4.2: MiMo 云端语音代理（TTS / ASR）。

密钥仅存后端 .env，前端不接触。未配 Key 或失败时返回 used/ok=false，
由前端降级到浏览器原生语音。
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from ..config import config
from ..voice_service import voice_service
from . import state

router = APIRouter()


class VoiceTTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None  # None 时由后端解析为配置默认音色


@router.post("/api/voice/tts")
@state.limiter.limit(config.RATE_LIMIT_VOICE)
async def voice_tts(req: VoiceTTSRequest, request: Request = None):
    """文本 -> mimo-v2.5-tts -> 音频（Base64 WAV）。"""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="文本不能为空")
    if not voice_service.enabled:
        return {"used": False, "message": "未配置 MIMO_API_KEY"}
    usage = await asyncio.to_thread(voice_service.synthesize, req.text, req.voice)
    return {
        "used": usage.used,
        "audio_b64": usage.audio_b64,
        "format": usage.format,
        "message": usage.message,
    }


@router.post("/api/voice/asr")
@state.limiter.limit(config.RATE_LIMIT_VOICE)
async def voice_asr(request: Request, file: UploadFile = File(...)):
    """上传音频 -> mimo-v2.5-asr -> 转写文本。"""
    if not voice_service.enabled:
        return {"ok": False, "text": "", "message": "未配置 MIMO_API_KEY"}
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="音频文件为空")
    # v7.4: 大小硬校验（中间件已按上传额度放行，这里是路由层最后一道防线）。
    # 音频随后会 base64 膨胀 1.33 倍塞进 MiMo 的 JSON 请求体，超限应尽早拒绝，
    # 否则会把一次注定失败的请求完整地转发到上游，白耗超时时间。
    if len(audio_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"录音过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB，请分段录音",
        )
    mime = file.content_type or "audio/webm"
    result = await asyncio.to_thread(
        voice_service.transcribe, audio_bytes, file.filename or "audio.webm", mime
    )
    return {"ok": result.ok, "text": result.text, "message": result.message}
