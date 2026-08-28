"""
全局配置：从 .env 读取环境变量 + 多 AI 后端 + 面试官风格预设 + 轮次配置。
v2.1: 多 AI 后端可切换 + 质量驱动推进参数。
v2.2: 扩展 6 阶段面试流程。
v2.4: 双模式面试（拟真/传统）+ 7种面试官角色 + 自动切换。
v6.0: Provider 注册表增强 —— AI_PROVIDER=auto 自动探测 + Key 校验下沉到配置层
      （对标 career-copilot 的 PROVIDER_REGISTRY + createProvider 自动探测）。
"""

import json
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def validate_api_key(key: str) -> str | None:
    """校验 API Key 有效性（canonical 实现，llm_client._api_key_issue 为其向后兼容别名）。

    返回 None 表示正常，否则返回问题描述（中文）。
    识别三类无效 Key：空、含非 ASCII 字符（如中文占位符）、占位符模板。
    """
    if not key:
        return "API Key 未配置"
    if any(ord(c) > 127 for c in key):
        return "API Key 含非 ASCII 字符（如中文），请填写纯英文数字的真实 Key"
    if any(t in key for t in ("sk-xxxx", "sk-your-", "key-here", "替换", "your-key")):
        return "API Key 是占位符模板，请填写真实 Key"
    return None


