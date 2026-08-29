"""
薄弱点记忆：EMA 衰减 + 30 天过期淘汰 + 中性区间不动（v6.5）。

借鉴来源：interviewerAgent `internal/memory/service.go` 的 `updateWeakness`。
对方的设计：
    score < 60（0-100 制）→ 记录/加重：EMA α=0.4，occurrence+1，续期 30 天
    score > 85            → 减轻：occurrence-1，归零则删除，否则 weakness *= 0.7
    60~85                → 中性区，完全不动

本项目的三点改造（为什么不照抄）：
1. **评分制不同**：我们诊断输出的是五维 1-5 分，对方是 0-100。因此先把 1-5 分
   映射为"薄弱度"（分越低越薄弱），阈值换算为 **<3.0 加重 / >4.5 减轻 / 3.0~4.5 中性**。
2. **岗位权重**：对方没有权重概念。我们把 JD 维度权重作为薄弱度**放大系数**——
   岗位越看重的维度，同样的失分越要命（`weight/0.2` 夹在 0.5~2.0 倍）。
   这是本项目相对原设计的真正增量，也复用了 v2.6 已有的动态权重。
3. **主键不同**：对方是 (user_id, tag) 复合主键，我们无用户体系，按 dimension 单键。

中性区"完全不动"是刻意保留的原版语义：**连 last_seen 都不续期**，
即"30 天没有再暴露严重短板，就认为这个短板已经改善，自然淘汰"——
而不是"只要还在练就一直挂着"。衰减靠的是时间，不是练习次数。

分层：L2（纯计算零依赖；持久化经 L1 的 db，L2 可依赖 L1）。
"""

import logging
from datetime import datetime, timedelta

from .db import (
    delete_weakness_memory,
    get_latest_risk_points,
    get_weakness_memory,
    list_active_weakness_memory,
    prune_expired_weakness_memory,
    upsert_weakness_memory,
)

logger = logging.getLogger(__name__)

# ===== 阈值与系数 =====

# 五维评分（1-5）→ 薄弱度判定阈值
WEAKNESS_ADD_BELOW = 3.0      # 低于此分 → 记录/加重薄弱点
WEAKNESS_RELIEF_ABOVE = 4.5   # 高于此分 → 减轻薄弱点
# 3.0 ~ 4.5 为中性区：不动（避免分数在阈值附近抖动导致薄弱点反复增删）

EMA_ALPHA_ADD = 0.4           # 加重时本次观测的权重（新观测权重更大）
EMA_ALPHA_RELIEF = 0.3        # 减轻时的衰减比例（weakness *= 1-0.3）
WEAKNESS_EXPIRE_DAYS = 30     # 加重后续期天数；超过未再加重即淘汰
MAX_WEAKNESS = 100.0
DEFAULT_WEIGHT = 0.2          # 五维均分时的默认权重（1/5）

