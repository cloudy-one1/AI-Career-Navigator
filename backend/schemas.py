"""
Pydantic 数据模型：v2 扩展，支持多轮面试 + WebSocket 流式诊断。
v2.1: 新增 AI 后端管理模型。
v2.2: 新增题库管理模型。
v2.4: 新增面试模式 + 面试官切换模型。
v2.5: 新增诊断反馈模型 + 岗位画像研究模型。
"""

from pydantic import BaseModel, Field
from typing import Optional


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


class SkillMatchRequest(BaseModel):
    keywords: list[str] = Field(..., description="JD 关键词列表")


class SessionCreateRequest(BaseModel):
    resume_text: str = Field(default="", description="简历文本")
    jd_text: str = Field(default="", description="岗位描述")
    style: str = Field(default="friendly", description="面试官风格: friendly/strict/pressure/...")
    mode: str = Field(default="simulation", description="面试模式: simulation(拟真6阶段) / traditional(传统5轮次) / coach(教练模式)")
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
    overall_score: float = Field(..., description="综合评分")
    overall_comment: str = Field(..., description="综合评语")


class DiagnoseResponse(BaseModel):
    session_id: str
    question_index: int
    round_index: int = 0
    diagnosis: DiagnosisResult
    rewrite_suggestion: str = Field(..., description="改写示范")
    needs_follow_up: bool = False
    follow_up_question: str = ""


class SkillMatchResponse(BaseModel):
    keywords: list[str]
    matches: list[dict]


class HistoryItem(BaseModel):
    question_index: int
    round_index: int
    question_text: str
    user_answer: str
    diagnosis: dict
    rewrite_suggestion: str
    created_at: str


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
