"""分析域：Gap 分析（单岗位/按会话）+ 跨岗位对比 + 职业规划。"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from ..config import config
from ..schemas import (
    GapAnalysisRequest, GapAnalysisResponse,
    CrossJobCompareRequest, CrossJobCompareResponse, JobCompareItem,
    CareerPlanRequest, CareerPlanResponse,
)
from .. import gap_analyzer
from .. import career_planner
from .. import profile_service
from ..db import get_resume, get_session, mark_journey_step
from . import state


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/gap-analysis", response_model=GapAnalysisResponse)
@state.limiter.limit(config.RATE_LIMIT_GAP)
async def gap_analysis(req: GapAnalysisRequest, request: Request = None):
    """
    简历-岗位 Gap 分析：六维度透明评分。
      技能(35%) / 城市(15%) / 学历(15%) / 经验(15%) / 薪资(10%) / 可信度(10%)
    当 market.db 中有对应岗位数据时，自动注入市场基准（薪资分位、学历分布等）。
    """
    try:
        result = await gap_analyzer.analyze_gap(
            resume_text=req.resume_text,
            jd_text=req.jd_text,
            keyword=req.keyword or "",
            use_market=True,
            llm_client=state.llm_client,
        )
        return result
    except Exception as e:
        logger.error(f"Gap分析失败: {e}")
        raise HTTPException(500, str(e))


@router.get("/api/gap-analysis/{session_id}")
async def gap_analysis_by_session(session_id: str):
    """
    根据已完成的会话获取 Gap 分析结果。
    优先使用面试时缓存的简历+JD，若无则返回 404。
    """
    session = await get_session(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    resume_text = session.get("resume_text", "")
    jd_text = session.get("jd_text", "")
    if not resume_text and not jd_text:
        raise HTTPException(400, "该会话没有简历或JD，无法生成Gap分析")

    # 从 JD 中提取关键词用于市场查询
    keyword = gap_analyzer._extract_keyword_from_jd(jd_text)

    try:
        result = await gap_analyzer.analyze_gap(
            resume_text=resume_text,
            jd_text=jd_text,
            keyword=keyword,
            use_market=True,
            llm_client=state.llm_client,
        )
        return result
    except Exception as e:
        logger.error(f"Gap分析失败(session={session_id}): {e}")
        raise HTTPException(500, str(e))


def _sorted_gap_dims(gap: dict) -> list:
    """按权重排序的维度列表（权重高的排前面）"""
    dims = gap.get("dimensions", [])
    if not dims:
        return []
    return sorted(dims, key=lambda d: -(d.get("weight", 0) or 0))


def _make_compare_item(title: str, gap: dict) -> JobCompareItem:
    """将 gap 分析结果转换为对比项"""
    dims = _sorted_gap_dims(gap)
    strengths = [f"{d['name']} ({d['score']}/5)" for d in dims if d.get("score", 0) >= 3.5][:3]
    gaps_list = [f"{d['name']} ({d.get('score',0)}/5): {d.get('gap','')}" for d in dims if d.get("score", 0) < 3.5][:3]
    mr = gap.get("market_reference")
    return JobCompareItem(
        title=title,
        overall_score=gap["overall_score"],
        risk_level=gap["risk_level"],
        key_strengths=strengths,
        key_gaps=gaps_list if gaps_list else ["各维度表现均衡"],
        dimensions=[d for d in dims],
        market_reference=mr if mr and mr.get("keyword") else None,
    )


@router.post("/api/cross-job-compare", response_model=CrossJobCompareResponse)
@state.limiter.limit("5/minute")
async def cross_job_compare(req: CrossJobCompareRequest, request: Request = None):
    """
    一份简历 vs 多个岗位：并行评估每个岗位的匹配度，输出排名 + 推荐。
    每个岗位独立调用 Gap 分析（含市场参考），然后汇总对比。
    """

    if len(req.jd_list) < 2:
        raise HTTPException(400, "至少需要 2 个岗位进行对比")

    # 并行分析所有岗位（复用全局单例 llm_client，确保使用已配置后端）
    async def analyze_one(title: str, jd_text: str) -> tuple[str, dict]:
        try:
            result = await gap_analyzer.analyze_gap(
                resume_text=req.resume_text,
                jd_text=jd_text,
                use_market=True,
                llm_client=state.llm_client,
            )
            return title, result
        except Exception as e:
            logger.warning(f"跨岗位对比-{title} 分析失败: {e}")
            return title, gap_analyzer._fallback_gap_result(str(e))

    tasks = [analyze_one(entry.title, entry.text) for entry in req.jd_list]
    raw_results = await asyncio.gather(*tasks)

    # 转换为对比结果列表
    compare_items = [_make_compare_item(title, gap) for title, gap in raw_results]

    # 按总分排序（降序）
    compare_items.sort(key=lambda x: x.overall_score, reverse=True)

    # 生成推荐语
    ranking = [item.title for item in compare_items]
    best = compare_items[0]
    worst = compare_items[-1]
    score_gap = best.overall_score - worst.overall_score

    if score_gap > 1.5:
        recommendation = (
            f"强烈推荐「{best.title}」— 综合匹配度 {best.overall_score}/5，"
            f"远高于「{worst.title}」({worst.overall_score}/5)。"
            f"建议优先投递该岗位方向。"
        )
    elif score_gap > 0.5:
        recommendation = (
            f"推荐「{best.title}」({best.overall_score}/5)，与「{worst.title}」"
            f"({worst.overall_score}/5) 有一定差距。二者的方向不同，建议根据个人偏好权衡。"
        )
    else:
        recommendation = (
            f"各岗位匹配度接近（最高 {best.overall_score}/5，最低 {worst.overall_score}/5）。"
            f"建议综合考虑公司、团队、成长空间等因素做决策。"
        )

    return CrossJobCompareResponse(
        results=compare_items,
        recommendation=recommendation,
        ranking=ranking,
    )


@router.post("/api/career-plan", response_model=CareerPlanResponse)
@state.limiter.limit(config.RATE_LIMIT_CAREER)
async def career_plan(req: CareerPlanRequest, request: Request = None):
    """
    职业规划（v3.2）：简历 + 目标岗位 + 目标年限 → 时间轴多阶段路径。
    以 Gap 分析六维快照为现状基线，调用 LLM 做多步路径推理。
    错误统一转 500，日志不泄露简历原文。

    v8.0：优先注入求职档案里的长期薄弱点（教练闭环）——规划器由此第一次知道
    "用户练过什么、弱在哪里"，第一阶段才能落在真实短板上而非泛泛而谈。
    注入失败一律降级为无上下文（等同 v7.x 既有行为），不阻断规划。
    """
    try:
        # v8.1: 支持以简历库档案为规划起点（前端可不传长文本，只传 resume_id）
        if req.resume_id and len(req.resume_text or "") < 10:
            try:
                row = await get_resume(req.resume_id)
                if row and row.get("raw_text"):
                    req.resume_text = row["raw_text"]
            except Exception as e:
                logger.warning(f"按 resume_id 回填简历失败，按请求中的文本继续: {e}")

        # v8.0 薄弱点 + v8.1 技能缺口：两段上下文都取不到就退回 v7.x 既有行为
        if not req.weakness_context:
            try:
                req.weakness_context = await profile_service.build_weakness_context()
            except Exception as e:
                logger.warning(f"职业规划薄弱点上下文注入失败，按无上下文继续: {e}")
        if not req.skill_gap_context:
            try:
                req.skill_gap_context = await profile_service.build_skill_gap_context()
            except Exception as e:
                logger.warning(f"职业规划技能缺口上下文注入失败，按无上下文继续: {e}")
        result = await career_planner.plan_career(
            req=req,
            llm_client=state.llm_client,
        )
        # v8.1: 规划生成成功 → 五步主线的第⑤步「发展路径」完成。
        # 这是唯一无法从档案推导的一步（档案里没有"是否规划过"的痕迹），
        # 故在此打点；打点失败不影响返回（进度只是少一个勾）。
        try:
            await mark_journey_step("career_path")
            profile_service.invalidate_profile_cache()
        except Exception as e:
            logger.warning(f"旅程步骤打点失败，不影响规划返回: {e}")
        return result
    except Exception as e:
        logger.error(f"职业规划失败: {type(e).__name__}: {e}")
        raise HTTPException(500, "职业规划服务暂时不可用，请稍后重试")
