"""
职业规划模块（v3.2，L3 业务逻辑）。

给定简历 + 目标岗位 + 目标年限，产出时间轴 + 路径推理的多阶段发展路径：
每阶段需补技能、里程碑、岗位跃迁动作、推进顺序理由。

与 Gap 分析的分工：
- gap_analyzer.analyze_gap()   → 横截面快照："你现在配不配这个岗位"（六维匹配分）
- career_planner.plan_career() → 纵向路径推理："从 A 到 B 该按什么顺序补什么"

规划是"生成"任务，诊断/匹配是"分析"任务，二者分属不同模块，
遵守「双 Agent 不可合并」的分离精神（不合并、不省调用）。
"""

import asyncio
import json
import logging
from typing import Optional

from .schemas import CareerPlanRequest, CareerPlanResponse, CareerStage
from .llm_client import LLMClient
from . import gap_analyzer

logger = logging.getLogger(__name__)

# 路径规划的系统提示词（独立 Prompt，与诊断/改写分离）
_PLANNER_SYSTEM_PROMPT = """你是资深职业发展顾问，擅长把候选人的现状与目标岗位之间的差距转化为可执行的多阶段发展路径。
你只负责"路径规划"（生成任务），不负责评分或诊断。
请基于候选人的现状（简历）与目标岗位要求，做多步骤路径推理，输出结构化的 JSON。

输出 JSON 结构：
{
  "stages": [
    {
      "order": 1,
      "title": "阶段标题（如：夯实基础：中级前端工程师）",
      "timeframe": "0-1 年",
      "target_level": "该阶段末的目标岗位层级",
      "skills_to_acquire": ["需补技能1", "需补技能2"],
      "milestones": ["可验证的里程碑1", "里程碑2"],
      "transition_action": "岗位跃迁/跳槽动作（如：跳槽到业务更复杂的中厂）",
      "rationale": "为什么这个阶段排在这里、为什么先补这些技能"
    }
  ],
  "summary": "一句话路径总结",
  "risk_level": "低/中/高"
}

要求：
- stages 必须按时间从近到远排列（order 从 1 开始），数量覆盖目标年限（约每 0.5-1.5 年一个阶段）。
- 每个阶段必须可落地：技能要具体（而非"提升能力"），里程碑要可验证（成果/项目/证书）。
- 阶段之间的先后顺序必须有理由（transition_action + rationale），体现"路径推理"而非罗列。
- 优先从「现状基线」的薄弱维度出发，明确第一阶段补什么。
- 不要编造简历中不存在的事实，所有建议以简历 + 目标岗位为依据。"""


def _build_user_prompt(req: CareerPlanRequest, baseline: dict) -> str:
    """构造规划 Prompt（含现状基线，作为路径起点）。"""
    target_desc = req.target_role
    if req.jd_text:
        target_desc += "\n目标岗位 JD：\n" + req.jd_text

    baseline_block = "（未获得基线，仍可规划，但请标注风险）"
    if baseline:
        dims = []
        for d in baseline.get("dimensions", []):
            dims.append(f"- {d.get('name', d.get('key', '?'))}: {d.get('score', '?')}/5 —— {d.get('evidence', '')}")
        baseline_block = "\n".join(dims)
        risk = baseline.get("risk_level", "?")
        baseline_block += f"\n综合风险等级: {risk}"

    # v8.0: 长期薄弱点（来自历次模拟面试的长期记忆）。
    # 这是"陪跑"闭环的落点——规划不再只看静态简历，而是看用户真实练出来的短板。
    weakness_block = ""
    ctx = getattr(req, "weakness_context", "") or ""
    if ctx.strip():
        weakness_block = f"""
候选人长期薄弱点（来自历次模拟面试的长期记忆，EMA 累积，越靠前越需优先解决）：
{ctx.strip()}

要求：第一阶段必须落在上述真实短板上，并在 rationale 里说明"为什么先补它"。
不要规划候选人已经掌握的内容。"""

    # v8.1: 技能缺口（简历 vs 目标岗位的市场热门技能）。
    # 与薄弱点的分工：那边是"表达与能力维度"的短板，这边是"硬技能"的缺口。
    skill_block = ""
    skill_ctx = getattr(req, "skill_gap_context", "") or ""
    if skill_ctx.strip():
        skill_block = f"""
技能缺口（简历与目标岗位市场热门技能的比对结果）：
{skill_ctx.strip()}"""

    return f"""候选人简历：
{req.resume_text}

目标：在 {req.timeframe_years} 年内成长为「{target_desc}」。

候选人现状基线（六维匹配评分，来自 Gap 分析）：
{baseline_block}
{weakness_block}
{skill_block}

请基于以上信息，规划一条从现状到目标的时间轴路径。每个阶段的安排要贴合候选人的起点，第一阶段必须针对现状最薄弱的维度。"""


