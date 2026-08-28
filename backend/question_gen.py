"""
问题生成模块：v2.2 支持 6 阶段面试的不同类型问题。
v2.4: 新增传统 5 轮次 Prompt 配置。
v2.6: 支持按弱项维度定向生成针对性追加题。
v3.1: 市场数据注入——参考 market.db 真实岗位数据校验问题的"市场合理性"。
"""

import asyncio
import json
import logging

from .output_sanitizer import OUTPUT_CONSTRAINTS, sanitize_spoken_text
from .resume_anchors import build_anchors_block, merge_anchor_sources

logger = logging.getLogger(__name__)

# ===== v6.2: 简历前置追问点（借鉴 GrillMind 的 deepDivePoints / vaguePoints） =====
# 由 resume_parser 在解析阶段产出，出题时注入，让追问有据可依而不是临场泛问。
_RESUME_POINTS_LIMIT = 5   # 每类最多注入的条数（防 prompt 膨胀）


def _fmt_points(items) -> str:
    if not items:
        return ""
    return "\n".join(f"- {str(x).strip()}" for x in items[:_RESUME_POINTS_LIMIT] if str(x).strip())


def build_resume_points_block(resume_points: dict) -> str:
    """把简历追问点格式化为出题 prompt 片段；无有效内容返回空串（不注入）。

    v6.3: 追加【锚点类型与追问方向】段。
    原有 deep/vague 二分只能定位"哪里值得问"，五分类才回答"该往哪个方向问"——
    同样是"写了但没展开"，技术选型该问"为什么选它"，量化数据该问"怎么测的"，
    方向不同则追问的质量差异极大。
    """
    if not isinstance(resume_points, dict):
        return ""
    deep = _fmt_points(resume_points.get("deep_dive_points") or [])
    vague = _fmt_points(resume_points.get("vague_points") or [])
    # v6.3: anchors 缺失时按关键词规则对既有追问点兜底分类（向后兼容旧数据）
    anchors_block = build_anchors_block(
        merge_anchor_sources(
            resume_points.get("anchors"),
            (resume_points.get("deep_dive_points") or [])
            + (resume_points.get("vague_points") or []),
        )
    )
    if not deep and not vague and not anchors_block:
        return ""
    parts = ["\n\n【简历前置追问点】以下线索由简历解析阶段预先提取，请优先据此提问/追问，"]
    parts.append("而不是泛泛而问：")
    if deep:
        parts.append(f"\n★ 值得深挖的点（候选人写了但细节不足，需要考其真伪与深度）：\n{deep}")
    if vague:
        parts.append(f"\n★ 可疑/模糊的点（表述含糊、缺时间或量化，需要核实）：\n{vague}")
    if anchors_block:
        parts.append(anchors_block)
    parts.append(
        "\n注意：发问要像真实面试官的自然追问，不要出现'简历提示'之类的元信息，"
        "也不要替候选人说出答案；仅在候选人确实谈及该内容时才追。"
    )
    return "".join(parts)


# ===== v2.6: 弱项维度 → 定向出题策略 =====

FOCUS_DIMENSION_PROMPTS = {
    "star_completeness": (
        "候选人在【STAR 完整度】上表现薄弱：回答缺少情境、任务、行动或结果中的关键环节，"
        "常常只讲做了什么，不讲背景与最终结果。\n"
        "请生成能**倒逼候选人补齐 STAR 结构**的问题，例如要求其完整复述一段经历的"
        "起因、他本人承担的具体职责、采取的关键行动、以及最终落地的结果。"
        "问题中要明确要求交代背景和结果。"
    ),
    "quantification": (
        "候选人在【量化程度】上表现薄弱：陈述成果时缺少数据支撑，多为'提升了很多'这类模糊表述。\n"
        "请生成能**逼出具体数字**的问题，例如追问性能提升的具体比例、耗时从多少降到多少、"
        "覆盖用户量级、成本节约金额、以及这些数字是如何测量得到的。"
    ),
    "logic_coherence": (
        "候选人在【逻辑连贯性】上表现薄弱：因果链条断裂，要点之间跳跃，难以自圆其说。\n"
        "请生成能**检验推理链条**的问题，例如要求其解释某个技术决策的取舍过程、"
        "为什么排除了其他方案、如果前提条件改变结论会怎样。问题应要求候选人分步骤论证。"
    ),
    "job_relevance": (
        "候选人在【岗位相关性】上表现薄弱：回答游离于岗位核心要求之外，未能展示匹配能力。\n"
        "请生成**紧扣岗位 JD 核心要求**的问题，直接指向该岗位最关键的能力项，"
        "要求候选人结合自身经历说明其如何胜任这一岗位的具体职责。"
    ),
    "professional_depth": (
        "候选人在【专业深度】上表现薄弱：对技术/领域知识的理解停留在表层，"
        "知其然而不知其所以然，无法解释背后的原理与权衡。\n"
        "请生成能**深挖技术/领域理解**的问题，例如追问某个方案的底层原理、"
        "与其他方案的对比分析、设计中的关键取舍、遇到的深层技术挑战及其解决思路。"
        "问题应要求候选人展示从原理到实践的系统性思考。"
    ),
}

