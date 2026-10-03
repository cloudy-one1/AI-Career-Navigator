"""
Pydantic 数据模型：v2 扩展，支持多轮面试 + WebSocket 流式诊断。
v2.1: 新增 AI 后端管理模型。
v2.2: 新增题库管理模型。
v2.4: 新增面试模式 + 面试官切换模型。
v2.5: 新增诊断反馈模型 + 岗位画像研究模型。
v8.21: 删除 18 个从未接线的"文档型"模型（其中 DimensionScore.score 的 int 约束
与诊断引擎实际 float 输出已漂移，接回路由即 ValidationError）。
防回潮门禁见 tests/test_schemas_wiring.py：新模型必须被接线才能进本文件。
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ========== v5.0: 面试模式 / 阶段枚举 ==========

class InterviewMode(str, Enum):
    """面试模式（对标 agent-interview-coach 的多模式协议）"""
    SIMULATION = "simulation"        # 拟真模式（6 阶段标准面试官）
    TRADITIONAL = "traditional"      # 传统模式（5 轮次）
    COACH = "coach"                  # 教练模式（先补基础再追问，不输出分数）
    HARDCORE = "hardcore"            # 拷打模式（高压追问，抓名词堆砌/过度包装/真实性漏洞）
    INTERVIEW_ONLY = "interview_only"  # 只面试模式（只问不解析，≤一句反馈+一个追问）


class InterviewStage(str, Enum):
    """面试阶段（对标 agent-interview-coach 的 4 阶段协议）"""
    PHONE_SCREEN = "phone_screen"    # 电话筛选面
    TECH_ROUND_1 = "tech_round_1"    # 技术一面
    TECH_ROUND_2 = "tech_round_2"    # 技术二面/主管面
    HR = "hr"                        # HR 面


# ========== 请求模型 ==========

class SessionCreateRequest(BaseModel):
    resume_text: str = Field(default="", description="简历文本")
    jd_text: str = Field(default="", description="岗位描述")
    style: str = Field(default="friendly", description="面试官风格: friendly/strict/pressure/...")
    mode: InterviewMode = Field(default=InterviewMode.SIMULATION, description="面试模式: simulation/traditional/coach/hardcore/interview_only")
    stage: InterviewStage = Field(default=InterviewStage.PHONE_SCREEN, description="面试阶段（v5.0 多阶段协议）")
    include_self_intro: bool = Field(default=False, description="是否包含自我介绍环节")
    question_type_mix: dict = Field(default={}, description="题型占比偏好: {knowledge: N, project: N, behavior: N}，0-100")
    # v6.5: 目标公司风格（company_profiles 注册名；空 = 按 JD 关键词自动匹配，"none" = 明确不启用）
    company_profile: str | None = Field(default=None, description="目标公司风格: bytedance/tencent/alibaba/none/None(自动匹配)")
    # v7.0: 关联简历库/岗位库。传入时由后端从库中取文本填充；不传则保持
    # "直接传 resume_text / jd_text" 的旧行为（向后兼容，前端不必改造）。
    resume_id: str | None = Field(default=None, description="简历库 id（优先于 resume_text）")
    position_id: str | None = Field(default=None, description="岗位库 id（优先于 jd_text）")


# ========== v7.0: 简历库 / 岗位库 ==========

class ResumeCreateRequest(BaseModel):
    title: str = Field(..., description="显示名，默认可用文件名")
    raw_text: str = Field(..., description="简历文本")
    filename: str | None = None
    parsed_json: str | None = None


class ResumeUpdateRequest(BaseModel):
    title: str | None = None
    parsed_json: str | None = None


class PositionCreateRequest(BaseModel):
    title: str = Field(..., description="岗位名称")
    jd_text: str = Field(..., description="岗位 JD 原文")
    department: str | None = None


class PositionUpdateRequest(BaseModel):
    title: str | None = None
    jd_text: str | None = None
    department: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    message: str
    mode: str = "simulation"
    rounds: list[dict] = []
    research: dict | None = None  # v2.5: 岗位画像研究结果
    company_profile: str | None = None  # v6.5: 实际生效的目标公司显示名（未启用为 None）


# ========== v5.0: 会话内模式切换 ==========

class ModeSwitchRequest(BaseModel):
    """v5.0: 会话进行中切换面试模式"""
    mode: InterviewMode = Field(default=InterviewMode.SIMULATION, description="目标模式")
    stage: InterviewStage | None = Field(default=None, description="可选：同步切换阶段")


class ModeSwitchResponse(BaseModel):
    """v5.0: 模式切换结果"""
    session_id: str
    mode: str
    stage: str
    message: str


# ========== v2.5: 诊断反馈 ==========

class DiagnosisFeedbackRequest(BaseModel):
    session_id: str
    round_idx: int
    question_idx: int
    feedback_type: str  # "up" | "down"
    dimension: str = ""  # 可选：针对哪个评分维度
    comment: str = ""    # 可选：用户补充说明
    current_score: float = 0


# ========== v2.1 AI 后端管理模型 ==========

class ProviderInfo(BaseModel):
    id: str
    name: str
    models: list[str] = []
    is_current: bool = False


class ProviderListResponse(BaseModel):
    providers: list[ProviderInfo]
    current: ProviderInfo


class ProviderSwitchRequest(BaseModel):
    provider: str = Field(..., description="后端标识: deepseek/qwen/zhipu/openai/auto（auto=按 AI_PROVIDERS 注册顺序探测第一个 Key 有效的后端，llm_client.switch_provider 实际支持）")


# ========== v2.2 题库管理模型 ==========

class CreateQuestionRequest(BaseModel):
    question_text: str
    round_type: str = ""
    intent: str = ""
    tags: list[str] = []
    difficulty: int = 3


class UpdateQuestionRequest(BaseModel):
    question_text: Optional[str] = None
    round_type: Optional[str] = None
    intent: Optional[str] = None
    tags: Optional[list[str]] = None
    difficulty: Optional[int] = None
    is_favorited: Optional[bool] = None


# ========== v3.1: Gap 分析 ==========

class GapDimensionItem(BaseModel):
    key: str
    name: str
    weight: float
    score: int
    evidence: str
    gap: str
    suggestion: str


class GapAnalysisRequest(BaseModel):
    resume_text: str = Field(..., description="简历文本")
    jd_text: str = Field(default="", description="岗位描述文本")
    keyword: str = Field(default="", description="搜索关键词（市场数据，可选）")


class MarketReference(BaseModel):
    """v3.1: Gap 分析的市场基准参照"""
    keyword: str
    total_samples: int
    avg_salary_k: float | None = None
    salary_range: str = ""
    top_cities: list[str] = []
    education_distribution: list[dict] = []
    top_skills: list[str] = []
    summary: str = ""  # 一句话总结市场位置


class GapAnalysisResponse(BaseModel):
    dimensions: list[GapDimensionItem]
    overall_score: float
    overall_assessment: str
    risk_level: str
    market_source: dict | None = None
    market_reference: MarketReference | None = None  # v3.1 新增


# ===== v3.1: 跨岗位对比 =====

class JDEntry(BaseModel):
    """单个岗位描述条目"""
    title: str = Field(..., min_length=1, description="岗位名称")
    text: str = Field(..., min_length=1, description="岗位描述文本")


class CrossJobCompareRequest(BaseModel):
    resume_text: str = Field(..., min_length=10, description="简历文本")
    # v8.19: max_length=10——此前无上限，gather 对 N 个岗位并行打 N 路 LLM
    # 调用且无并发闸，一次请求可瞬间打出几十路上游调用
    jd_list: list[JDEntry] = Field(..., min_length=2, max_length=10,
                                   description="待对比的岗位列表（2~10 个）")


class JobCompareItem(BaseModel):
    """单个岗位对比结果"""
    title: str
    overall_score: float
    risk_level: str
    key_strengths: list[str] = []       # 本岗位最匹配的维度
    key_gaps: list[str] = []            # 本岗位最薄弱的维度
    dimensions: list[GapDimensionItem] = []
    market_reference: MarketReference | None = None


class CrossJobCompareResponse(BaseModel):
    results: list[JobCompareItem]
    recommendation: str  # 综合推荐（哪个岗位最佳 + 理由）
    ranking: list[str]   # 岗位名称排序（最佳→最差）


# ========== v3.2: 职业规划 ==========

class CareerStage(BaseModel):
    """职业路径中的单个阶段"""
    order: int                          # 阶段序号（从 1 开始）
    title: str                          # 阶段标题，如 "初级前端工程师"
    timeframe: str                      # 时间区间，如 "0-1 年"
    target_level: str = ""              # 该阶段末的目标岗位层级（可空）
    skills_to_acquire: list[str] = []   # 本阶段需补技能
    milestones: list[str] = []          # 里程碑（可验证成果）
    transition_action: str = ""         # 岗位跃迁 / 跳槽动作
    rationale: str = ""                 # 为何此顺序 / 阶段理由


class CareerPlanRequest(BaseModel):
    """职业规划请求：简历 + 目标岗位 + 目标年限"""
    resume_text: str = Field(..., min_length=10, description="简历文本")
    target_role: str = Field(..., min_length=2, description="目标岗位/角色")
    jd_text: str = Field(default="", description="目标岗位 JD（可选，更精准）")
    timeframe_years: int = Field(default=3, ge=1, le=10, description="目标年限（1-10 年）")
    # v8.0: 长期薄弱点上下文。可选字段是为了向后兼容——既有调用方与测试零影响，
    # 由 /api/career-plan 路由从档案服务注入，让规划器第一次"知道用户练过什么"。
    weakness_context: str = Field(default="", description="长期薄弱点上下文（档案服务注入）")
    # v8.1: 支持以简历库档案为规划起点；以及简历技能 vs 市场热门技能的缺口上下文。
    resume_id: str = Field(default="", description="简历库 id（可选，为空则用 resume_text）")
    skill_gap_context: str = Field(default="", description="技能缺口上下文（档案服务注入）")


class CareerPlanResponse(BaseModel):
    """职业规划结果：现状基线 + 多阶段时间轴路径"""
    baseline_gap: GapAnalysisResponse | None = None  # 现状六维快照（路径起点）
    stages: list[CareerStage] = []                   # 时间轴阶段（从近到远）
    summary: str = ""                                # 一句话路径总结
    risk_level: str = ""                             # 路径可行度风险（低/中/高）


# ===== v8.0 求职档案（Job-Seeking Profile）=====

class NextAction(BaseModel):
    """下一步最佳动作（NBA）：规则表产出，确定性、零延迟、可解释。

    为什么不用 LLM 决策：用户每天都要看这一句，延迟与不确定性都不可接受；
    而且"为什么是这一步"必须讲得清，规则表天然可解释。
    """
    action: str = Field(default="", description="展示给用户的动作指令（一句）")
    target_tab: str = Field(default="", description="直达的前端 tab（与 navConfig 的 tab 名一致）")
    reason: str = Field(default="", description="为什么是这一步（可信度来源）")
    urgency: str = Field(default="normal", description="high | normal | low")
    dimension: str = Field(default="", description="针对某薄弱维度时填维度 key，否则为空")


class ProfileResponse(BaseModel):
    """求职档案：四组状态 + 下一步最佳动作。

    档案是"投影层"而非新真相源，任一段都可能因数据缺失而为空——
    degraded 字段如实记录降了哪些段，供前端诚实提示而非假装数据完整。
    """
    identity: dict = Field(default_factory=dict, description="我是谁（简历画像）")
    target: dict = Field(default_factory=dict, description="我要去哪（目标岗位 + 市场基准）")
    level: dict = Field(default_factory=dict, description="我现在什么水平（五维能力 + 环比）")
    gaps: list[dict] = Field(default_factory=list, description="待提升项（排序行动项）")
    # v8.1: 五步主线完成度（steps 的 state 取值 done/current/todo）
    journey: dict = Field(default_factory=dict, description="五步主线完成度")
    next_action: Optional[NextAction] = None
    updated_at: str = ""
    degraded: list[str] = Field(default_factory=list, description="降级的段名（供前端诚实提示）")
    # v8.4: 当前目标岗位 ID（供前端长期记忆页做岗位筛选的默认值）
    target_position_id: str = ""


# ===== v6.3 长期记忆闭环 =====

class WeaknessResolveRequest(BaseModel):
    """标记薄弱点已解决 / 恢复未解决。

    resolved=True 表示"这块短板已补掉"，该点随即退出面试回注入与复习建议，
    形成"练 → 评 → 记 → 再练"的闭环收敛。
    """
    resolved: bool = Field(default=True, description="True=标记已解决，False=恢复未解决")