class Config:
    # ===== 多 AI 后端配置 =====
    # 当前使用的后端: deepseek / qwen / zhipu / openai / auto
    # v6.0: "auto" = 按 AI_PROVIDERS 注册顺序自动探测第一个 Key 有效的后端
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
    def provider_key_issue(self, pid: str) -> str | None:
        """校验指定注册后端的 Key 配置状态（无效返回中文问题描述，有效返回 None）。"""
        info = self.AI_PROVIDERS.get(pid)
        if not info:
            return f"未知 provider: {pid}"
        key = os.getenv("LLM_API_KEY", "") or os.getenv(info["api_key_env"], "")
        return validate_api_key(key)

    @property
    def AI_PROVIDER_RESOLVED(self) -> str:
        """v6.0: 解析实际生效的 provider（Provider 注册表自动探测）。

        - 显式合法值（deepseek/qwen/zhipu/openai）→ 原样返回，行为不变；
        - "auto" → 按 AI_PROVIDERS 注册顺序探测第一个 Key 有效的后端；
        - 未知值 → 回退 deepseek 并告警。
        """
        p = (self.AI_PROVIDER or "").strip()
        if p in self.AI_PROVIDERS:
            return p
        if p == "auto":
            for pid in self.AI_PROVIDERS:
                if not self.provider_key_issue(pid):
                    logger.info(f"AI_PROVIDER=auto 自动探测到 provider={pid}")
                    return pid
            logger.warning("AI_PROVIDER=auto 未探测到任何有效 Key，回退 deepseek")
            return "deepseek"
        logger.warning(f"未知 AI_PROVIDER={p!r}，回退 deepseek")
        return "deepseek"

    @property
    def LLM_BASE_URL(self) -> str:
        provider = self.AI_PROVIDERS.get(self.AI_PROVIDER_RESOLVED, self.AI_PROVIDERS["deepseek"])
        return os.getenv("LLM_BASE_URL", provider["base_url"])

    @property
    def LLM_API_KEY(self) -> str:
        provider = self.AI_PROVIDERS.get(self.AI_PROVIDER_RESOLVED, self.AI_PROVIDERS["deepseek"])
        env_key = provider.get("api_key_env", "DEEPSEEK_API_KEY")
        return os.getenv("LLM_API_KEY", os.getenv(env_key, ""))

    @property
    def LLM_MODEL(self) -> str:
        provider = self.AI_PROVIDERS.get(self.AI_PROVIDER_RESOLVED, self.AI_PROVIDERS["deepseek"])
        env_key = provider.get("model_env", "DEEPSEEK_MODEL")
        return os.getenv("LLM_MODEL", os.getenv(env_key, provider["default_model"]))

    # ===== v4.3: 模型调用优雅降级（fallback）链 =====
    @property
    def LLM_FALLBACK_CHAIN(self) -> list[dict]:
        """解析 LLM_FALLBACK_CHAIN 为有序候选列表，供 LLMClient 兜底重试。

        格式: "provider:model,provider:model,..." 或仅 "model"（沿用当前 provider）。
        每项独立解析 api_key / base_url（不同 provider 的 Key 通常不同）。
        空配置返回空列表 —— 此时退化为单模型（无 fallback），向后兼容。
        候选按出现顺序尝试，主模型（当前 provider/model）始终在首位（见 llm_client）。
        """
        raw = os.getenv("LLM_FALLBACK_CHAIN", "").strip()
        if not raw:
            return []
        candidates = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                provider, model = part.split(":", 1)
            else:
                # v6.0: 裸 model 条目沿用解析后的实际 provider（兼容 AI_PROVIDER=auto）
                provider, model = self.AI_PROVIDER_RESOLVED, part
            provider = provider.strip()
            model = model.strip()
            if provider not in self.AI_PROVIDERS:
                logger.warning(f"LLM_FALLBACK_CHAIN 含未知 provider: {provider}，已跳过")
                continue
            info = self.AI_PROVIDERS[provider]
            api_key = os.getenv("LLM_API_KEY", os.getenv(info["api_key_env"], ""))
            base_url = os.getenv("LLM_BASE_URL", info["base_url"])
            candidates.append({
                "provider": provider,
                "model": model,
                "api_key": api_key,
                "base_url": base_url,
            })
        return candidates

    @property
    def LLM_FALLBACK_MAX_RETRIES(self) -> int:
        """fallback 最大尝试候选数（默认 3；超出候选数时实际取候选数）。"""
        try:
            return int(os.getenv("LLM_FALLBACK_MAX_RETRIES", "3"))
        except ValueError:
            return 3

    # ===== v6.2: 任务级模型绑定（借鉴 GrillMind 的「按任务独立绑定模型」）=====
    # 不同任务对延迟/推理深度的要求不同：出题与追问要快，报告与职业规划可以慢而深。
    # 单一 LLM_MODEL 会让"想用强模型写报告"和"想用快模型上面试对话"互相妥协。
    #
    # 环境变量 LLM_TASK_MODELS，JSON 对象，值为 "model" 或 "provider:model"：
    #   LLM_TASK_MODELS={"diagnosis":"deepseek-chat","report":"qwen-max","parse":"glm-4-flash"}
    # 未配置的任务沿用 LLM_MODEL（向后兼容，不配即无变化）。

    # 任务枚举：key 为任务名，value 为中文说明（仅用于日志与前端展示）
    LLM_TASKS = (
        "parse",       # 简历解析 / 追问点提取
        "question",    # 出题（轮次题目 / 追加题）
        "interview",   # 面试追问 / 实时反馈
        "diagnosis",   # 回答诊断（流式，实时链路）
        "rewrite",     # 回答改写（流式，实时链路）
        "report",      # 报告生成
        "career",      # 职业规划路径推理
        "market",      # 市场 / 岗位分析
    )

    # 实时面试链路：对话中同步等待，延迟敏感，永远关深度思考
    REALTIME_TASKS = ("question", "interview", "diagnosis", "rewrite")

    # 面试永远关深度思考（默认开启）。
    # 推理类模型（deepseek-reasoner / o1 / qwen3-thinking / glm-z1）首 token 延迟数秒，
    # 放在面试对话里会明显卡顿；报告/规划类离线任务不受此限制。
    INTERVIEW_DISABLE_REASONING = os.getenv(
        "INTERVIEW_DISABLE_REASONING", "true"
    ).strip().lower() not in ("0", "false", "no", "off")

    @property
    def LLM_TASK_MODELS(self) -> dict:
        """解析 LLM_TASK_MODELS 为 {task: {"provider":..., "model":..., "api_key":..., "base_url":...}}。

        未配置 / 解析失败一律返回空 dict —— 所有任务沿用 LLM_MODEL，向后兼容。
        未知任务名与无效 provider 会被跳过并告警，不影响其它任务绑定。
        """
        raw = os.getenv("LLM_TASK_MODELS", "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"LLM_TASK_MODELS 不是合法 JSON，已忽略: {e}")
            return {}
        if not isinstance(data, dict):
            logger.warning("LLM_TASK_MODELS 应为 JSON 对象，已忽略")
            return {}

        result: dict = {}
        for task, spec in data.items():
            task = str(task).strip()
            spec = str(spec).strip()
            if task not in self.LLM_TASKS:
                logger.warning(f"LLM_TASK_MODELS 含未知任务 {task!r}，已跳过")
                continue
            if not spec:
                continue
            if ":" in spec:
                provider, model = spec.split(":", 1)
            else:
                provider, model = self.AI_PROVIDER_RESOLVED, spec
            provider, model = provider.strip(), model.strip()
            if provider not in self.AI_PROVIDERS:
                logger.warning(f"LLM_TASK_MODELS[{task}] 含未知 provider {provider!r}，已跳过")
                continue
            info = self.AI_PROVIDERS[provider]
            result[task] = {
                "provider": provider,
                "model": model,
                "api_key": os.getenv("LLM_API_KEY", os.getenv(info["api_key_env"], "")),
                "base_url": os.getenv("LLM_BASE_URL", info["base_url"]),
            }
        return result

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

    # ===== v3.3: 实时采集（job-crawler B档内嵌）=====
    # 采集口令（可选）：非空时前端调用 /api/market/crawl 必须携带相同 token，防滥用
    MARKET_CRAWL_TOKEN = os.getenv("MARKET_CRAWL_TOKEN", "")
    # 单次采集城市数上限 / 页数上限（与 job-crawler 一致）
    MARKET_CRAWL_CITY_LIMIT = int(os.getenv("MARKET_CRAWL_CITY_LIMIT", "5"))
    MARKET_CRAWL_PAGE_LIMIT = int(os.getenv("MARKET_CRAWL_PAGE_LIMIT", "5"))
    # 采集接口限流（Playwright 较重，防滥用）
    MARKET_CRAWL_RATE_LIMIT = os.getenv("MARKET_CRAWL_RATE_LIMIT", "3/minute")

    # ===== v4.2: 小米 MiMo 云端语音（可选）=====
    # 未配置 MIMO_API_KEY 时，前端自动降级为浏览器原生语音（speechSynthesis / SpeechRecognition）
    # 协议：TTS/ASR 均走 OpenAI 兼容的 {base}/chat/completions，认证头用 api-key
    # v6.1: Provider 注册表选择器（借鉴 offerMaster 的 STT_PROVIDER/TTS_PROVIDER 工厂），
    #       当前注册表仅 mimo；未知值回退 mimo 并告警
    VOICE_TTS_PROVIDER = os.getenv("VOICE_TTS_PROVIDER", "mimo")
    VOICE_STT_PROVIDER = os.getenv("VOICE_STT_PROVIDER", "mimo")
    MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
    MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
    MIMO_TTS_MODEL = os.getenv("MIMO_TTS_MODEL", "mimo-v2.5-tts")
    MIMO_ASR_MODEL = os.getenv("MIMO_ASR_MODEL", "mimo-v2.5-asr")
    # 预置音色（中文面试场景默认 冰糖；可选 茉莉/苏打/白桦/Mia/Chloe/Milo/Dean）
    MIMO_TTS_VOICE = os.getenv("MIMO_TTS_VOICE", "冰糖")
    # TTS 风格提示（自然语言，可空字符串）；首条 user 消息注入
    MIMO_TTS_STYLE = os.getenv("MIMO_TTS_STYLE", "自然、专业的面试官语气，语速适中，吐字清晰。")
    # ASR 识别语言：auto / zh / en
    MIMO_ASR_LANGUAGE = os.getenv("MIMO_ASR_LANGUAGE", "auto")
    # 语音请求超时（秒）与限流
    MIMO_TIMEOUT = int(os.getenv("MIMO_TIMEOUT", "60"))
    RATE_LIMIT_VOICE = os.getenv("RATE_LIMIT_VOICE", "20/minute")

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
            "closing": True,                # v6.2: 收尾阶段（工程强控，禁止追问/追加题）
        },
    ]

    # ===== v6.2: closing 阶段内部收尾指令（借鉴 GrillMind 的"工程强控"收尾手法） =====
    # 轮次计数推进到 closing 轮时，由工程层注入出题 prompt，
    # 使面试官在最后一轮自然收束，而不是无限追问（不依赖模型自决）。
    CLOSING_INSTRUCTION = """【收尾阶段 · 工程强控指令】
本轮是本次面试的最后一个阶段，请严格遵守：
1. 不要再开启任何新的技术话题或追问线索；
2. 提问方向限于：候选人向面试官的反问、对本次面试的收束确认、后续流程交代；
3. 语气转暖，给候选人一个体面的收尾，不要在本轮制造新的压力点；
4. 题目数量严格按照要求，不得多出。"""

    # closing 收束语（工程层确定性输出，不额外消耗 LLM 调用，也不会生成失败）
    CLOSING_MESSAGE = "本次面试到此结束，感谢你的参与。接下来我会基于你的回答生成一份面评报告，稍后可在报告页查看。"

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
            "closing": True,                # v6.2: 收尾阶段（工程强控）
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
