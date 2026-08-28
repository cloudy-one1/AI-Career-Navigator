"""
Pydantic 数据模型：v2 扩展，支持多轮面试 + WebSocket 流式诊断。
v2.1: 新增 AI 后端管理模型。
v2.2: 新增题库管理模型。
v2.4: 新增面试模式 + 面试官切换模型。
v2.5: 新增诊断反馈模型 + 岗位画像研究模型。
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


# ========== 面试官风格 ==========

class InterviewerStyle(BaseModel):
    """面试官风格配置"""
    id: str
    name: str
    description: str
    system_prompt_modifier: str  # 注入到 system prompt 的风格指令


# ========== 面试轮次 ==========

class RoundConfig(BaseModel):
    """轮次配置"""
    round_index: int
    name: str  # 如 "技术面试"、"行为面试"、"综合面试"
    question_count: int = 3
    target_duration_min: int = 15
    advance_threshold: float = 3.0  # 该轮平均分达此值才能推进


# ========== 请求模型 ==========

class GenerateQuestionsRequest(BaseModel):
    resume_text: str = Field(..., description="简历文本")
    jd_text: str = Field(default="", description="岗位描述文本")


class DiagnoseRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    question_index: int = Field(..., description="当前题目索引")
    question_text: str = Field(..., description="题目内容")
    user_answer: str = Field(..., description="用户回答")
    resume_text: str = Field(default="", description="简历文本")
    jd_text: str = Field(default="", description="岗位描述")


class SessionCreateRequest(BaseModel):
    resume_text: str = Field(default="", description="简历文本")
    jd_text: str = Field(default="", description="岗位描述")
    style: str = Field(default="friendly", description="面试官风格: friendly/strict/pressure/...")
    mode: InterviewMode = Field(default=InterviewMode.SIMULATION, description="面试模式: simulation/traditional/coach/hardcore/interview_only")
    stage: InterviewStage = Field(default=InterviewStage.PHONE_SCREEN, description="面试阶段（v5.0 多阶段协议）")
    include_self_intro: bool = Field(default=False, description="是否包含自我介绍环节")
    question_type_mix: dict = Field(default={}, description="题型占比偏好: {knowledge: N, project: N, behavior: N}，0-100")


class WeaknessProfileItem(BaseModel):
    dimension: str
    avg_score: float
    weight: float
    risk_points: list[str] = []


class SessionCreateResponse(BaseModel):
    session_id: str
    message: str
    mode: str = "simulation"
    rounds: list[dict] = []
    research: dict | None = None  # v2.5: 岗位画像研究结果


# ========== 响应模型 ==========

class QuestionItem(BaseModel):
    index: int
    question: str


class GenerateQuestionsResponse(BaseModel):
    session_id: str
    jd_keywords: list[str]
    questions: list[QuestionItem]


class DimensionScore(BaseModel):
    score: int = Field(..., ge=1, le=5)
    comment: str = Field(..., description="诊断评语")


class DiagnosisResult(BaseModel):
    star_completeness: DimensionScore
    quantification: DimensionScore
    logic_coherence: DimensionScore
    job_relevance: DimensionScore
    professional_depth: DimensionScore  # v5.0: 专业深度维度（与诊断引擎五维对齐）
    overall_score: float = Field(..., description="综合评分")
    overall_comment: str = Field(..., description="综合评语")
    weakness_tags: list[str] = Field(default=[], description="v5.0: 本轮薄弱点标签（供跨轮累计）")


class DiagnoseResponse(BaseModel):
    session_id: str
    question_index: int
    round_index: int = 0
    diagnosis: DiagnosisResult
    rewrite_suggestion: str = Field(..., description="改写示范")
    needs_follow_up: bool = False
    follow_up_question: str = ""


class HistoryItem(BaseModel):
    question_index: int
    round_index: int
    question_text: str
    user_answer: str
    diagnosis: dict
    rewrite_suggestion: str
    created_at: str


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


# ========== 多轮面试模型 ==========

class RoundSummary(BaseModel):
    """单轮面试总结"""
    round_index: int
    round_name: str
    questions_count: int
    answers_count: int
    avg_score: float
    dimensions_avg: dict  # {star_completeness: 3.5, ...}


class ComprehensiveReport(BaseModel):
    """综合面试报告"""
    session_id: str
    interviewer_style: str
    rounds: list[RoundSummary]
    overall_avg: float
    dimension_trends: list[dict]  # 各维度逐轮趋势数据
    strengths: list[str]
    weaknesses: list[str]
    suggestions: str  # 整体提升建议


# ========== v2.5: 诊断反馈 ==========

class DiagnosisFeedbackRequest(BaseModel):
    session_id: str
    round_idx: int
    question_idx: int
    feedback_type: str  # "up" | "down"
    dimension: str = ""  # 可选：针对哪个评分维度
    comment: str = ""    # 可选：用户补充说明
    current_score: float = 0


class FeedbackStatsResponse(BaseModel):
    up: int = 0
    down: int = 0
    total: int = 0


# ========== WebSocket 消息模型 ==========

class WSMessage(BaseModel):
    type: str
    data: dict = {}


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
    provider: str = Field(..., description="后端标识: deepseek/qwen/zhipu/openai")


class ReportData(BaseModel):
    session_id: str
    interviewer_style: str
    total_rounds: int
    rounds: list[dict]
    overall_avg: float
    dimension_trends: list[dict]
    strengths: list[str]
    weaknesses: list[str]
    suggestions: str


# ========== v2.2 题库管理模型 ==========

class QuestionBankItem(BaseModel):
    id: int
    round_type: str = ""
    question_text: str
    intent: str = ""
    tags: list[str] = []
    difficulty: int = 3
    source: str = "manual"
    is_favorited: bool = False
    usage_count: int = 0
    created_at: str = ""


class QuestionBankListResponse(BaseModel):
    questions: list[QuestionBankItem]
    total: int
    round_types: list[str]


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
    jd_list: list[JDEntry] = Field(..., min_length=2, description="待对比的岗位列表（至少2个）")


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


class CareerPlanResponse(BaseModel):
    """职业规划结果：现状基线 + 多阶段时间轴路径"""
    baseline_gap: GapAnalysisResponse | None = None  # 现状六维快照（路径起点）
    stages: list[CareerStage] = []                   # 时间轴阶段（从近到远）
    summary: str = ""                                # 一句话路径总结
    risk_level: str = ""                             # 路径可行度风险（低/中/高）
