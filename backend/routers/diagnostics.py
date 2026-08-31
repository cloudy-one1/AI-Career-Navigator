"""诊断洞察域：诊断反馈（👍/👎）+ 薄弱点画像（会话快照 / 全局聚合 / 长期记忆明细）。

注意路由顺序——GET /points 与 /suggestions 必须注册在 GET /{session_id} 之前，
否则 "points" / "suggestions" 会被当成 session_id 吃掉。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from ..db import (
    get_weakness_profile, get_global_weakness_profile,
    list_weakness_points, list_unresolved_weaknesses,
    mark_weakness_resolved, delete_weakness,
    save_feedback as db_save_feedback, get_feedback_stats,
)
from ..schemas import WeaknessResolveRequest, DiagnosisFeedbackRequest
from .. import weakness_memory

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/feedback")
async def submit_feedback(req: DiagnosisFeedbackRequest):
    """提交诊断反馈（👍/👎）"""
    try:
        feedback_id = await db_save_feedback(
            session_id=req.session_id,
            round_idx=req.round_idx,
            question_idx=req.question_idx,
            feedback_type=req.feedback_type,
            dimension=req.dimension,
            comment=req.comment,
            current_score=req.current_score,
        )
        return {"status": "ok", "feedback_id": feedback_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/feedback/{session_id}")
async def get_feedback(session_id: str):
    """获取会话的反馈统计"""
    try:
        stats = await get_feedback_stats(session_id)
        return stats
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/weakness-profile")
async def global_weakness_profile():
    """获取全局薄弱点聚合（各维度历史平均分）"""
    try:
        profile = await get_global_weakness_profile()
        return {"status": "ok", "profile": profile}
    except Exception as e:
        logger.error(f"获取全局薄弱点失败: {e}")
        raise HTTPException(500, str(e))


@router.get("/api/weakness-profile/points")
async def weakness_points(include_resolved: bool = False,
                          limit: int = Query(200, ge=1, le=1000)):
    """薄弱点明细（记忆图谱数据源）。

    include_resolved 默认 False：主视图只呈现未解决的短板；
    limit 兜住上限，避免历史数据多了之后一次性拉爆前端 DOM。
    """
    try:
        points = await list_weakness_points(include_resolved=include_resolved,
                                            limit=limit)
        return {"status": "ok", "count": len(points), "points": points}
    except Exception as e:
        logger.error(f"获取薄弱点明细失败: {e}")
        raise HTTPException(500, str(e))


@router.get("/api/weakness-profile/suggestions")
async def weakness_suggestions(limit: int = Query(5, ge=1, le=20)):
    """复习建议：最该优先补的未解决薄弱点（与面试回注入同一排序口径）。

    v6.5: 与回注入同口径——优先 EMA 薄弱度降序，新表为空时回退 v6.3 的均分升序。
    """
    try:
        suggestions = await weakness_memory.active_memory_points(limit=limit)
        if not suggestions:
            suggestions = await list_unresolved_weaknesses(limit=limit)
        return {"status": "ok", "count": len(suggestions), "suggestions": suggestions}
    except Exception as e:
        logger.error(f"获取复习建议失败: {e}")
        raise HTTPException(500, str(e))


@router.put("/api/weakness-profile/{point_id}/resolve")
async def resolve_weakness(point_id: int, payload: WeaknessResolveRequest):
    """标记薄弱点已解决 / 恢复未解决（闭环的收敛动作）。"""
    try:
        ok = await mark_weakness_resolved(point_id, payload.resolved)
        if not ok:
            raise HTTPException(404, "薄弱点不存在")
        return {"status": "ok", "id": point_id, "resolved": payload.resolved}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新薄弱点状态失败: {e}")
        raise HTTPException(500, str(e))


@router.delete("/api/weakness-profile/{point_id}")
async def remove_weakness(point_id: int):
    """删除单条薄弱点（与"标记已解决"区分：这是物理删除，不可恢复）。"""
    try:
        ok = await delete_weakness(point_id)
        if not ok:
            raise HTTPException(404, "薄弱点不存在")
        return {"status": "ok", "id": point_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除薄弱点失败: {e}")
        raise HTTPException(500, str(e))


@router.get("/api/weakness-profile/{session_id}")
async def session_weakness_profile(session_id: str):
    """获取指定会话的薄弱点快照"""
    try:
        profile = await get_weakness_profile(session_id)
        return {"status": "ok", "session_id": session_id, "profile": profile}
    except Exception as e:
        logger.error(f"获取会话薄弱点失败: {e}")
        raise HTTPException(500, str(e))