def _parse_stages(raw: dict) -> list[CareerStage]:
    """解析 LLM 返回的阶段列表，容错降级。"""
    stages: list[CareerStage] = []
    for item in raw.get("stages", []) or []:
        if not isinstance(item, dict):
            continue
        # 跳过没有任何有效字段的空项（如 {}）
        if not any(k in item for k in ("order", "title", "timeframe", "target_level")):
            continue
        try:
            stages.append(CareerStage(
                order=int(item.get("order", len(stages) + 1)),
                title=str(item.get("title", "")).strip() or f"阶段 {len(stages) + 1}",
                timeframe=str(item.get("timeframe", "")).strip(),
                target_level=str(item.get("target_level", "")).strip(),
                skills_to_acquire=[str(s).strip() for s in (item.get("skills_to_acquire") or []) if str(s).strip()],
                milestones=[str(m).strip() for m in (item.get("milestones") or []) if str(m).strip()],
                transition_action=str(item.get("transition_action", "")).strip(),
                rationale=str(item.get("rationale", "")).strip(),
            ))
        except Exception as e:
            logger.warning(f"职业规划阶段解析失败，跳过: {e}")
    # 按 order 排序并重排序号
    stages.sort(key=lambda s: s.order)
    for i, s in enumerate(stages, start=1):
        s.order = i
    return stages


def _first_weakness_name(context: str) -> str:
    """从薄弱点上下文里取最前面那条维度名（形如"- 量化程度：长期薄弱度 62…"）。

    LLM 失败走降级模板时，第一阶段也应落在真实短板上——闭环不能只在
    LLM 可用时成立。
    """
    first_line = (context or "").strip().splitlines()
    if not first_line:
        return ""
    head = first_line[0].lstrip("- ").strip()
    return head.split("：")[0].split(":")[0].strip()


def _missing_skills(context: str) -> list[str]:
    """从技能缺口上下文里解析"未体现的技能"清单（供降级模板使用）。"""
    for line in (context or "").splitlines():
        if "未体现的技能" not in line:
            continue
        tail = line.split("：", 1)[-1]
        # 去掉括号内的排序说明，只留技能名
        tail = tail.split("（")[0]
        return [s.strip() for s in tail.split("、") if s.strip()]
    return []


