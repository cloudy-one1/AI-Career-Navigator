"""系统域：健康检查 + AI 后端管理（列表/切换/权重预热）。"""
import hashlib
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from ..config import config
from ..db import get_quote_verification_stats, list_sessions, lookup_jd_weights
from ..llm_client import LLMClient, _api_key_issue
from ..diagnosis_engine import DiagnosisEngine, quote_stats
from ..dimension_weights import analyze_jd_weights
from ..schemas import ProviderSwitchRequest, ProviderListResponse, ProviderInfo
from . import state

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/health")
async def health():
    # quote_stats：诊断"原话引用"的可核率，两个口径并列——
    #   进程内（v8.10）：本进程自启动起累计，重启归零，反映"当前运行期"；
    #   all_time（v8.14）：从落库报告的 qa_breakdown[].dimension_details 反查的
    #   全历史口径，重启不丢（老报告无该字段，不进分母，见 db.sessions 的聚合函数）。
    # 挂在 health 上是为了让质量指标可被外部读到，而不是只活在日志里。
    try:
        all_time = await get_quote_verification_stats()
    except Exception as e:  # noqa: BLE001
        # 读不出历史可核率不能拖垮 health——按无数据降级并留痕，
        # 否则 DB 故障会被读成"从来没有过引用"。
        logger.warning("全历史引用可核率统计失败，按无数据返回: %s", e)
        all_time = {
            "reports_scanned": 0, "reports_with_quote_data": 0,
            "cited": 0, "verified": 0, "verify_rate": None,
            "parse_errors": 0, "error": str(e),
        }
    return {
        "status": "ok",
        "provider": config.AI_PROVIDER,
        "quote_stats": {**quote_stats(), "all_time": all_time},
    }


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
    except Exception as e:  # noqa: BLE001
        # 读不出历史会话时按"没有会话"返回是错的结论，必须留痕：
        # 否则 DB 故障会被看成"用户还没面过试"。
        logger.warning("预热读取历史会话失败，按无会话处理: %s", e)
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
        except Exception as e:  # noqa: BLE001
            # 查缓存失败会被当成"未命中"，于是白花一次 LLM 调用——要留痕
            logger.warning("查询 JD 权重缓存失败，按未命中处理: %s", e)

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
