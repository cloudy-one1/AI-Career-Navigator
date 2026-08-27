"""
全局配置：从 .env 读取环境变量 + 多 AI 后端 + 面试官风格预设 + 轮次配置。
v2.1: 多 AI 后端可切换 + 质量驱动推进参数。
v2.2: 扩展 6 阶段面试流程。
v2.4: 双模式面试（拟真/传统）+ 7种面试官角色 + 自动切换。
"""

import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    # ===== 多 AI 后端配置 =====
    # 当前使用的后端: deepseek / qwen / zhipu / openai
    AI_PROVIDER = os.getenv("AI_PROVIDER", "deepseek")

    AI_PROVIDERS = {
        "deepseek": {
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model_env": "DEEPSEEK_MODEL",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
        "qwen": {
            "name": "通义千问",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key_env": "QWEN_API_KEY",
            "model_env": "QWEN_MODEL",
            "default_model": "qwen-plus",
            "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
        },
        "zhipu": {
            "name": "智谱 GLM",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key_env": "ZHIPU_API_KEY",
            "model_env": "ZHIPU_MODEL",
            "default_model": "glm-4-flash",
            "models": ["glm-4-flash", "glm-4-plus", "glm-4-air"],
        },
        "openai": {
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "model_env": "OPENAI_MODEL",
            "default_model": "gpt-4o-mini",
            "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        },
    }

    # 当前使用的 API 配置（根据 AI_PROVIDER 动态解析）
    @property
    def LLM_BASE_URL(self) -> str:
        provider = self.AI_PROVIDERS.get(self.AI_PROVIDER, self.AI_PROVIDERS["deepseek"])
        return os.getenv("LLM_BASE_URL", provider["base_url"])

    @property
    def LLM_API_KEY(self) -> str:
        provider = self.AI_PROVIDERS.get(self.AI_PROVIDER, self.AI_PROVIDERS["deepseek"])
        env_key = provider.get("api_key_env", "DEEPSEEK_API_KEY")
        return os.getenv("LLM_API_KEY", os.getenv(env_key, ""))

    @property
    def LLM_MODEL(self) -> str:
        provider = self.AI_PROVIDERS.get(self.AI_PROVIDER, self.AI_PROVIDERS["deepseek"])
        env_key = provider.get("model_env", "DEEPSEEK_MODEL")
        return os.getenv("LLM_MODEL", os.getenv(env_key, provider["default_model"]))

    # ===== 兼容旧版（通过 provider 统一读取）=====
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # SQLite 数据库路径
    DB_PATH = os.path.join(BASE_DIR, "data", "interview.db")

    # 上传文件存储
    UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")

    # 静态数据文件
    SKILLS_DATA_PATH = os.path.join(BASE_DIR, "backend", "skills_data.json")

    # ===== v3.1: Web 安全配置 =====
    # CORS: 允许的前端来源（逗号分隔），空字符串 = 允许所有（开发模式）
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000")
    # 请求体大小限制（字节）
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))  # 上传 10MB
    MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", 1 * 1024 * 1024))  # 普通请求 1MB
    # 限流：全局 / IP / 分钟
    RATE_LIMIT_GLOBAL = os.getenv("RATE_LIMIT_GLOBAL", "100/minute")
    RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "10/minute")
    RATE_LIMIT_GAP = os.getenv("RATE_LIMIT_GAP", "20/minute")
    RATE_LIMIT_SESSION = os.getenv("RATE_LIMIT_SESSION", "20/minute")
    RATE_LIMIT_CAREER = os.getenv("RATE_LIMIT_CAREER", "10/minute")  # v3.2 职业规划（路径推理 LLM 调用较重）

    # ===== v3.0: 市场数据层 =====
    MARKET_DB_PATH = os.path.join(BASE_DIR, "data", "market.db")
    JOB_CRAWLER_DB_PATH = os.getenv("JOB_CRAWLER_DB_PATH", "")            # job-crawler data.db 路径（空=导入时指定）

    # ===== v2 追问阈值 =====
    FOLLOW_UP_MIN_LENGTH = 30       # 回答低于此字数触发追问
    FOLLOW_UP_MAX_COUNT = 2         # 单题最多追问次数
    FOLLOW_UP_SCORE_THRESHOLD = 2.5 # 回答质量低于此分数触发追问

    # ===== v2.2 6 阶段面试流程 =====
    # 借鉴 MockMate 的 9 阶段设计，浓缩为 6 阶段：
    # 破冰 → 技术广度 → 技术深度 → 项目拷问 → 行为面 → 反问收尾
    INTERVIEW_ROUNDS = [
        {
            "round_index": 0,
            "name": "破冰环节",
            "question_count": 1,
            "min_questions": 1,
            "advance_threshold": 0,         # 破冰不检查质量，简单过渡
            "max_extra_questions": 0,
        },
        {
            "round_index": 1,
            "name": "技术广度",
            "question_count": 3,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 2,
        },
        {
            "round_index": 2,
            "name": "技术深度",
            "question_count": 3,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 2,
        },
        {
            "round_index": 3,
            "name": "项目拷问",
            "question_count": 2,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 1,
        },
        {
            "round_index": 4,
            "name": "行为面试",
            "question_count": 2,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 1,
        },
        {
            "round_index": 5,
            "name": "反问收尾",
            "question_count": 1,
            "min_questions": 0,             # 反问环节不强制回答
            "advance_threshold": 0,         # 始终通过
            "max_extra_questions": 0,
        },
    ]

    # ===== v2.4: 面试模式 =====
    INTERVIEW_MODES = {
        "simulation": {
            "id": "simulation",
            "name": "拟真模式",
            "description": "模拟真实大厂面试的 6 阶段流程：破冰→技术广度→技术深度→项目拷问→行为面→反问收尾",
            "rounds": None,  # 使用 INTERVIEW_ROUNDS
        },
        "traditional": {
            "id": "traditional",
            "name": "传统模式",
            "description": "5 轮次经典面试：笔试→技术一面→技术二面→综合面试→自定义",
            "rounds": None,  # 使用 TRADITIONAL_ROUNDS
        },
    }

    # v2.4: 传统模式 5 轮次
    TRADITIONAL_ROUNDS = [
        {
            "round_index": 0,
            "name": "笔试环节",
            "question_count": 3,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 1,
            "interviewer_style": "professional",  # 专业型笔试官
        },
        {
            "round_index": 1,
            "name": "技术一面",
            "question_count": 3,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 2,
            "interviewer_style": "strict",  # 严格型技术面试官
        },
        {
            "round_index": 2,
            "name": "技术二面",
            "question_count": 3,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 2,
            "interviewer_style": "skeptical",  # 质疑型深度拷问
        },
        {
            "round_index": 3,
            "name": "综合面试",
            "question_count": 2,
            "min_questions": 2,
            "advance_threshold": 2.5,
            "max_extra_questions": 1,
            "interviewer_style": "curious",  # 好奇型综合评估
        },
        {
            "round_index": 4,
            "name": "自定义环节",
            "question_count": 2,
            "min_questions": 1,
            "advance_threshold": 0,  # 始终通过
            "max_extra_questions": 0,
            "interviewer_style": "friendly",  # 友好型收尾
        },
    ]

    # 面试官风格预设 (v2.4 扩展为 7 种)
    INTERVIEWER_STYLES = {
        "friendly": {
            "id": "friendly",
            "name": "友好型",
            "description": "鼓励式提问，给候选人充分的发挥空间",
            "attack_level": 1,       # 1-5 攻击性
            "interrupt_prob": 0.05,  # 打断概率
            "system_prompt_modifier": (
                "你是一位友好的面试官，语气温和且鼓励。"
                "提问时循序渐进，给候选人充足时间组织思路。"
                "当回答不够好时，用引导的方式提示候选人补充。"
            ),
        },
        "strict": {
            "id": "strict",
            "name": "严格型",
            "description": "严谨追问，深度挖掘技术细节",
            "attack_level": 3,
            "interrupt_prob": 0.15,
            "system_prompt_modifier": (
                "你是一位严格的技术面试官，追求深度和准确度。"
                "对候选人的回答要追根问底，不放过任何模糊表述。"
                "遇到不清晰的回答直接要求澄清，不接受敷衍。"
            ),
        },
        "pressure": {
            "id": "pressure",
            "name": "压力型",
            "description": "高压追问，模拟真实高压面试环境",
            "attack_level": 5,
            "interrupt_prob": 0.30,
            "system_prompt_modifier": (
                "你是一位以施加压力著称的面试官，模拟真实高压面试场景。"
                "频繁打断不完整的回答，挑战候选人的观点，质疑其方案的合理性。"
                "但注意保持专业，不超越专业技术讨论的边界。"
            ),
        },
        "professional": {
            "id": "professional",
            "name": "专业型",
            "description": "客观专业评估，提问精准到位",
            "attack_level": 2,
            "interrupt_prob": 0.10,
            "system_prompt_modifier": (
                "你是一位专业的技术面试官，客观冷静，提问精准到位。"
                "以事实和技术能力为唯一评判标准，不做无谓的闲聊。"
                "每个问题都直指核心能力考察点。"
            ),
        },
        "curious": {
            "id": "curious",
            "name": "好奇型",
            "description": "基于候选人经历深入探索，挖掘隐藏亮点",
            "attack_level": 1,
            "interrupt_prob": 0.08,
            "system_prompt_modifier": (
                "你是一位好奇心强的面试官，对候选人的项目经历充满兴趣。"
                "善于追问每个项目的技术决策背景和思考过程。"
                "通过开放式问题挖掘候选人自己都未必意识到的亮点。"
            ),
        },
        "skeptical": {
            "id": "skeptical",
            "name": "质疑型",
            "description": "怀疑态度拷问，验证候选人能力的真实性",
            "attack_level": 4,
            "interrupt_prob": 0.25,
            "system_prompt_modifier": (
                "你是一位持怀疑态度的面试官，不轻易相信候选人声称的能力。"
                "对每个技术声明都要求拿出证据和细节来支撑。"
                "质疑候选人的方案选择，追问为什么不采用更好的替代方案。"
            ),
        },
        "encouraging": {
            "id": "encouraging",
            "name": "鼓励型",
            "description": "温暖包容的提问风格，帮助候选人放松发挥",
            "attack_level": 1,
            "interrupt_prob": 0.02,
            "system_prompt_modifier": (
                "你是一位温暖包容的面试官，善于创建轻松的面试氛围。"
                "即使候选人答错了也会先肯定再引导，从不打击积极性。"
                "关注候选人的成长潜力和学习态度，而非当前能力差距。"
            ),
        },
    }


config = Config()