def _fallback_plan(req: CareerPlanRequest, baseline: dict | None) -> CareerPlanResponse:
    """LLM 失败时的降级路径：基于基线的固定三段式建议（诚实标注为启发式）。

    v8.0：有长期薄弱点时优先以它为第一阶段主题（以真实短板为起点）。
    v8.1：技能缺口并入第一阶段的补技能清单——降级模板也要用得上真实数据。
    """
    if getattr(req, "weakness_context", ""):
        first_focus = _first_weakness_name(req.weakness_context) or "岗位相关性"
        first_skills = "针对该维度做专项演练（用模拟面试复测至达标）"
        gap_skills = _missing_skills(getattr(req, "skill_gap_context", ""))
        if gap_skills:
            first_skills = f"补足市场热门技能：{'、'.join(gap_skills[:3])}；" + first_skills
    elif baseline:
        dims = baseline.get("dimensions", [])
        weakest = min(dims, key=lambda d: d.get("score", 5), default=None) if dims else None
        first_focus = weakest.get("name", "岗位相关性") if weakest else "岗位相关性"
        first_skills = weakest.get("suggestion", "") if weakest else ""
    else:
        first_focus = "岗位相关性"
        first_skills = ""

    stages = [
        CareerStage(
            order=1,
            title=f"阶段一：补齐「{first_focus}」差距",
            timeframe="0-1 年",
            target_level=req.target_role + "（入门级）",
            skills_to_acquire=[s for s in [first_skills] if s],
            milestones=["完成目标岗位核心技能的系统学习", "产出 1-2 个可展示的实践项目"],
            transition_action="在现岗或内部转岗中承担更贴近目标岗位的职责",
            rationale="第一阶段针对现状最薄弱维度，先补差距再谈跃迁。",
        ),
        CareerStage(
            order=2,
            title="阶段二：独立胜任目标岗位",
            timeframe="1-2 年",
            target_level=req.target_role,
            skills_to_acquire=["目标岗位核心技能深度实践", "项目全流程参与能力"],
            milestones=["独立负责模块/项目并量化成果", "获得目标岗位的正式 offer"],
            transition_action="跳槽或转岗至目标岗位",
            rationale="在补齐基础上实现岗位跃迁，完成从预备到正式的身份转换。",
        ),
        CareerStage(
            order=3,
            title="阶段三：在目标岗位上沉淀并深化",
            timeframe="2-3 年",
            target_level=req.target_role + "（高级）",
            skills_to_acquire=["复杂问题解决", "跨团队协作与影响力"],
            milestones=["主导关键项目", "沉淀方法论并带教新人"],
            transition_action="视情况向更高层级或专家方向演进",
            rationale="跃迁后沉淀 1-2 年，形成可量化的业绩与影响力。",
        ),
    ]
    return CareerPlanResponse(
        baseline_gap=baseline,
        stages=stages,
        summary=f"以现状为起点，先补「{first_focus}」再实现向「{req.target_role}」的跃迁，随后沉淀深化。（降级方案：LLM 规划失败，本路径为启发式模板）",
        risk_level="中",
    )


async def plan_career(
    req: CareerPlanRequest,
    llm_client: Optional[LLMClient] = None,
) -> CareerPlanResponse:
    """
    职业规划主入口。

    流程：
      1. 调用 gap_analyzer.analyze_gap() 获取现状基线（六维快照）
      2. 将基线注入规划 Prompt，调用 LLM 做多步路径推理
      3. 解析结果；LLM 失败则降级为启发式模板

    参数：
      req:         CareerPlanRequest（简历 + 目标岗位 + 年限）
      llm_client:  全局单例（由 main 注入，保持多后端一致）；为空则跳过 LLM 走降级
    """
    # 1. 现状基线（横截面）
    baseline: dict | None = None
    try:
        baseline = await gap_analyzer.analyze_gap(
            resume_text=req.resume_text,
            jd_text=req.jd_text or req.target_role,
            use_market=True,
            llm_client=llm_client,
        )
    except Exception as e:
        logger.warning(f"职业规划基线获取失败，继续规划: {e}")

    # 2. LLM 路径推理（同步 chat_json 经 asyncio.to_thread，避免阻塞事件循环）
    if llm_client is not None:
        try:
            user_prompt = _build_user_prompt(req, baseline)
            raw = await asyncio.to_thread(
                llm_client.chat_json,
                _PLANNER_SYSTEM_PROMPT,
                user_prompt,
                0.4,
                4096,
                "career",   # v6.2: 任务级模型绑定（离线重推理，允许用强模型）
            )
            if raw and not raw.get("error"):
                stages = _parse_stages(raw)
                if stages:
                    return CareerPlanResponse(
                        baseline_gap=baseline,
                        stages=stages,
                        summary=str(raw.get("summary", "")).strip(),
                        risk_level=str(raw.get("risk_level", "中")).strip() or "中",
                    )
                logger.warning("职业规划 LLM 返回空阶段列表，走降级")
        except Exception as e:
            logger.exception(f"职业规划 LLM 调用失败，走降级: {e}")

    # 3. 降级路径
    return _fallback_plan(req, baseline)