FOCUS_DIMENSION_NAMES = {
    "star_completeness": "STAR 完整度",
    "quantification": "量化程度",
    "logic_coherence": "逻辑连贯性",
    "job_relevance": "岗位相关性",
    "professional_depth": "专业深度",
}


# ===== v3.1: 市场数据辅助函数 =====

async def _extract_keyword_from_text(text: str) -> str:
    """从文本中提取一个可能匹配 market.db 的关键词"""
    if not text:
        return ""
    try:
        from .market.store import list_keywords
        known = await list_keywords()
        text_lower = text.lower()
        # 按关键词长度降序匹配（优先长关键词）
        for kw in sorted(known, key=lambda x: -len(x)):
            if len(kw) < 2:
                continue
            if kw.lower() in text_lower:
                return kw
    except Exception as e:
        logger.debug(f"提取市场关键词跳过: {e}")
    return ""


async def _build_market_context_block(jd_text: str) -> str:
    """
    从 market.db 查询同类岗位数据，返回一段上下文文本注入出题 Prompt。
    若无市场数据或 market.db 为空，返回空字符串（不影响现有流程）。
    """
    keyword = await _extract_keyword_from_text(jd_text)
    if not keyword:
        return ""

    try:
        from .market.store import get_stats
        stats = await get_stats(keyword=keyword)
        if stats.get("total", 0) == 0:
            return ""
    except Exception as e:
        logger.debug(f"市场数据查询跳过: {e}")
        return ""

    parts = [f"\n\n【市场参考数据】（关键词={keyword}，共 {stats['total']} 条岗位）"]

    # 热门技能
    top_skills = stats.get("top_skills", [])[:10]
    if top_skills:
        skills_text = "、".join(s["skill"] for s in top_skills)
        parts.append(f"- 热门技能要求：{skills_text}")
        parts.append(f"  （以上来自真实招聘数据，请确保题目覆盖这些高频技能）")

    # 招聘公司
    try:
        from .market.store import query_jobs
        jobs = await query_jobs(keyword=keyword, limit=15)
        companies = list(set(j.get("company", "") for j in jobs.get("items", []) if j.get("company")))
        if companies:
            parts.append(f"- 招聘公司类型：{', '.join(companies[:10])}")
    except Exception:
        pass

    # 学历分布
    edu = stats.get("education_distribution", [])
    if edu:
        edu_text = ", ".join(f"{e.get('education', '?')}({e.get('cnt', 0)}条)" for e in edu[:5])
        parts.append(f"- 学历分布：{edu_text}")

    # 薪资范围
    avg = stats.get("avg_salary", {}) or {}
    if avg.get("avg_k") and avg.get("max_k"):
        parts.append(f"- 薪资范围：均 {avg['avg_k']}K，区间 {avg.get('min_k', '?')}-{avg['max_k']}K")

    parts.append("（上述数据仅供出题参考，帮助生成更贴合真实市场的面试题。）")
    return "\n".join(parts)

# ===== v2.2: 6 阶段问题生成 Prompt 配置 =====

