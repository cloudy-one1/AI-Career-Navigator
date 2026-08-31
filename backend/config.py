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

# 全局唯一版本号：FastAPI app（main.py）、/api/health（routers/system.py）、
# run.py 启动横幅统一引用此处，避免再出现「横幅 3.1 / 实际 7.3」的版本尾巴。
APP_VERSION = "7.3.1"


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

    # ===== v7.0: 认证与资源归属（CHARTER DC-06）=====
    # 默认关闭：AUTH_ENABLED=false 时所有鉴权与归属过滤跳过，行为与 v6.x 完全一致。
    # 这是 DC-06 承诺的回滚手段——认证层出问题时可一键退回现状，不必改代码。
    AUTH_ENABLED = os.getenv(
        "AUTH_ENABLED", "false"
    ).strip().lower() in ("1", "true", "yes", "on")
    # JWT 签名密钥。为空时不随机生成（否则每次重启所有 token 失效），
    # 而是生成后持久化到 data/.auth_secret（该文件须进 .gitignore）。
    AUTH_SECRET = os.getenv("AUTH_SECRET", "")
    AUTH_SECRET_FILE = os.path.join(BASE_DIR, "data", ".auth_secret")
    # token 有效期（小时）。注册/登录签发，过期后需重新登录。
    AUTH_TOKEN_TTL_HOURS = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "72"))
    # 密码策略（注册时校验，不做复杂度正则——长度是唯一被验证有效的策略）
    AUTH_PASSWORD_MIN_LENGTH = int(os.getenv("AUTH_PASSWORD_MIN_LENGTH", "8"))
    # 用户名长度区间，字符集限定为字母数字下划线连字符（避免空格/中文造成歧义）
    AUTH_USERNAME_MIN_LENGTH = 3
    AUTH_USERNAME_MAX_LENGTH = 32
    # 可选角色：求职者（默认）/ 招聘者。
    # 注意 recruiter 在本模块内无任何特权——其可见范围由 D3 的分享链接决定。
    AUTH_ROLES = ("jobseeker", "recruiter")

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

    # ===== v6.3: 压力题注入（借鉴 mock-interviewer 的压力题库）=====
    # 之前的"压力"只在语气层（pressure 风格 / hardcore 模式），题目仍全来自简历与 JD；
    # 压力题补的是**内容层面的不可预测性**——真实面试的压力很多来自被问到没准备过的题。
    PRESSURE_QUESTION_ENABLED = os.getenv(
        "PRESSURE_QUESTION_ENABLED", "true"
    ).strip().lower() not in ("0", "false", "no", "off")
    # 单场面试最多注入的压力题数量（压力题是调味不是主菜，多了变成刁难）
    PRESSURE_MAX_PER_SESSION = int(os.getenv("PRESSURE_MAX_PER_SESSION", "1"))
    # 按面试官 attack_level(1-5) 映射每轮注入概率：
    # 友好/鼓励型几乎不注入（不符合人设），压力型高概率注入。
    PRESSURE_PROB_BY_ATTACK_LEVEL = {
        1: 0.0,
        2: 0.15,
        3: 0.35,
        4: 0.60,
        5: 0.85,
    }

    # ===== v6.4: 检索语义近似通道（借鉴 MockFlow 的零依赖混合召回）=====
    # 检索评分在"关键词命中"之外叠加一条"字符 bigram 余弦相似度"通道，
    # 补同义/改写召回短板（如知识块写"检索召回率优化"、提问说"向量检索召回"，
    # 词命中为 0 但字面高度重叠）。零第三方依赖（MockFlow 用同一手法替代 Embedding）。
    # 注意：余弦相似度在长文本间会被绝对值稀释（我们块头最长 800 字、回答可达数百字，
    # 相关文本的实测相似度通常只有 0.1~0.3，与 MockFlow 的一行式语料完全不同量级），
    # 因此零词命中块的入选门槛必须是"绝对下限 + 相对最高相似度"双闸，不能只用固定阈值。
    # 绝对下限：相似度低于此值即使全场最高也不入选（防全场都低时矮子里拔将军）。
    RETRIEVAL_SEMANTIC_MIN_SIM = float(os.getenv("RETRIEVAL_SEMANTIC_MIN_SIM", "0.12"))
    # 相对门槛：零词命中块的相似度须达到全场最高相似度的此比例才入选。
    RETRIEVAL_SEMANTIC_TOP_RATIO = float(os.getenv("RETRIEVAL_SEMANTIC_TOP_RATIO", "0.8"))
    # bigram 余弦加成权重：加成 = WEIGHT × sim × 8.0（×8.0 对齐"命中一个词条 = +8 分"量级）。
    # 实测相似度量级（0.1~0.3）下加成约 0.1~0.8 分——语义信号只做排序微调，词条命中仍是主导。
    RETRIEVAL_SEMANTIC_WEIGHT = float(os.getenv("RETRIEVAL_SEMANTIC_WEIGHT", "0.35"))

    # ===== v6.5: 动态难度（借鉴 interviewerAgent internal/difficulty，只抄轮内自适应）=====
    # 只决定"当前这道题出多难"，**不参与阶段/轮次推进** —— 那部分归 v6.2 的工程强控。
    # 阈值基于本项目的五维加权总分（1-5 制），非对方的 0-100 制。
    DIFFICULTY_ENABLED = os.getenv(
        "DIFFICULTY_ENABLED", "true"
    ).strip().lower() not in ("0", "false", "no", "off")
    DIFFICULTY_INITIAL_LEVEL = int(os.getenv("DIFFICULTY_INITIAL_LEVEL", "3"))
    DIFFICULTY_MIN_LEVEL = int(os.getenv("DIFFICULTY_MIN_LEVEL", "1"))
    DIFFICULTY_MAX_LEVEL = int(os.getenv("DIFFICULTY_MAX_LEVEL", "5"))
    DIFFICULTY_UP_SCORE = float(os.getenv("DIFFICULTY_UP_SCORE", "4.0"))      # ≥ 此分连续达标 → 升档
    DIFFICULTY_DOWN_SCORE = float(os.getenv("DIFFICULTY_DOWN_SCORE", "2.0"))  # ≤ 此分连续失手 → 降档
    # 2.0~4.0 为中性区：两侧连续计数同时清零。
    DIFFICULTY_CONSEC = int(os.getenv("DIFFICULTY_CONSEC", "2"))              # 连续 N 次触发变档

    # ===== v2 追问阈值 =====
    FOLLOW_UP_MIN_LENGTH = 30       # 回答低于此字数触发追问
    FOLLOW_UP_MAX_COUNT = 2         # 单题最多追问次数
    FOLLOW_UP_SCORE_THRESHOLD = 2.5 # 回答质量低于此分数触发追问

    # ===== v6.3: JD 匹配缺口阈值 =====
    # Gap 分析各维度得分低于此值即视为"岗位要求但简历未充分体现"的缺口，
    # 注入出题 prompt 作为优先级链第一环（JD gap > JD 强匹配 > 简历锚点）。
    JD_GAP_SCORE_THRESHOLD = 3.5
    # 单场面试最多注入的缺口条数（过多会稀释重点、挤占上下文预算）
    JD_GAP_MAX_ITEMS = 5

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
    # v6.3: 每个风格从「一段语气描述」升级为「结构化角色卡」，新增三字段
    #   （对标 mock-interviewer 的 references/面试官画像.md）：
    #   perspective      —— 该角色的内心独白：他真正在评判什么。
    #                      正向描述模型会"创造性发挥"，视角独白才锚定判断标准。
    #   followup_chain   —— 该角色的追问链（list[str]）：决定"怎么问"。
    #                      与"薄弱维度"（决定"问什么"）正交，二者组合后才不会
    #                      出现"7 种风格语气不同、追问结构却完全同构"的问题。
    #   never_ask        —— 负向清单：该角色**不会问**什么。
    #                      这是最容易被忽略也最有效的一类约束——正向描述只能
    #                      引导，负向清单才能划出硬边界，防止角色失真。
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
            "perspective": "这个人的基础底子扎不扎实，紧张之下还能不能说出真实水平。",
            "followup_chain": [
                "你刚才提到 XX，能具体展开说说当时的情况吗",
                "在这件事里你自己负责的是哪一块",
                "如果现在重来一次，你会怎么调整",
            ],
            "never_ask": [
                "攻击性反诘与否定式评价",
                "明显超出候选人当前职级的架构战略题",
                "行业趋势与宏观商业判断",
            ],
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
            "perspective": "他说的每一句话有没有证据支撑，能不能扛住两层追问。",
            "followup_chain": [
                "具体是怎么实现的",
                "这个数字是怎么测出来的",
                "遇到过什么坑，最后怎么解决的",
                "还有没有更好的办法",
            ],
            "never_ask": [
                "纯行业趋势与宏观战略",
                "与简历无关的开放式闲聊",
                "组织架构与管理哲学",
            ],
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
            "perspective": "他在高压下会不会自相矛盾，会不会为了圆场而编造细节。",
            "followup_chain": [
                "你确定是这样吗，依据是什么",
                "换个角度看，你这个方案是不是根本不成立",
                "如果这些成果不是你带来的，你怎么证明",
                "给你 30 秒，重说一遍核心结论",
            ],
            "never_ask": [
                "针对个人而非专业的否定评价",
                "超出技术讨论边界的压迫与嘲讽",
                "同一问题的无意义反复逼问",
            ],
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
            "perspective": "他的能力边界在哪里，能不能按岗位标准稳定交付。",
            "followup_chain": [
                "这个方案你对比过哪些替代方案",
                "两者的核心差异在哪，什么条件下你会改选另一个",
                "落地过程中最大的阻力是什么，怎么解决的",
            ],
            "never_ask": [
                "寒暄式闲聊与客套追问",
                "与岗位 JD 无关的偏门知识点",
                "纯主观偏好式提问（例如偏好某个框架的主观理由）",
            ],
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
            "perspective": "他做过的事情里，有没有连他自己都没意识到的亮点。",
            "followup_chain": [
                "当时你是怎么想到这么做的",
                "这个决策背后你权衡了哪些因素",
                "如果资源不受限，你会怎么重新设计",
                "这段经历对你后来的技术判断有什么影响",
            ],
            "never_ask": [
                "冷冰冰的是非判断题",
                "纯记忆性的概念背诵",
                "打断式的连续逼问",
            ],
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
            "perspective": "简历上的每一个字，是不是他自己干的、是不是真做到了。",
            "followup_chain": [
                "这个数据是怎么归因的",
                "排除掉外部因素之后还剩多少",
                "这件事是你做的还是团队做的，你的角色是什么",
                "如果换个人来做，结果会差多少",
            ],
            "never_ask": [
                "无条件肯定的附和与赞美",
                "与简历完全无关的空想场景假设",
                "脱离项目语境的纯理论原理背诵",
            ],
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
            "perspective": "他现在缺的是信心还是能力，我能不能帮他把自己讲出来。",
            "followup_chain": [
                "你已经说了 XX，再想想还有没有可以补充的",
                "如果换一个你更熟悉的项目来回答，你会怎么说",
                "这个问题里你最有把握的是哪一块，我们先从那里聊",
            ],
            "never_ask": [
                "否定式评价与打击式追问",
                "明显超出其当前职级的难题",
                "换汤不换药的同一角度连续追问",
            ],
        },
    }


config = Config()
