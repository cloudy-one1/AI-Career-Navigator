"""
问题生成模块：v2.2 支持 6 阶段面试的不同类型问题。
v2.4: 新增传统 5 轮次 Prompt 配置。
v2.6: 支持按弱项维度定向生成针对性追加题。
v3.1: 市场数据注入——参考 market.db 真实岗位数据校验问题的"市场合理性"。
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

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
                                   type_mix: dict | None = None) -> list[dict]:
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

    system_prompt = get_question_gen_system_prompt()
    user_prompt = f"""请根据以下信息，生成 {count} 道{round_name}问题。

【候选人简历】
{resume_text[:3000]}

【岗位描述】
{jd_text[:2000] if jd_text else "无"}
{market_block}

【本轮的考察重点】
{focus}{type_mix_block}{extra_block}

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
        )
        questions = result.get("questions", []) if isinstance(result, dict) else []
        if focus_dimension:
            for q in questions:
                q["focus_dimension"] = focus_dimension
                q["focus_dimension_name"] = FOCUS_DIMENSION_NAMES.get(focus_dimension, "")
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
9. 整场面试共 5-8 轮（由后端轮次配置控制），单轮内各题相互独立，不要把一道大题拆成多道小题"""