ROUND_PROMPTS = {
    0: {
        "name": "破冰环节",
        "focus": (
            "建立轻松的面试氛围。通过简历确认和自我介绍，"
            "了解候选人的职业背景、核心技能定位。"
            "不需要技术深度，重在让候选人放松并展现沟通能力。"
        ),
    },
    1: {
        "name": "技术广度",
        "focus": (
            "技术知识面评估。围绕简历中的技术栈和岗位 JD 要求，"
            "考察候选人对核心技术（语言/框架/工具/方法论）的理解广度。"
            "问题应覆盖多个技术领域，测试知识面的完整性。"
        ),
    },
    2: {
        "name": "技术深度",
        "focus": (
            "技术深度与原理理解。针对候选人的核心技术栈，"
            "深挖底层原理、架构设计、性能优化、安全考量等。"
            "每个问题都需要候选人展示「知其所以然」的能力。"
        ),
    },
    3: {
        "name": "项目拷问",
        "focus": (
            "项目经验真实性与深度验证。围绕简历中的具体项目，"
            "拷问候选人的角色贡献、技术决策、遇到的挑战、"
            "失败教训等。通过 STAR 方法验证项目经验的真实性。"
        ),
    },
    4: {
        "name": "行为面试",
        "focus": (
            "软技能与工作行为模式。考察候选人的团队协作、"
            "冲突处理、时间管理、领导力、抗压能力等。"
            "使用行为面试法（STAR），要求候选人给出具体事例。"
        ),
    },
    5: {
        "name": "反问收尾",
        "focus": (
            "给予候选人提问机会，同时评估其对岗位和公司的理解深度。"
            "可以询问候选人对岗位的期待、职业规划、"
            "以及是否有想了解的问题。以正向收尾结束面试。"
        ),
    },
}

# ===== v2.4: 传统 5 轮次问题生成 Prompt =====

TRADITIONAL_ROUND_PROMPTS = {
    0: {
        "name": "笔试环节",
        "focus": (
            "技术基础知识考察。围绕候选人简历中的技术栈和岗位要求，"
            "生成基础概念题、选择题式简答题或代码设计简述题。"
            "题目偏基础，覆盖面广，验证候选人的基础功是否扎实。"
            "可包含：语言基础、数据结构算法、网络/操作系统基础知识。"
        ),
    },
    1: {
        "name": "技术一面",
        "focus": (
            "技术广度与实际应用能力。考察候选人对主流技术框架、"
            "工具链、开发流程的掌握程度。关注实践经验和工程能力，"
            "而非纯理论背诵。问题应围绕简历中的核心技术栈展开，"
            "涉及 API 设计、中间件使用、性能调优等方面。"
        ),
    },
    2: {
        "name": "技术二面",
        "focus": (
            "技术深度与架构能力。深挖底层原理、系统设计、"
            "分布式架构、高并发处理等高级话题。"
            "故意追问直到候选人触及知识边界，验证其[深度天花板]。"
            "适合使用[为什么这么设计]/[有没有更好的方案]等质疑性追问。"
        ),
    },
    3: {
        "name": "综合面试",
        "focus": (
            "综合素质评估。结合项目经验、软技能、团队协作、"
            "业务理解等多个维度，考察候选人是否适合团队文化。"
            "可以涉及跨团队协作经历、技术决策理由、"
            "以及候选人对行业趋势的思考。"
        ),
    },
    4: {
        "name": "自定义环节",
        "focus": (
            "收尾与个性化互动。根据面试表现，询问候选人"
            "还有哪些未展示的能力，或补充 AI 面试未能覆盖的方面。"
            "可以问职业规划、对岗位的理解和期待，"
            "或给予候选人补充展示的机会。"
        ),
    },
}


