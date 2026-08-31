"""系统域：健康检查 + AI 后端管理（列表/切换/权重预热）。"""
import hashlib
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from ..config import config
from ..db import list_sessions, lookup_jd_weights
from ..llm_client import LLMClient, _api_key_issue
from ..diagnosis_engine import DiagnosisEngine
from ..dimension_weights import analyze_jd_weights
from ..schemas import ProviderSwitchRequest, ProviderListResponse, ProviderInfo
from . import state

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.1", "provider": config.AI_PROVIDER}


@router.get("/api/providers", response_model=ProviderListResponse)
async def list_providers():
    providers = []
    for k, v in config.AI_PROVIDERS.items():
        providers.append(ProviderInfo(
            id=k,
            name=v["name"],
            models=v.get("models", []),
            is_current=(k == config.AI_PROVIDER),
        ))
    current = ProviderInfo(
        id=config.AI_PROVIDER,
        name=config.AI_PROVIDERS[config.AI_PROVIDER]["name"],
        models=config.AI_PROVIDERS[config.AI_PROVIDER].get("models", []),
        is_current=True,
    )
    return ProviderListResponse(providers=providers, current=current)


@router.post("/api/switch-provider")
async def switch_provider(req: ProviderSwitchRequest):
    if req.provider not in config.AI_PROVIDERS:
        raise HTTPException(status_code=400,
                            detail=f"不支持的后端: {req.provider}。可用: {list(config.AI_PROVIDERS.keys())}")

    provider_info = config.AI_PROVIDERS[req.provider]
    api_key_env = provider_info.get("api_key_env", "")
    api_key = os.getenv(api_key_env) or os.getenv("LLM_API_KEY")
    issue = _api_key_issue(api_key or "")
    if issue:
        raise HTTPException(status_code=400,
                            detail=f"{provider_info['name']} {issue}，请设置 {api_key_env} 环境变量")

    # v7.2.2: 单例收敛到 state 模块 —— 重赋值必须走属性赋值，任何路由读到的
    # 都是最新实例（拆分前靠 main.py 的 global 声明保证，跨模块后 global 失效）。
    async with state.provider_lock:
        config.AI_PROVIDER = req.provider
        state.llm_client = LLMClient(provider=req.provider)
        state.diagnosis_engine = DiagnosisEngine(llm_client=state.llm_client)
    logger.info(f"切换到后端: {req.provider}")
    return {"message": f"已切换到 {provider_info['name']}", "provider": req.provider}


@router.post("/api/warmup")
@state.limiter.limit("1/minute")
async def warmup(request: Request):
    """
    预热：预计算所有已知 JD 的权重缓存。
    遍历历史会话中的唯一 JD 文本，对未缓存的调用 LLM 分析并写入缓存。
    返回 {precomputed, skipped} 计数。
    """
    try:
        sessions_data = await list_sessions()
        sessions = sessions_data.get("sessions", []) if isinstance(sessions_data, dict) else []
    except Exception:
        sessions = []

    if not sessions:
        return {"message": "没有历史会话可预热", "precomputed": 0, "skipped": 0, "total_jds": 0}

    # 收集唯一 JD 文本
    seen_hashes = set()
    unique_jds: list[str] = []
    for s in sessions:
        jd = (s.get("jd_text") or "").strip()
        if jd and len(jd) >= 8:
            jd_normalized = jd[:2000]
            h = hashlib.sha256(jd_normalized.encode("utf-8")).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_jds.append(jd_normalized)

    if not unique_jds:
        return {"message": "没有足够长的 JD 文本可预热", "precomputed": 0, "skipped": 0, "total_jds": 0}

    precomputed = 0
    skipped = 0

    llm = LLMClient()

    for jd_text in unique_jds:
        jd_hash = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
        # 检查是否已有缓存
        try:
            existing = await lookup_jd_weights(jd_hash)
            if existing:
                skipped += 1
                continue
        except Exception:
            pass

        # 缓存未命中，调用 LLM 并写入缓存
        try:
            await analyze_jd_weights(llm, jd_text)
            precomputed += 1
        except Exception as e:
            logger.warning(f"预热 JD 权重失败: {e}")

    return {
        "message": f"预热完成：{precomputed} 个已计算，{skipped} 个已缓存",
        "precomputed": precomputed,
        "skipped": skipped,
        "total_jds": len(unique_jds),
    }