_DT_FMT = "%Y-%m-%d %H:%M:%S"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def score_to_weakness(score: float, weight: float = DEFAULT_WEIGHT) -> float:
    """五维得分（1-5）→ 薄弱度（0-100，越高越薄弱），并按岗位权重放大。

    映射：薄弱度 = (5 - score) / 4 × 100，再乘权重系数（weight/0.2，夹 0.5~2.0）。
    score=3.0 → 50；score=4.5 → 12.5；score=1.0 且权重 0.4 → 100（封顶）。
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        return 0.0
    s = _clamp(s, 1.0, 5.0)
    base = (5.0 - s) / 4.0 * MAX_WEAKNESS
    try:
        w = float(weight)
    except (TypeError, ValueError):
        w = DEFAULT_WEIGHT
    if w <= 0:
        w = DEFAULT_WEIGHT
    factor = _clamp(w / DEFAULT_WEIGHT, 0.5, 2.0)
    return round(_clamp(base * factor, 0.0, MAX_WEAKNESS), 2)


def update_weakness(state: dict | None, score: float,
                    weight: float = DEFAULT_WEIGHT,
                    now: datetime | None = None) -> dict:
    """按本次得分演进薄弱点状态（纯函数，不碰 IO）。

    返回统一结构：
        {"weakness_score", "occurrence_count", "last_score",
         "last_seen", "expires_at", "updated_at", "removed"}
    removed=True 表示计数已归零，调用方应删除该记录。
    """
    now = now or datetime.now()
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 3.0

    old_score = float((state or {}).get("weakness_score") or 0.0)
    count = int((state or {}).get("occurrence_count") or 0)
    expires_at = (state or {}).get("expires_at")
    last_seen = (state or {}).get("last_seen")

    result = {
        "weakness_score": old_score,
        "occurrence_count": count,
        "last_score": round(s, 2),
        "last_seen": last_seen,
        "expires_at": expires_at,
        "updated_at": now,
        "removed": False,
    }

    if s < WEAKNESS_ADD_BELOW:
        # 加重：EMA，新观测权重 α；计数 +1；续期
        new_w = EMA_ALPHA_ADD * score_to_weakness(s, weight) + (1 - EMA_ALPHA_ADD) * old_score
        result["weakness_score"] = round(_clamp(new_w, 0.0, MAX_WEAKNESS), 2)
        result["occurrence_count"] = count + 1
        result["last_seen"] = now
        result["expires_at"] = now + timedelta(days=WEAKNESS_EXPIRE_DAYS)
    elif s > WEAKNESS_RELIEF_ABOVE and state is not None:
        # 减轻：计数 -1；归零即移除；否则按比例衰减
        remaining = max(0, count - 1)
        result["occurrence_count"] = remaining
        if remaining <= 0:
            result["removed"] = True
            result["weakness_score"] = 0.0
            result["expires_at"] = None
        else:
            result["weakness_score"] = round(old_score * (1 - EMA_ALPHA_RELIEF), 2)
            result["expires_at"] = now + timedelta(days=WEAKNESS_EXPIRE_DAYS)
    # 中性区：完全不动（含不续期），由时间自然淘汰

    return result


def is_expired(state: dict | None, now: datetime | None = None) -> bool:
    """薄弱点是否已过期（expires_at 为空视为未设过期，不过期）。"""
    if not state:
        return False
    exp = state.get("expires_at")
    if not exp:
        return False
    if isinstance(exp, str):
        try:
            exp = datetime.strptime(exp, _DT_FMT)
        except ValueError:
            return False
    return (now or datetime.now()) >= exp


def _to_db_state(dimension: str, st: dict) -> dict:
    """纯函数状态 → db 可写入的行（datetime 转 localtime 文本）。"""
    def _fmt(v):
        if isinstance(v, datetime):
            return v.strftime(_DT_FMT)
        return v
    return {
        "dimension": dimension,
        "weakness_score": float(st.get("weakness_score") or 0.0),
        "occurrence_count": int(st.get("occurrence_count") or 0),
        "last_score": float(st.get("last_score") or 0.0),
        "last_seen": _fmt(st.get("last_seen")),
        "expires_at": _fmt(st.get("expires_at")),
        "updated_at": _fmt(st.get("updated_at")),
    }


# ===== IO 编排（L2 调 L1，供 L4 使用） =====

async def record_observation(dimension: str, score: float,
                             weight: float = DEFAULT_WEIGHT) -> dict | None:
    """记录一次维度得分观测，演进该维度的长期薄弱点状态。

    失败一律降级（记日志返回 None），绝不阻断面试结束流程。
    """
    dim = str(dimension or "").strip()
    if not dim:
        return None
    try:
        state = await get_weakness_memory(dim)
        new_state = update_weakness(state, score, weight)
        if new_state.get("removed"):
            await delete_weakness_memory(dim)
            logger.info(f"[薄弱记忆] {dim} 已连续达标，移除长期薄弱点")
            return new_state
        await upsert_weakness_memory(dim, _to_db_state(dim, new_state))
        return new_state
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[薄弱记忆] {dim} 记录失败，已降级: {e}")
        return None


async def active_memory_points(limit: int = 10) -> list[dict]:
    """按"加权薄弱度"排序的活跃（未过期）长期薄弱点，供首轮出题回注入。

    与 v6.3 的 list_unresolved_weaknesses 的差别：
      - 排序口径从"最近一次均分升序"改为"EMA 薄弱度降序 + 权重放大"；
      - 过期的短板不再回注入（30 天未再严重失分即视为已改善）；
      - 补充 occurrence_count / weakness_score，让出题 prompt 能说清"为什么是它"。
    """
    try:
        rows = await list_active_weakness_memory(limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[薄弱记忆] 读取失败，降级为空: {e}")
        return []
    if not rows:
        return []
    dims = [r.get("dimension", "") for r in rows if r.get("dimension")]
    try:
        risks_map = await get_latest_risk_points(dims)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[薄弱记忆] 风险点读取失败，降级为空: {e}")
        risks_map = {}
    points = []
    for r in rows:
        dim = r.get("dimension", "")
        if not dim:
            continue
        points.append({
            "dimension": dim,
            # 兼容 question_gen 既有字段口径（历史均分）
            "avg_score": r.get("last_score", 0),
            "risk_points": (risks_map.get(dim) or [])[:2],
            # v6.5 新增字段：让 prompt 能区分"反复失分"与"一次失手"
            "weakness_score": r.get("weakness_score", 0),
            "occurrence_count": r.get("occurrence_count", 0),
        })
    return points


async def prune_expired() -> int:
    """清理已过期的长期薄弱点，返回清理条数（失败返回 0）。"""
    try:
        n = await prune_expired_weakness_memory()
        if n:
            logger.info(f"[薄弱记忆] 清理过期薄弱点 {n} 条")
        return n
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[薄弱记忆] 过期清理失败，已降级: {e}")
        return 0