async def generate_round_questions(llm_client, resume_text: str, jd_text: str,
                                   round_idx: int, round_name: str, count: int,
                                   mode: str = "simulation",
                                   focus_dimension: str | None = None,
                                   weak_evidence: str = "",
                                   type_mix: dict | None = None,
                                   closing_instruction: str = "",
                                   resume_points: dict | None = None,
                                   avoid_questions: list[str] | None = None,
                                   memory_points: list[dict] | None = None,
                                   jd_gaps: list[str] | None = None) -> list[dict]:
    """
    为指定轮次生成问题。
    不同轮次使用不同的聚焦角度（v2.2 扩展为 6 阶段，v2.4 支持双模式）。

    v2.6 新增：
      focus_dimension — 指定弱项维度，生成定向补强题
      weak_evidence   — 该维度失分的具体证据（诊断评语），让追加题更贴合真实短板

    v2.7 新增：
      type_mix — 题型占比偏好 {knowledge, project, behavior}，0-100 的相对权重

    v3.1 新增：
      市场数据注入 — 查询 market.db 同类岗位的技能/公司信息，让题目更贴近真实招聘市场

    v6.2 新增：
      closing_instruction — 收尾阶段的内部收尾指令（由会话层按轮次计数判定后注入，
      工程强控：最后一轮的题目必须带收束性质，不依赖模型自决是否收尾）
      resume_points — 简历解析阶段产出的追问点 {deep_dive_points, vague_points}，
      让面试官的追问有数据支撑，而非临场泛泛而问

    v6.3 新增：
      avoid_questions — 本次会话已问过的题目文本（由会话层 L3 维护），
      作为【已问题目清单·严禁重复】负向约束注入，服务于两个场景：
        1) 换题（模型决定 next_question 后追加/新起一题）时给出真正的新题；
        2) 兜底重试：模型不听约束又出了重复题时，会话层带上重复题再要一道。
      memory_points — 历史未解决薄弱点（长期记忆闭环），来自 db.list_unresolved_weaknesses()。
        以【历史薄弱点·优先考察】段注入，让每场新面试优先覆盖反复失分的维度，
        对应"练 → 评 → 记 → 再练"闭环里的"记 → 再练"这一段。
        由会话层控制只在首轮注入一次（后续轮次薄弱点不变，重复注入是纯浪费）。

    v6.3 新增：
      jd_gaps — JD 匹配缺口（岗位要求但简历未充分体现的点），由 gap_analyzer 产出。
        注入【JD 匹配缺口 · 优先考察】段，显式声明出题优先级链：
            JD gap 区域（必问）> JD 强匹配区域（验证深度）> 简历锚点（补充探测）
        为什么必须显式声明：不声明时模型会顺着简历走——简历内容在上下文里更"显眼"、
        更容易写出具体问题；而真实面试官手里拿的是 JD，最关心的恰恰是
        "JD 上要求的你到底行不行"。这个偏差靠模型自觉纠不回来，只能工程层强控。
    """

    # v3.1: 市场数据注入（仅非补强题时注入，补强题本身已有定向上下文）
    market_block = ""
    if not focus_dimension:
        try:
            market_block = await _build_market_context_block(jd_text or "")
        except Exception as e:
            logger.debug(f"市场数据注入跳过: {e}")
    # v2.4: 根据面试模式选择 Prompt 集
    prompts = TRADITIONAL_ROUND_PROMPTS if mode == "traditional" else ROUND_PROMPTS
    round_config = prompts.get(round_idx, prompts.get(0, prompts[list(prompts.keys())[0]]))
    focus = round_config["focus"]

    # v2.7: 题型占比偏好注入
    type_mix_block = ""
    if type_mix:
        k = type_mix.get("knowledge", 0)
        p = type_mix.get("project", 0)
        b = type_mix.get("behavior", 0)
        total = k + p + b
        if total > 0:
            type_mix_block = (
                f"\n\n【题型占比偏好】\n"
                f"本次面试的题型偏好分布为：基础知识概念题约 {k * 100 // total}%、"
                f"实际项目经验题约 {p * 100 // total}%、行为/软技能题约 {b * 100 // total}%。\n"
                f"请在保持本轮考察重点的前提下，尽量使题目类型分布接近此偏好。"
            )

    # v2.6: 叠加弱项定向策略
    extra_block = ""
    if focus_dimension and focus_dimension in FOCUS_DIMENSION_PROMPTS:
        dim_name = FOCUS_DIMENSION_NAMES[focus_dimension]
        extra_block = (
            f"\n\n【本题为弱项补强题 · 定向维度：{dim_name}】\n"
            f"{FOCUS_DIMENSION_PROMPTS[focus_dimension]}\n"
        )
        if weak_evidence:
            extra_block += f"\n该候选人在此维度的失分表现：{weak_evidence[:300]}\n"
        extra_block += (
            "\n注意：题目要自然地像面试官继续发问，不要出现'这是补强题'之类的元信息，"
            "也不要直接告诉候选人他哪里不好。"
        )

    # v6.3: JD 匹配缺口优先考察（出题优先级链的第一环）
    # 只取前 5 条：缺口清单过长会挤占 JD/简历正文的上下文预算，反而稀释重点。
    jd_gap_block = ""
    if jd_gaps:
        listed_gaps = "\n".join(
            f"{i + 1}. {str(g).strip()[:120]}"
            for i, g in enumerate(jd_gaps[:5]) if str(g).strip()
        )
        if listed_gaps:
            jd_gap_block = (
                "\n\n【JD 匹配缺口 · 优先考察】\n"
                "以下是目标岗位要求、但候选人简历未充分体现或明显偏弱的点。"
                "真实面试官手里拿着 JD，最关心的就是这些缺口——\n"
                f"{listed_gaps}\n\n"
                "出题优先级（严格遵守，不要颠倒）：\n"
                "1) 优先围绕上述缺口出题或变形出题；\n"
                "2) 缺口已覆盖时，再回到 JD 强匹配区域验证深度；\n"
                "3) 最后才是简历锚点与常规考察。\n"
                "注意：缺口可能对应候选人没有的经历——此时用「假设场景 / 迁移能力」问法"
                "（如「如果让你做 X，你会怎么切入」），不要问不存在的事实细节。"
            )

    # v6.2: 收尾阶段内部指令注入（工程强控，替代"让模型自己决定何时收尾"）
    closing_block = f"\n\n{closing_instruction}" if closing_instruction else ""

    # v6.2: 简历前置追问点注入（仅在非补强题时注入，补强题已有定向上下文）
    resume_points_block = build_resume_points_block(resume_points) if (
        resume_points and not focus_dimension
    ) else ""

    # v6.3: 已问题目负向约束（换题/备选题的底层保证）
    # 只列最近若干条，避免清单过长挤占上下文预算；超长题截断到 120 字。
    avoid_block = ""
    if avoid_questions:
        listed = "\n".join(
            f"{i + 1}. {str(q).strip()[:120]}"
            for i, q in enumerate(avoid_questions[-8:]) if str(q).strip()
        )
        if listed:
            avoid_block = (
                "\n\n【已问题目清单 · 严禁重复】\n"
                "本次面试已经问过以下题目，你生成的题目**不得与其中任何一道重复或高度相似**：\n"
                f"{listed}\n"
                "请换一个考察角度、换一个具体场景或换一个技术点来出题。"
            )

    # v6.3: 历史薄弱点回注入（长期记忆闭环的"记 → 再练"）
    # 只取前 8 条、每条最多带 2 个风险点：清单过长会挤占 JD/简历的上下文预算。
    memory_block = ""
    if memory_points:
        lines = []
        for p in memory_points[:8]:
            dim = str(p.get("dimension", "") or "").strip()
            if not dim:
                continue
            score = p.get("avg_score", 0)
            risks = [str(r) for r in (p.get("risk_points") or [])][:2]
            line = f"- {dim}（历史均分 {score}）"
            if risks:
                line += f"：{'；'.join(risks)}"
            lines.append(line)
        if lines:
            memory_block = (
                "\n\n【历史薄弱点 · 优先考察】\n"
                "该候选人在以往面试中反复暴露以下短板，本场请优先覆盖这些维度；"
                "必须自然融入本轮考察重点，不要生硬点名「这是你的薄弱项」。\n"
                + "\n".join(lines)
            )

    system_prompt = get_question_gen_system_prompt()
    user_prompt = f"""请根据以下信息，生成 {count} 道{round_name}问题。

【候选人简历】
{resume_text[:3000]}

【岗位描述】
{jd_text[:2000] if jd_text else "无"}
{market_block}

【本轮的考察重点】
{focus}{type_mix_block}{jd_gap_block}{extra_block}{resume_points_block}{closing_block}{avoid_block}{memory_block}

要求：
1. 每个问题附上「考察意图」（1 句话即可）
2. 问题应与候选人的实际经验强关联，避免空洞的通用题
3. 难度递进：第 1 题为基础热身，最后 1 题为深度挑战
4. 输出严格 JSON 格式：{{"questions": [{{"index": 0, "question": "...", "intent": "...", "question_type": "knowledge/project/behavior"}}, ...]}}

只输出 JSON，不要任何额外文字。"""

    try:
        # chat_json 是同步阻塞调用，放入线程避免卡住事件循环
        result = await asyncio.to_thread(
            llm_client.chat_json,
            system_prompt,
            user_prompt,
            0.8,
            2048,
            "question",   # v6.2: 任务级模型绑定（出题）
        )
        questions = result.get("questions", []) if isinstance(result, dict) else []
        for q in questions:
            if not isinstance(q, dict):
                continue
            if focus_dimension:
                q["focus_dimension"] = focus_dimension
                q["focus_dimension_name"] = FOCUS_DIMENSION_NAMES.get(focus_dimension, "")
            # v6.2: 输出净化 —— 题目要进 TTS 与前端渲染，Markdown/舞台提示/垫词在此兜底清除
            for key in ("question", "intent"):
                if isinstance(q.get(key), str):
                    q[key] = sanitize_spoken_text(q[key])
        logger.info(f"生成 {round_name} {len(questions)} 道题目"
                    f"{f'（定向维度: {focus_dimension}）' if focus_dimension else ''}")
        return questions
    except Exception as e:
        logger.error(f"生成{round_name}问题失败: {e}")
        return []


async def generate_coach_tip(llm_client, resume_text: str, jd_text: str,
                                round_name: str) -> dict | None:
    """
    v2.7 教练模式：为当前轮次生成知识点讲解引导。
    返回一个伪问题 dict，question_type 为 'coach_tip'，前端特殊渲染。
    """
    system_prompt = get_question_gen_system_prompt()
    user_prompt = f"""你是一位面试教练。本轮是「{round_name}」。

请针对候选人的简历和岗位 JD，生成一段简短的知识点讲解（200 字以内），
帮助候选人理解本轮面试官最看重什么、常见踩坑点有哪些、以及回答框架建议。

【候选人简历】
{resume_text[:2000]}

【岗位描述】
{jd_text[:1500] if jd_text else "无"}

输出严格 JSON 格式：
{{"question": "讲解标题", "intent": "讲解正文", "question_type": "coach_tip"}}

只输出 JSON，不要任何额外文字。"""

    try:
        result = await asyncio.to_thread(
            llm_client.chat_json,
            system_prompt,
            user_prompt,
            0.7,
            1024,
            "question",   # v6.2: 任务级模型绑定（教练引导同属出题）
        )
        if isinstance(result, dict) and result.get("question"):
            result["question_type"] = "coach_tip"
            result["index"] = -2
            return result
    except Exception as e:
        logger.error(f"生成教练引导失败: {e}")
    return None


async def generate_questions(llm_client, resume_text: str, jd_text: str) -> dict:
    """
    兼容 v1 的单次生成接口。自动提取 JD 关键词 + 生成 8 道题。
    v3.1: 注入市场参考数据。
    """
    market_block = ""
    try:
        market_block = await _build_market_context_block(jd_text or "")
    except Exception as e:
        logger.debug(f"市场数据注入跳过: {e}")

    system_prompt = get_question_gen_system_prompt()
    user_prompt = f"""请根据以下信息，生成 8 道覆盖面广的面试问题。

【候选人简历】
{resume_text[:3000]}

【岗位描述】
{jd_text[:2000] if jd_text else "无"}
{market_block}

要求：
1. 覆盖：技术基础（2 题）、项目深挖（2 题）、系统设计（1 题）、行为面试（2 题）、综合/文化（1 题）
2. 每个问题附上「考察意图」（1 句话）
3. 难度递进
4. 输出严格 JSON：{{"jd_keywords": ["关键词1", ...], "questions": [{{"index": 0, "question": "...", "intent": "..."}}, ...]}}

只输出 JSON。"""

    try:
        result = await asyncio.to_thread(
            llm_client.chat_json,
            system_prompt,
            user_prompt,
            0.8,
            3072,
            "question",   # v6.2: 任务级模型绑定（出题）
        )
        return result if isinstance(result, dict) else {"jd_keywords": [], "questions": []}
    except Exception as e:
        logger.error(f"生成问题失败: {e}")
        return {"jd_keywords": [], "questions": []}


def get_question_gen_system_prompt() -> str:
    # v6.0: 补充出题硬约束（对标 career-copilot interview.system 的工程化 Prompt）：
    # 只出题不替答 / 题型枚举 / 难度递进 / 整场轮次感。
    return """你是一位资深技术面试官，有 10 年以上的面试经验。
你的任务是为特定候选人生成高质量的面试问题。

原则：
1. 问题必须紧密结合候选人的实际经历，不得生成泛泛的通用题
2. 问题的语气、深度应与岗位 JD 相匹配
3. 每个问题都应该能挖掘出候选人的真实能力水平
4. 避免生成"参考答案已隐含其中"的提示性问题
5. 输出必须是合法的 JSON 格式
6. 你只负责出题，绝不替候选人回答，也不要在题目里暗示答案
7. question_type 只能取枚举值：knowledge（知识概念）/ project（项目经验）/ behavior（行为软技能），不要自创其它取值
8. 难度递进：一轮内第 1 题为基础热身（easy），中间逐题加深（mid），最后一题考察深度上限（hard）
9. 整场面试共 5-8 轮（由后端轮次配置控制），单轮内各题相互独立，不要把一道大题拆成多道小题

""" + OUTPUT_CONSTRAINTS
