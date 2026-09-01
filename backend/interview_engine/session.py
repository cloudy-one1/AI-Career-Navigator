"""
面试会话状态机 v2.6
管理双模式面试流程 + 多面试官切换。
拆分为 session + report 子模块。

v2.6 变更：
  1. 补齐 main.py WebSocket 主流程所需接口（此前接口断裂，运行即 AttributeError）
  2. 诊断维度权重按 JD 动态化，贯穿诊断 / 推进判定 / 报告
  3. 追问与流式诊断合并：诊断结果自带 follow_up_question，无需二次 LLM 往返
  4. 弱项追踪：按加权失分定位薄弱维度，驱动定向追加题
"""

import asyncio
import copy
import logging
import random

from ..config import config
from ..question_gen import (
    build_resume_points_block,
    generate_round_questions,
    FOCUS_DIMENSION_NAMES,
    generate_coach_tip,
)
from ..pressure_bank import sample_questions as sample_pressure_questions
from ..resume_anchors import ANCHOR_KEYS, ANCHOR_META, merge_anchor_sources
from ..dimension_weights import (
    DEFAULT_WEIGHTS,
    DIM_KEYS,
    DIM_NAMES,
    analyze_jd_weights,
    describe_weights,
    weighted_score,
)
from ..resume_retriever import build_evidence_package, content_hash, ResumeRetriever
from .flow import (                      # v7.0 流程状态与推进决策（纯逻辑，无 IO）
    FlowDecision,
    FlowSnapshot,
    FlowState,
    NextAction,
    decide_next,
    with_overrides,
)
from ..company_profiles import company_role_block, company_round_block  # v6.5 公司风格层
from ..interview_skills import SkillContext, default_registry  # v6.5 面试技能（有状态多轮）
from ..difficulty import DifficultyScheduler  # v6.5 动态难度（轮内自适应）
from ..output_sanitizer import (
    OUTPUT_CONSTRAINTS,
    contains_answer_leak,
    sanitize_spoken_text,
)
from .report import build_report

logger = logging.getLogger(__name__)

# v5.0: 不会答/示弱信号检测（对标 agent-interview-coach 的 coaching recovery）
UNCERTAIN_ANSWER_MARKERS = (
    "不会", "不懂", "没思路", "答不上来", "不知道", "不清楚",
    "没做过", "不太了解", "不了解", "没接触过", "忘了",
)

# ===== v6.1: 结束面试信号检测（借鉴 offerMaster rules.py 的退出词机制） =====
# 候选人在回答位输入/说出退出口令时，面试官应自然收束面试（而不是把口令当成回答去诊断）。
# 确定性关键词匹配，不依赖 LLM：低成本、可测试、无幻觉。
END_INTERVIEW_KEYWORDS = (
    "结束面试", "结束这次面试", "面试结束", "面试到此结束", "到此为止",
    "我想结束", "不想继续了", "停止面试", "end interview", "stop interview",
)


# ===== v6.3: 恢复/教练触发阈值（借鉴 mock-interviewer 的"连续触发 3 次主动建议跳过"）=====
# 为什么需要阈值：没有上限时，候选人可以对每一题都喊"不会"换提示，
# 面试从"能力诊断"退化成"提示驱动"，评分也失去意义。
RECOVERY_SKIP_THRESHOLD = 3
# 连续触发达阈值时，工程层直接用这句确定性话术覆盖模型的追问
RECOVERY_SKIP_ADVICE = (
    "这个方向我们先放一放，换一个你更熟悉的角度继续——"
    "你觉得这个项目里你做得最扎实的是哪一块？"
)
# 恢复态检测到"直接给答案"时的降级引导话术（绝不让答案从面试官口中说出）
RECOVERY_FALLBACK_PROMPT = (
    "没关系，我们换个角度：这道题里你最有把握的是哪一部分？从那里说起就好。"
)

# v6.2: 思考时长合理区间（秒）。超出即视为异常上报/前端计时错误，按 0 处理（不污染统计）。
MAX_THINKING_SECONDS = 600
MIN_THINKING_SECONDS = 0


def _normalize_thinking_seconds(value) -> float:
    """把前端上报的思考时长规整为合法秒数（非法值一律 0，不抛异常）。"""
    try:
        sec = float(value)
    except (TypeError, ValueError):
        return 0.0
    if sec != sec or sec < MIN_THINKING_SECONDS or sec > MAX_THINKING_SECONDS:  # NaN 自不等
        return 0.0
    return round(sec, 1)


def is_end_signal(text: str) -> bool:
    """检测回答文本是否为"结束面试"退出口令（大小写不敏感的子串匹配）。"""
    if not text:
        return False
    low = text.strip().lower()
    if not low:
        return False
    return any(kw in low for kw in END_INTERVIEW_KEYWORDS)


class InterviewSession:
    """单次面试会话的状态机 (v2.6 / v5.0)"""

    # ===== 生命周期 =====

    def __init__(self, session_id: str, resume_text: str, jd_text: str,
                 llm_client, diagnosis_engine, interview_style: str = "friendly",
                 db=None, mode: str = "simulation",
                 stage: str = "phone_screen",
                 include_self_intro: bool = False,
                 question_type_mix: dict = None,
                 resume_points: dict | None = None,
                 jd_gaps: list[str] | None = None,
                 company_profile: dict | None = None):
        self.session_id = session_id
        self.resume_text = resume_text
        self.jd_text = jd_text
        self.llm = llm_client
        self.diagnosis = diagnosis_engine
        self.style = interview_style
        self.db = db
        self.mode = mode
        self.stage = stage  # v5.0: 面试阶段（phone_screen/tech_round_1/tech_round_2/hr）

        # v2.7: 自我介绍 + 题型占比
        self.include_self_intro = include_self_intro
        self.self_intro_done = False
        self.question_type_mix = question_type_mix or {}

        # v6.2: 简历解析前置追问点（借鉴 GrillMind 的 deepDivePoints / vaguePoints）
        # 结构：{"deep_dive_points": [...], "vague_points": [...]}，解析失败时为空 dict。
        self.resume_points: dict = resume_points or {}

        # v6.3: JD 匹配缺口（岗位要求但简历未充分体现的点），由 L4（main.py）调
        # gap_analyzer 产出后注入。出题时作为优先级链第一环，未注入则降级为无缺口模式。
        # 刻意不在会话内调用 analyze_gap：那是一次 LLM 往返，出题链路已有多次调用，
        # 叠加会显著拉长首题等待；且 gap 对整场不变，创建期算一次即可。
        self.jd_gaps: list[str] = [str(g).strip() for g in (jd_gaps or []) if str(g).strip()]

        # v6.5: 目标公司风格（借鉴 interviewerAgent 的 companies/*.yaml 配置层）。
        # 由 L4（main.py）解析后传入完整 profile dict（显式选择 > JD 关键词自动匹配），
        # None = 不启用。会话层只消费不加载，保持 L3 不反向依赖 L2 的数据装配职责。
        self.company_profile: dict = company_profile or {}

        # v6.5: 面试技能（有状态多轮，借鉴 interviewerAgent internal/skill）。
        # 与 mode 的区别：mode 是整场设定且无结束条件；skill 是临时插入的一段流程，
        # 走完自动退回普通面试。技能轮**不进诊断**（测验答案是"B"，
        # 拿去打五维分只会污染报告），因此单独维护一段对话历史。
        self.skill_registry = default_registry()
        self.active_skill = ""
        self.skill_ctx: SkillContext | None = None
        self.skill_history: list[dict] = []

        # v7.0: 流程位置（显式"程序计数器"）。
        # 价值不在"多一个字段"，而在：面试进行到哪一步不再需要从
        # "最后一题有没有答""本轮第几题"反推，可以直接读出，也能落库供重启后追溯。
        self.flow_state: FlowState = FlowState.INIT
        self.answered_count: int = 0

        # v6.5: 动态难度（只管"这道题出多难"，不管"该进哪个阶段"——
        # 阶段推进归 v6.2 的轮次计数工程强控，难度信号不得反向干预）。
        self.difficulty = DifficultyScheduler(
            initial=config.DIFFICULTY_INITIAL_LEVEL,
            min_level=config.DIFFICULTY_MIN_LEVEL,
            max_level=config.DIFFICULTY_MAX_LEVEL,
            up_score=config.DIFFICULTY_UP_SCORE,
            down_score=config.DIFFICULTY_DOWN_SCORE,
            consec=config.DIFFICULTY_CONSEC,
        )
        # 变档事件由 main.py 推送后清空（与 pending_follow_up 同款的一次性信号）
        self.pending_difficulty: dict | None = None

        self.rounds = (config.TRADITIONAL_ROUNDS if mode == "traditional"
                       else config.INTERVIEW_ROUNDS)
        self.current_round = 0
        self.current_question_idx = 0

        self.round_questions = []
        self.round_answers = []
        self.round_diagnoses = []
        self.extra_questions_added = 0

        self.all_diagnoses = []
        self.interviewer_history = []

        self.follow_up_count = 0
        self.last_answer_text = ""
        self.pending_follow_up = ""       # v2.6: 流式诊断带出的追问，等待推送

        self.answer_history = []
        self.current_question_context = ""
        self.pending_status = False

        # v2.6: 诊断维度动态权重
        self.dim_weights = dict(DEFAULT_WEIGHTS)
        self.weight_reason = "尚未分析岗位，暂用五维等权"
        self.weight_source = "default"
        self._weights_ready = False

        # v5.0: 薄弱点跨轮累计 + 不会答恢复 + 简历证据检索
        self.weakness_tags: list[str] = []            # 去重累计（保序）
        self._weakness_counts: dict[str, int] = {}    # 标签 → 出现次数
        self.recovery_active = False                  # 当前是否处于"不会答恢复"状态
        # v6.3: 连续触发恢复的计数（正常回答即归零）。达阈值时由工程层
        # 主动建议跳过当前方向，避免候选人在同一处耗尽信心、也让评分失去意义。
        self.recovery_streak = 0
        self.recovery_total = 0                        # 全场触发总次数（报告中披露）
        self._recovery_advice_done = False             # 建议跳过的话术是否已用过
        self._retriever: ResumeRetriever | None = None
        self.mode_changed = False                     # 最近一次是否切换过模式（前端可提示）

        # v6.3 注入去重（借鉴 HakiMeet 的 _injected_cache，改用 blake2b 稳定指纹）：
        # 累计本会话已注入 prompt 的内容指纹，下一轮检索时排除，
        # 避免长会话中同一段简历证据被反复拼进 prompt（重复追问、浪费上下文预算）。
        # 生命周期 = 会话，随 InterviewSession 一起释放，无跨会话泄漏。
        self._injected_hashes: set[str] = set()

        # v6.3 备选题/换题：本次会话已问过的题目（文本 + 指纹）。
        # 出题时作为【已问题目清单·严禁重复】负向约束传给 question_gen，
        # 换题时才能真正给出新题，而不是换汤不换药的重复题。
        self.asked_questions: list[str] = []
        self.asked_question_hashes: set[str] = set()

        # v6.3 长期记忆闭环：历史未解决薄弱点，由 L4（main.py）从 db 拉取后注入。
        # 会话层刻意不持有 DB 句柄——数据访问留在 L4，避免 L3 反向依赖数据层细节。
        self.long_term_memory: list[dict] = []

        # v6.3 压力题注入（借鉴 mock-interviewer 压力题库）：
        # 之前的压力只在语气层，题目仍全来自简历/JD；压力题补的是内容层的不可预测性。
        # 整场限量，注入后登记进已问题目台账（与普通题共用去重机制）。
        self.pressure_injected = 0

    # ===== v6.5: 动态难度（轮内自适应，不参与阶段推进）=====

    def record_difficulty(self, score) -> None:
        """按诊断加权总分演进难度档（诊断失败/缺分时不记录）。

        为什么不放在 diagnosis_engine：难度是会话级状态，诊断引擎是无状态的一次调用。
        """
        if not config.DIFFICULTY_ENABLED:
            return
        changed, direction = self.difficulty.record(score)
        if not changed:
            return
        level = self.difficulty.state.level
        logger.info("[session] %s 难度变档 → %d（%s）",
                    self.session_id[:8], level, "升" if direction > 0 else "降")
        self.pending_difficulty = {
            "type": "difficulty_change",
            "level": level,
            "direction": direction,
            "message": f"难度已{'提升' if direction > 0 else '下调'}至 {level}/{self.difficulty.max_level} 档",
        }

    def difficulty_instruction(self) -> str:
        """出题时注入的难度指令（未启用返回空串，与 closing_instruction 同注入通道）。"""
        if not config.DIFFICULTY_ENABLED:
            return ""
        return self.difficulty.build_prompt()

    # ===== v2.6: JD 动态权重 =====

    async def init_weights(self) -> dict:
        """
        分析 JD 得到五维度权重。会话建立后调用一次，失败自动退化等权。
        返回可直接推送给前端的权重事件数据。
        """
        if self._weights_ready:
            return self.weights_payload()

        try:
            result = await analyze_jd_weights(self.llm, self.jd_text)
            self.dim_weights = result["weights"]
            self.weight_reason = result["reason"]
            self.weight_source = result["source"]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"权重初始化失败，保持等权: {e}")
        finally:
            self._weights_ready = True

        return self.weights_payload()

    def weights_payload(self) -> dict:
        """权重信息的标准推送结构。"""
        return {
            "weights": dict(self.dim_weights),
            "weight_names": {k: DIM_NAMES[k] for k in DIM_KEYS},
            "weight_desc": describe_weights(self.dim_weights),
            "reason": self.weight_reason,
            "source": self.weight_source,
        }

    # ===== 属性 =====

    @property
    def is_finished(self):
        return self.current_round >= len(self.rounds)

    @property
    def current_question(self):
        if self.current_question_idx < len(self.round_questions):
            return self.round_questions[self.current_question_idx]
        return None

    @property
    def round_remaining(self):
        return len(self.round_questions) - self.current_question_idx

    # ===== 轮次控制 =====

    def current_round_info(self) -> dict:
        idx = min(self.current_round, len(self.rounds) - 1)
        return self.rounds[idx]

    # ===== v6.2: closing 收尾阶段（借鉴 GrillMind 的工程强控收尾） =====

    def is_closing_round(self) -> bool:
        """当前轮是否为收尾阶段。

        判定：轮次配置显式标记 closing=True，或已推进到最后一轮。
        这是工程层的确定性判定，不依赖 LLM 自决，用于强控：
        收尾阶段禁止追问、禁止追加题，并在出题时注入内部收尾指令。
        """
        if self.is_finished:
            return True
        info = self.current_round_info()
        return bool(info.get("closing")) or self.current_round >= len(self.rounds) - 1

    # ===== v7.0: 流程位置（显式状态机）=====

    def snapshot(self, **overrides) -> FlowSnapshot:
        """构造推进决策所需的纯数据快照。

        为什么是方法而不是直接读 self：快照是**决策输入**的边界，
        把它显式化之后，decide_next 才可能脱离会话对象被单测。

        overrides 用于"预演"——调用方可以临时改某个输入（例如把诊断结果传进来），
        而不必真的改动会话状态。
        """
        cfg = self.current_round_info()
        diag = self.round_diagnoses[-1] if self.round_diagnoses else None
        quality = self.check_round_quality()

        # check_round_quality 的 passed 是纯数值比较（avg >= threshold）。
        # 当本轮还没答过题时 avg=0，而部分轮次的 advance_threshold 也是 0
        # （例如"破冰环节"不设门槛），此时会得到"未答一题却判定通过"。
        # 这里补上"必须有答题记录"的前提 —— 语义上"通过"只能建立在答题之上。
        # 该修正只影响新的纯函数决策，旧的 advance_round 走的是另一条路径。
        answered = len(self.round_answers)
        round_passed = bool(quality.get("passed")) and answered > 0
        avg_below = round_passed is False

        snap = FlowSnapshot(
            flow_state=self.flow_state,
            current_round=self.current_round,
            total_rounds=len(self.rounds),
            is_closing_round=self.is_closing_round(),
            question_idx=self.current_question_idx,
            questions_in_round=len(self.round_questions),
            answered_in_round=len(self.round_answers),
            extra_added=self.extra_questions_added,
            max_extra=int(cfg.get("max_extra_questions", 0) or 0),
            round_passed=round_passed,
            below_min_questions=(
                answered < int(cfg.get("min_questions", 1) or 1)
            ),
            follow_up_count=self.follow_up_count,
            follow_up_max=config.FOLLOW_UP_MAX_COUNT,
            has_follow_up_question=bool(
                diag and str(diag.get("follow_up_question", "") or "").strip()
            ),
            next_action=(diag or {}).get("next_action"),
            answer_too_short=(
                len((self.last_answer_text or "").strip()) < config.FOLLOW_UP_MIN_LENGTH
            ),
            round_avg_below_threshold=avg_below,
            recovery_streak=self.recovery_streak,
            recovery_skip_threshold=RECOVERY_SKIP_THRESHOLD,
            recovery_advice_done=self._recovery_advice_done,
        )
        return snap if not overrides else with_overrides(snap, **overrides)

    def decide(self, **overrides) -> FlowDecision:
        """判定下一步动作（委托给纯函数 decide_next）。"""
        return decide_next(self.snapshot(**overrides))

    def set_flow_state(self, state: FlowState, answered: int | None = None) -> None:
        """更新流程位置。只改内存字段 —— 落库由 L4（main.py）在异步上下文中完成。

        为什么不在会话内写库：session 的方法大多是同步的（供流式链路调用），
        在这里 await 会把整个调用链都变成异步，改动面远大于收益。
        """
        self.flow_state = state
        if answered is not None:
            self.answered_count = answered

    def flow_payload(self) -> dict:
        """供接口/落库使用的流程状态摘要。"""
        return {
            "flow_state": self.flow_state.value
            if isinstance(self.flow_state, FlowState) else str(self.flow_state),
            "answered_count": self.answered_count,
            "current_round": self.current_round,
            "question_idx": self.current_question_idx,
            "follow_up_count": self.follow_up_count,
        }

    def closing_instruction(self) -> str:
        """返回注入出题 prompt 的内部收尾指令（非收尾阶段返回空串）。"""
        return config.CLOSING_INSTRUCTION if self.is_closing_round() else ""

    def current_interviewer(self) -> dict:
        cfg = self.current_round_info()
        style_id = cfg.get("interviewer_style", self.style)
        interviewer = config.INTERVIEWER_STYLES.get(style_id, config.INTERVIEWER_STYLES["friendly"])
        return {
            "style_id": interviewer["id"],
            "name": interviewer["name"],
            "description": interviewer["description"],
            "attack_level": interviewer.get("attack_level", 1),
            "interrupt_prob": interviewer.get("interrupt_prob", 0.05),
            "prompt_modifier": interviewer.get("system_prompt_modifier", ""),
            # v6.3: 结构化角色卡三件套（对标 mock-interviewer 面试官画像）
            "perspective": interviewer.get("perspective", ""),
            "followup_chain": list(interviewer.get("followup_chain", []) or []),
            "never_ask": list(interviewer.get("never_ask", []) or []),
        }

    def get_interviewer_system_prompt(self) -> str:
        """保持返回风格原始语气指令（既有契约，勿改语义）。

        需要完整角色卡（含视角/追问链/负向清单）时用 get_interviewer_role_prompt()。
        """
        return self.current_interviewer().get("prompt_modifier", "")

    def get_interviewer_role_prompt(self) -> str:
        """v6.3: 完整角色卡 —— 语气指令 + 视角独白 + 追问链 + 不会问清单。

        为什么拆成独立方法而不是改 get_interviewer_system_prompt：
        后者是既有对外契约（前端/测试按"原始语气指令"取用），扩展其返回值会
        让"风格指令"与"角色卡"两种语义混在一个字段里，调用方难以分辨。

        三段的各自作用：
          - perspective：正向描述模型会创造性发挥，视角独白才锚定"他在评判什么"；
          - followup_chain：决定"怎么问"，与薄弱维度（决定"问什么"）正交；
          - never_ask：负向清单划硬边界，防止角色失真（如友好型去聊宏观战略）。

        v6.5: 公司风格块前置 —— 注入顺序为「公司人格 > 本轮公司指令 > 风格角色卡」。
        公司是外层人格（评判标准、追问清单、行业语境），风格卡是内层语气（怎么说话），
        两者正交；公司块放最前，避免风格卡的语气指令稀释公司特定的考察要求。
        """
        parts: list[str] = []
        if self.company_profile:
            role_block = company_role_block(self.company_profile)
            if role_block:
                parts.append(role_block)
            round_block = company_round_block(
                self.company_profile, self.current_round_info().get("name", "")
            )
            if round_block:
                parts.append(round_block)
        iv = self.current_interviewer()
        parts.append(iv.get("prompt_modifier", ""))  # v6.5: append 而非重建，保留前置的公司风格块
        if iv.get("perspective"):
            parts.append(
                f"\n【你在评判什么】{iv['perspective']}"
            )
        if iv.get("followup_chain"):
            chain = " → ".join(iv["followup_chain"])
            parts.append(
                f"\n【你的追问路径】按此链路逐层深入：{chain}\n"
                "不要跳过链路层级，也不要在链路之外另起无关话题。"
            )
        if iv.get("never_ask"):
            never = "；".join(iv["never_ask"])
            parts.append(
                f"\n【你不问什么】以下内容不属于你的考察范围，严禁提问：{never}"
            )
        return "\n".join(p for p in parts if p).strip()

    def _get_question_type(self) -> str:
        """推断当前问题的题型，用于差异化诊断。"""
        q = self.current_question
        if q and isinstance(q, dict) and q.get("question_type"):
            return q["question_type"]

        info = self.current_round_info()
        round_name = info.get("name", "")

        type_map = {
            "破冰": "self_intro",
            "笔试": "knowledge",
            "技术广度": "knowledge",
            "技术深度": "knowledge",
            "技术一面": "knowledge",
            "技术二面": "knowledge",
            "项目拷问": "project",
            "项目深挖": "project",
            "行为面试": "behavior",
            "综合面试": "mixed",
            "综合": "mixed",
            "反问收尾": "mixed",
            "自定义环节": "mixed",
        }
        return type_map.get(round_name, "mixed")

    def get_interviewer_change_event(self) -> dict | None:
        cfg = self.current_round_info()
        current_style = cfg.get("interviewer_style", self.style)
        prev_style = None
        if self.interviewer_history:
            prev_style = self.interviewer_history[-1].get("style_id")

        if prev_style and prev_style != current_style:
            old_intv = config.INTERVIEWER_STYLES.get(prev_style, {})
            new_intv = self.current_interviewer()
            self.interviewer_history.append({
                "round": self.current_round,
                "style_id": current_style,
                "name": new_intv["name"],
            })
            return {
                "type": "interviewer_change",
                "previous": {
                    "style_id": prev_style,
                    "name": old_intv.get("name", "未知"),
                },
                "current": {
                    "style_id": current_style,
                    "name": new_intv["name"],
                    "description": new_intv.get("description", ""),
                },
                "reason": f"进入{cfg['name']}，面试官切换为{new_intv['name']}",
            }

        if not self.interviewer_history:
            new_intv = self.current_interviewer()
            self.interviewer_history.append({
                "round": self.current_round,
                "style_id": current_style,
                "name": new_intv["name"],
            })
            return {
                "type": "interviewer_change",
                "previous": None,
                "current": {
                    "style_id": current_style,
                    "name": new_intv["name"],
                    "description": new_intv.get("description", ""),
                },
                "reason": f"面试开始，当前面试官：{new_intv['name']}",
            }

        return None

    # ===== 评分统计（v2.6 全部改为加权） =====

    def _current_round_avg_score(self) -> float:
        """本轮加权平均分。"""
        if not self.round_diagnoses:
            return 0.0
        scores = [d.get("overall_score", 0) for d in self.round_diagnoses]
        scores = [s for s in scores if s and s > 0]
        return round(sum(scores) / len(scores), 2) if scores else 0.0

    def round_weak_dimension(self) -> tuple[str, str]:
        """
        定位本轮最薄弱的维度。
        判定依据：各维度加权失分（(5 - 均分) x 权重）最大者 —— 兼顾"分低"与"这个岗位很看重"。
        返回 (维度 key, 失分证据文本)
        """
        if not self.round_diagnoses:
            return "", ""

        sums: dict[str, list[float]] = {k: [] for k in DIM_KEYS}
        comments: dict[str, list[str]] = {k: [] for k in DIM_KEYS}

        for d in self.round_diagnoses:
            for k, v in (d.get("dimensions") or {}).items():
                if k in sums and isinstance(v, (int, float)) and v > 0:
                    sums[k].append(float(v))
            for k, detail in (d.get("dimension_details") or {}).items():
                if k in comments and isinstance(detail, dict):
                    c = str(detail.get("comment", "")).strip()
                    if c and c != "无法解析":
                        comments[k].append(c)

        best_key, best_loss = "", -1.0
        for k in DIM_KEYS:
            if not sums[k]:
                continue
            avg = sum(sums[k]) / len(sums[k])
            loss = (5.0 - avg) * self.dim_weights.get(k, 0.25)
            if loss > best_loss:
                best_loss, best_key = loss, k

        if not best_key or best_loss <= 0:
            return "", ""

        evidence = "；".join(comments.get(best_key, [])[:2])
        return best_key, evidence

    def should_add_extra_question(self) -> bool:
        """是否还能追加题目"""
        cfg = self.current_round_info()
        return self.extra_questions_added < cfg.get("max_extra_questions", 0)

    def has_more_questions_in_round(self) -> bool:
        """本轮是否还有未提问的题目（main.py 契约）"""
        return self.current_question_idx < len(self.round_questions)

    def check_round_quality(self) -> dict:
        """
        轮次质量检查（main.py 契约）。
        返回是否达标、当前加权均分、阈值，以及薄弱维度，供前端展示与追加题决策使用。
        """
        cfg = self.current_round_info()
        threshold = cfg.get("advance_threshold", 3.0)
        avg = self._current_round_avg_score()
        weak_key, weak_evidence = self.round_weak_dimension()
        return {
            "round": self.current_round,
            "round_name": cfg["name"],
            "avg_score": avg,
            "threshold": threshold,
            "passed": avg >= threshold,
            "answered": len(self.round_answers),
            "min_questions": cfg.get("min_questions", 1),
            "extra_added": self.extra_questions_added,
            "max_extra": cfg.get("max_extra_questions", 0),
            "can_add_extra": self.should_add_extra_question(),
            "weak_dimension": weak_key,
            "weak_dimension_name": DIM_NAMES.get(weak_key, ""),
            "weak_evidence": weak_evidence,
            "weight_desc": describe_weights(self.dim_weights),
        }

    def advance_round(self) -> bool:
        """
        推进到下一轮。返回 True 表示还有下一轮，False 表示面试结束（main.py 契约）。
        v5.0: 若中途切换过模式（如切到 traditional），按新模式重建轮次结构。
        """
        self.current_round += 1
        self.current_question_idx = 0
        self.round_questions = []
        self.round_answers = []
        self.round_diagnoses = []
        self.extra_questions_added = 0
        self.follow_up_count = 0
        if self.mode_changed:
            self.rounds = (config.TRADITIONAL_ROUNDS if self.mode == "traditional"
                           else config.INTERVIEW_ROUNDS)
            self.current_round = min(self.current_round, len(self.rounds))
            self.mode_changed = False
        return not self.is_finished

    def round_summary(self) -> dict:
        """本轮小结，用于 round_summary 消息。"""
        cfg = self.current_round_info()
        weak_key, _ = self.round_weak_dimension()
        return {
            "round": self.current_round,
            "round_name": cfg["name"],
            "avg_score": self._current_round_avg_score(),
            "question_count": len(self.round_answers),
            "weak_dimension": weak_key,
            "weak_dimension_name": DIM_NAMES.get(weak_key, ""),
        }

    # ===== 回答处理（main.py 契约） =====

    def record_answer(self, answer_text: str, diagnosis: dict | None = None,
                      thinking_seconds: float = 0, assisted: bool = False):
        """
        记录一次回答与其诊断结果，并前移题目指针。

        v6.2: thinking_seconds —— 从题目展示到提交回答的思考时长（前端上报）。
        用于报告的 qaBreakdown，把"答得好不好"和"想了多久"放在一起看：
        想很久才答好 vs 张口就来却答偏，是两种完全不同的真实面试风险。

        v6.3: assisted —— 本题是否借助了恢复/教练引导。
        借鉴 mock-interviewer："教练对话不计入该题评分，但复盘中标注'借助引导'"。
        本系统不做"不计分"（评分是连续诊断链路的一部分，剔除会打断数据流），
        改为**标注**：分数照常记录，但报告里明确标出该题借助了引导，
        让读者自己判断这个分数的成色——比悄悄改分数更诚实。
        """
        self.round_answers.append(answer_text)
        self.last_answer_text = answer_text
        self.follow_up_count = 0  # 新题目，重置追问计数
        self.answered_count += 1  # v7.0: 累计答题数（落库供重启后追溯）

        q = self.current_question
        question_text = q.get("question", "") if isinstance(q, dict) else str(q or "")

        thinking = _normalize_thinking_seconds(thinking_seconds)

        self.answer_history.append({
            "round": self.current_round,
            "question_idx": self.current_question_idx,
            "question": question_text,
            "answer": answer_text,
            "thinking_seconds": thinking,
        })

        if diagnosis:
            diag_with_round = copy.deepcopy(diagnosis)
            diag_with_round["round"] = self.current_round
            diag_with_round["round_name"] = self.current_round_info()["name"]
            diag_with_round["question_idx"] = self.current_question_idx
            diag_with_round["question"] = question_text
            diag_with_round["thinking_seconds"] = thinking
            diag_with_round["assisted"] = bool(assisted)
            self.round_diagnoses.append(diag_with_round)
            self.all_diagnoses.append(diag_with_round)
            self.pending_follow_up = str(diagnosis.get("follow_up_question", "") or "").strip()
            # v5.0: 薄弱点跨轮累计
            tags = diagnosis.get("weakness_tags") or []
            if tags:
                self.accumulate_weaknesses(tags)
            # v6.5: 动态难度 —— 用诊断的加权总分（1-5）驱动，不是回复长度。
            # 缺分/诊断失败时不记录：那不是"得了 0 分"，误记会把难度一路降到底档。
            self.record_difficulty(diagnosis.get("overall_score"))
        else:
            self.pending_follow_up = ""

        self.pending_follow_up = self._guard_recovery_output(self.pending_follow_up, assisted)
        self.current_question_idx += 1

    # ===== v5.0: 简历证据 / 不会答恢复 / 多模式 =====

    def _evidence_for(self, answer_text: str) -> str:
        """按候选人当前回答检索简历，生成【本轮证据包】。

        v6.2: 追加简历解析阶段产出的前置追问点（deepDivePoints/vaguePoints），
        使诊断侧的 follow_up_question 也有数据支撑，而不是模型临场泛问。

        v6.3: 检索时排除本会话已注入过的证据块，并把本轮入选块的指纹记入缓存。
        证据块总量有限，长会话后期可能出现"全部已注入"——此时 select_context_tracked
        会回退复用，保证证据包不退化为空（去重不得以牺牲诊断依据为代价）。
        """
        if self._retriever is None:
            self._retriever = ResumeRetriever()
            if self.resume_text and self.resume_text.strip():
                self._retriever.add_document("简历", self.resume_text)
        evidence, injected = self._retriever.select_context_tracked(
            answer_text, exclude_hashes=self._injected_hashes
        )
        if injected:
            self._injected_hashes.update(injected)
            logger.debug("[session] %s 证据注入去重：本轮新增 %d 块，累计 %d 块",
                         self.session_id[:8], len(injected), len(self._injected_hashes))
        if self.resume_points:
            evidence = f"{evidence}\n{build_resume_points_block(self.resume_points)}"
        return evidence

    def needs_recovery(self, answer_text: str) -> bool:
        """检测候选人是否表示"不会/不懂/没思路"，触发不会答恢复。"""
        if not answer_text:
            return False
        low = answer_text.strip().lower()
        return any(m in low for m in UNCERTAIN_ANSWER_MARKERS)

    # ===== v6.3: 恢复/教练模式的工程化约束 =====

    def _update_recovery_streak(self, recovery_requested: bool) -> None:
        """维护"连续触发恢复"计数：触发 +1，正常回答归零。

        连续（而非累计）计数的原因：偶发卡壳是正常的，连续卡在同一类问题上
        才说明这个方向对候选人当前水平不合适，需要主动换方向。
        """
        if recovery_requested:
            self.recovery_streak += 1
            self.recovery_total += 1
        else:
            self.recovery_streak = 0

    def _guard_recovery_output(self, text: str, assisted: bool) -> str:
        """恢复态下对面试官话术做两道工程兜底。

        1) **绝不给答案**：模型若违反恢复红线直接报出答案，确定性替换为引导话术。
           Prompt 已约束，但模型并非 100% 遵守——这是工程层兜底，与
           output_sanitizer 对 Markdown/垫词的处理同一思路。
        2) **连续触发达阈值主动建议跳过**：不再顺着原题继续追问，
           否则候选人会在同一个方向上反复受挫，评分也失去意义。
        """
        if self.recovery_streak >= RECOVERY_SKIP_THRESHOLD and not self._recovery_advice_done:
            self._recovery_advice_done = True
            logger.info("[session] %s 连续 %d 次触发恢复，工程层主动建议跳过当前方向",
                        self.session_id[:8], self.recovery_streak)
            return RECOVERY_SKIP_ADVICE

        if assisted and text and contains_answer_leak(text):
            logger.warning("[session] %s 恢复态输出疑似直接给答案，已替换为引导话术",
                           self.session_id[:8])
            return RECOVERY_FALLBACK_PROMPT

        return text

    def accumulate_weaknesses(self, tags: list[str]) -> None:
        """跨轮累计薄弱点标签（保序去重 + 计数）。"""
        for t in tags:
            t = str(t).strip()
            if not t:
                continue
            self._weakness_counts[t] = self._weakness_counts.get(t, 0) + 1
            if t not in self.weakness_tags:
                self.weakness_tags.append(t)

    def weakness_payload(self) -> dict:
        """薄弱点面板数据（供前端实时刷新）。"""
        return {
            "tags": list(self.weakness_tags),
            "counts": dict(self._weakness_counts),
            "recovery_active": self.recovery_active,
        }

    def switch_mode(self, mode: str, stage: str | None = None) -> dict:
        """
        v5.0: 会话进行中切换面试模式/阶段。
        返回前端可用的模式切换事件；traditional <-> simulation 会改变轮次结构，
        因此会话中途仅允许在 simulation/coach/hardcore/interview_only 之间切换，
        切换 traditional 需要重建轮次（返回提示，由 main.py 决定是否强制）。
        """
        old_mode = self.mode
        new_mode = mode if mode in ("simulation", "traditional", "coach", "hardcore", "interview_only") else old_mode

        if new_mode == "traditional" and old_mode != "traditional":
            # 传统模式轮次结构与拟真模式不同，中途切换需在下一轮生效
            self.mode = new_mode
            self.mode_changed = True
            self.recovery_active = False
            return {
                "type": "mode_change",
                "session_id": self.session_id,
                "previous": {"mode": old_mode, "stage": self.stage},
                "current": {"mode": new_mode, "stage": self.stage},
                "message": f"模式已切换为「{new_mode}」，下一轮将使用传统 5 轮制结构",
                "applied_next_round": True,
            }

        if new_mode != old_mode:
            self.mode = new_mode
            self.mode_changed = True
            self.recovery_active = False

        if stage is not None and stage in ("phone_screen", "tech_round_1", "tech_round_2", "hr"):
            self.stage = stage

        if new_mode == old_mode and (stage is None or stage == self.stage):
            return {
                "type": "mode_change",
                "session_id": self.session_id,
                "previous": {"mode": old_mode, "stage": self.stage},
                "current": {"mode": new_mode, "stage": self.stage},
                "message": "模式未变化",
                "applied_next_round": False,
            }

        return {
            "type": "mode_change",
            "session_id": self.session_id,
            "previous": {"mode": old_mode, "stage": self.stage},
            "current": {"mode": new_mode, "stage": self.stage},
            "message": f"面试模式已切换为「{new_mode}」，接下来我将按新模式进行",
            "applied_next_round": False,
        }

    # ===== v6.5: 面试技能（有状态多轮，借鉴 interviewerAgent internal/skill）=====

    def is_skill_active(self) -> bool:
        return bool(self.active_skill) and self.skill_ctx is not None

    def activate_skill(self, name: str) -> dict:
        """显式激活一个技能（默认触发方式，不靠关键词猜测）。

        返回前端可用事件；未知技能名 / 已有进行中技能 → 返回 error 事件，不改变状态。
        """
        skill = self.skill_registry.get(str(name or "").strip())
        if skill is None:
            return {
                "type": "skill_start", "ok": False,
                "message": f"未知技能：{name}。可用技能："
                           + "、".join(s["name"] for s in self.skill_registry.list()),
            }
        if self.is_skill_active():
            return {
                "type": "skill_start", "ok": False,
                "message": f"「{self.active_skill}」进行中，请先完成或退出。",
            }

        self.active_skill = skill.name
        self.skill_ctx = SkillContext(
            session_id=self.session_id,
            mode=self.mode,
            weak_tags=list(self.weakness_tags[:3]),
        )
        self.skill_history = []
        logger.info("[session] %s 激活技能 %s", self.session_id[:8], skill.name)
        return {
            "type": "skill_start", "ok": True,
            "skill": skill.name,
            "description": skill.description,
            "total_steps": skill.total_steps(),
            "step": 1,
            "message": skill.opening_message(self.skill_ctx),
        }

    def deactivate_skill(self, reason: str = "completed") -> dict:
        """退出技能模式，回到普通面试。"""
        if not self.is_skill_active():
            return {"type": "skill_end", "ok": False, "message": "当前没有进行中的技能"}
        skill = self.skill_registry.get(self.active_skill)
        message = skill.closing_message(self.skill_ctx) if skill else "我们回到正式面试。"
        name = self.active_skill
        self.active_skill = ""
        self.skill_ctx = None
        self.skill_history = []
        logger.info("[session] %s 退出技能 %s（%s）", self.session_id[:8], name, reason)
        return {"type": "skill_end", "ok": True, "skill": name,
                "reason": reason, "message": message}

    def skill_prompt(self) -> str:
        """当前步的技能 prompt（技能模式下优先级最高，覆盖普通面试官角色卡）。"""
        if not self.is_skill_active():
            return ""
        skill = self.skill_registry.get(self.active_skill)
        if skill is None:
            return ""
        return skill.build_prompt(self.skill_ctx)

    def advance_skill(self, answer_text: str) -> dict:
        """推进技能状态一步；完成则自动退出并返回结束事件。"""
        if not self.is_skill_active():
            return {"ok": False, "message": "当前没有进行中的技能"}
        skill = self.skill_registry.get(self.active_skill)
        ctx = self.skill_ctx

        self.skill_history.append({"role": "user", "content": answer_text})
        skill.on_turn_end(ctx, answer_text)

        if skill.is_complete(ctx):
            event = self.deactivate_skill(reason="completed")
            return {
                "ok": True, "completed": True,
                "step": ctx.step, "total": skill.total_steps(),
                "message": event.get("message", ""),
            }
        return {
            "ok": True, "completed": False,
            "step": ctx.step, "total": skill.total_steps(),
        }

    async def generate_skill_turn(self, answer_text: str = "") -> str:
        """生成技能模式下面试官的下一句话。

        刻意走独立的一段对话历史、不复用诊断链路：
        技能轮的"回答"（如测验选项 B）不是面试作答，打五维分没有意义。
        输出同样经过 output_sanitizer（与正式面试官话术同一净化标准）。
        """
        if not self.is_skill_active():
            return ""
        skill = self.skill_registry.get(self.active_skill)
        prompt = self.skill_prompt()
        if not prompt:
            return ""
        if answer_text:
            self.skill_history.append({"role": "user", "content": answer_text})
        try:
            reply = await asyncio.to_thread(
                self.llm.chat,
                prompt,
                "\n".join(f"{m['role']}: {m['content']}" for m in self.skill_history)
                or "（请开始这个环节）",
                0.7,
                500,
                None,
                "interview",   # 任务级模型绑定：实时链路，禁推理模型
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[session] 技能 {self.active_skill} 生成失败: {e}")
            return ""
        reply = sanitize_spoken_text(str(reply or "")).strip()
        if reply:
            self.skill_history.append({"role": "assistant", "content": reply})
        return reply

    async def handle_answer(self, answer_text: str, from_voice: bool = False,
                            thinking_seconds: float = 0) -> dict:
        """
        非流式处理一次回答（降级路径 / 兼容 main.py 契约）。
        流式主流程请使用 stream_answer()。
        v5.0: 注入简历证据包 + 不会答恢复信号。
        v6.1: from_voice=True 时诊断注入 ASR 容错评分话术。
        """
        q = self.current_question
        question_text = q.get("question", "") if isinstance(q, dict) else str(q or "")
        recovery_requested = self.needs_recovery(answer_text)
        self._update_recovery_streak(recovery_requested)

        diagnosis = await self.diagnosis.diagnose(
            question=question_text,
            answer=answer_text,
            resume_text=self.resume_text,
            jd_text=self.jd_text,
            weights=self.dim_weights,
            evidence_package=self._evidence_for(answer_text),
            mode=self.mode,
            recovery_requested=recovery_requested,
            from_voice=from_voice,
            # v6.3: 追问主要由诊断侧产出，角色卡必须一路传下去，
            # 否则换面试官只换语气、追问结构不变。
            interviewer_role=self.get_interviewer_role_prompt(),
        )
        # v6.3: assisted 标记 —— 本题借助了恢复引导，分数照记但报告中披露
        self.record_answer(answer_text, diagnosis, thinking_seconds,
                           assisted=recovery_requested)
        if recovery_requested:
            self.recovery_active = True
        return diagnosis

    async def stream_answer(self, answer_text: str, from_voice: bool = False,
                            thinking_seconds: float = 0):
        """
        v2.6 主流程：流式诊断一次回答。
        逐条 yield 诊断消息；结束时自动 record_answer，
        并把 Diagnostician 产出的 follow_up_question 暂存到 pending_follow_up。
        v5.0: 注入简历证据包 + 不会答恢复信号。
        v6.1: from_voice=True 时诊断注入 ASR 容错评分话术。
        """
        q = self.current_question
        question_text = q.get("question", "") if isinstance(q, dict) else str(q or "")
        question_type = self._get_question_type()
        recovery_requested = self.needs_recovery(answer_text)
        self._update_recovery_streak(recovery_requested)

        final_result = None
        async for msg in self.diagnosis.stream(
            question=question_text,
            answer=answer_text,
            resume_text=self.resume_text,
            jd_text=self.jd_text,
            weights=self.dim_weights,
            question_type=question_type,
            evidence_package=self._evidence_for(answer_text),
            mode=self.mode,
            recovery_requested=recovery_requested,
            from_voice=from_voice,
            # v6.3: 面试官角色卡（视角 / 追问路径 / 不会问清单）
            interviewer_role=self.get_interviewer_role_prompt(),
        ):
            if msg.get("type") == "diagnosis_done":
                final_result = msg.get("data")
            yield msg

        # v6.3: assisted 标记 —— 本题借助了恢复引导，分数照记但报告中披露
        self.record_answer(answer_text, final_result, thinking_seconds,
                           assisted=recovery_requested)
        if recovery_requested:
            self.recovery_active = True

    def handle_follow_up_answer(self, answer_text: str, thinking_seconds: float = 0):
        """
        记录追问的补充回答（main.py 契约）。
        追问补充不单独计为一道题，而是并入上一题的回答语境，
        避免"一次追问 = 一道题"扭曲轮次进度与均分。
        v6.2: 追问思考时长累加到本题（真实面试里"被追问后卡住多久"同样是有价值信号）。
        """
        self.last_answer_text = answer_text
        thinking = _normalize_thinking_seconds(thinking_seconds)
        # v8.x: 保留追问问题文本，供复盘还原"面试官追问了什么"。
        # 此前只存追问回答，问题文本丢失，导致报告/复盘完全看不到追问内容。
        fu_question = (self.pending_follow_up or "").strip()
        if self.answer_history:
            h = self.answer_history[-1]
            h.setdefault("follow_ups", []).append(answer_text)
            if fu_question:
                h.setdefault("follow_up_questions", []).append(fu_question)
            if thinking > 0:
                fu_key = "follow_up_thinking_seconds"
                h[fu_key] = round(float(h.get(fu_key, 0)) + thinking, 1)
                h["thinking_seconds"] = round(float(h.get("thinking_seconds", 0)) + thinking, 1)
            # 同步到诊断记录，保证报告 qaBreakdown 与 answer_history 一致
            if self.all_diagnoses and thinking > 0:
                d = self.all_diagnoses[-1]
                d["thinking_seconds"] = round(float(d.get("thinking_seconds", 0)) + thinking, 1)
        if self.round_answers:
            self.round_answers[-1] = f"{self.round_answers[-1]}\n[追问补充] {answer_text}"
        self.pending_follow_up = ""

    def mark_follow_up_skipped(self, follow_up_question: str = "") -> None:
        """
        v7.0.2: 记录"追问被跳过"（测评问题 #1，方案 C：跳过留痕）。

        真实面试里"被追问却回避"本身就是负面信号。这里不扣分（评分口径
        保持"追问补充不重评"的既有设计），但把"面试官追问了、候选人没接"
        这一事实**显式落进本题诊断记录**，综合报告与分享页据此如实披露，
        让"回避"不再零成本、零痕迹。

        follow_up_question：被跳过的追问文本。追问推送时 generate_follow_up
        已清空 pending_follow_up，故由调用方（main.py 的 skip 分支）传入。
        """
        skipped_q = str(follow_up_question or "").strip() or str(self.pending_follow_up or "").strip()
        self.pending_follow_up = ""
        if not self.all_diagnoses:
            return
        d = self.all_diagnoses[-1]
        d["follow_up_skipped"] = True
        if skipped_q:
            d["skipped_follow_up"] = skipped_q

    # ===== 追问判断 =====

    def should_follow_up(self, answer_text: str = "", diagnosis: dict | None = None) -> bool:
        """
        是否需要追问。兼容 main.py 的两参调用与内部无参调用。
        v2.6: 优先采信流式诊断直接产出的 follow_up_question，避免二次 LLM 往返。
        v6.0: 采信诊断同轮产出的 next_action 三态（follow_up/next_question/complete）：
          - 模型产出追问文本 → 追问（同轮决策，最高优先）；
          - next_question/complete 且无追问文本 → 尊重模型推进决策，
            不再因低分强行追问；但回答过短仍强制追问，防止敷衍回答被"放行"；
          - 未声明 → 走原有阈值规则兜底（向后兼容）。
        """
        # v6.3: 连续恢复达阈值时，"建议跳过当前方向"是保护性干预而非追问，
        # 必须允许突破 FOLLOW_UP_MAX_COUNT —— 否则它恰好会被"第 3 次追问"拦掉，
        # 保护机制在最需要它的时刻失效。
        if self.recovery_streak >= RECOVERY_SKIP_THRESHOLD and not self._recovery_advice_done:
            return True

        if self.follow_up_count >= config.FOLLOW_UP_MAX_COUNT:
            return False

        # v6.2: 收尾阶段工程强控 —— 一律不再追问（含"回答过短强制追问"）。
        # 收尾轮（反问收尾/自定义环节）答完即收束，避免最后一题被无限追问拖住。
        if self.is_closing_round():
            return False

        diag = diagnosis if diagnosis is not None else (
            self.round_diagnoses[-1] if self.round_diagnoses else None
        )

        if diag and str(diag.get("follow_up_question", "") or "").strip():
            return True

        answer = answer_text or self.last_answer_text
        if len(answer.strip()) < config.FOLLOW_UP_MIN_LENGTH:
            return True

        if diag:
            # v6.0: 模型明确决定"进入下一题/收束议题"时，低分不再触发强制追问
            if str(diag.get("next_action", "") or "").strip() in ("next_question", "complete"):
                return False
            score = diag.get("overall_score", 0)
            if score and score < config.FOLLOW_UP_SCORE_THRESHOLD:
                return True

        return False

    async def generate_follow_up(self, diagnosis: dict | None = None) -> str:
        """
        获取追问文本。
        v2.6: 若流式诊断已带出追问，直接复用（零额外调用）；否则回退单独生成。
        v6.2: 输出净化 + 输出约束注入 —— 追问直接进 TTS，必须无 Markdown/舞台提示/垫词。
        """
        self.follow_up_count += 1

        diag = diagnosis if diagnosis is not None else (
            self.round_diagnoses[-1] if self.round_diagnoses else None
        )
        preset = self.pending_follow_up or (
            str(diag.get("follow_up_question", "") or "").strip() if diag else ""
        )
        if preset:
            self.pending_follow_up = ""
            return sanitize_spoken_text(preset)

        weak_name = ""
        if diag:
            weak_name = diag.get("weakest_dimension_name", "")

        # v6.3: 追问的两个自由度必须分开注入，否则 7 种风格只会"语气不同、结构同构"：
        #   问什么 ← 薄弱维度（weak_name，来自诊断）
        #   怎么问 ← 角色追问路径（followup_chain，来自面试官角色卡）
        role_prompt = self.get_interviewer_role_prompt()
        focus_line = f"\n本次追问要打的点（问什么）：候选人的薄弱环节【{weak_name}】。" if weak_name else ""

        try:
            follow_up = await asyncio.to_thread(
                self.llm.chat,
                (
                    f"{role_prompt}\n"
                    "你需要对候选人刚才的回答进行追问。"
                    "追问应当像真实面试官的追问，自然、简短、直击要害，不超过 50 字。"
                    "追问必须显式引用候选人回答里的具体词汇、数字或项目名（如\"你刚才提到 XX\"），"
                    "严禁空泛的套路式追问。\n"
                    + OUTPUT_CONSTRAINTS
                    + focus_line
                ),
                (
                    f"候选人刚才的回答：{self.last_answer_text[:500]}\n\n"
                    "请给出一个自然的追问，直接输出追问本身，不要任何前缀。"
                ),
                0.8,
                200,
                None,
                "interview",   # v6.2: 任务级模型绑定（实时链路，禁推理模型）
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"追问生成失败: {e}")
            return "能否再详细说说？"

        return sanitize_spoken_text(follow_up) or "能否再详细说说？"

    # ===== 题目生成 =====

    # ===== v6.3: 已问题目台账（备选题/换题的底层支撑）=====

    def avoid_questions_payload(self, limit: int = 8) -> list[str]:
        """最近问过的题目文本，供出题侧做负向约束。

        只取最近 limit 条：清单过长会挤占上下文预算，而模型对近期题目的
        重复倾向最明显，远期题目的边际收益很低。
        """
        return self.asked_questions[-limit:] if limit > 0 else list(self.asked_questions)

    def _note_asked_questions(self, questions: list[dict]) -> None:
        """登记本轮已问过的题目（文本 + 稳定指纹）。"""
        for q in questions or []:
            if not isinstance(q, dict):
                continue
            text = str(q.get("question", "") or "").strip()
            if not text:
                continue
            self.asked_questions.append(text)
            self.asked_question_hashes.add(content_hash(text))

    def _is_duplicate_question(self, text: str) -> bool:
        """题目是否已在本次会话问过（指纹比对）。"""
        text = (text or "").strip()
        return bool(text) and content_hash(text) in self.asked_question_hashes

    def set_long_term_memory(self, points: list[dict]) -> None:
        """注入历史未解决薄弱点（长期记忆闭环的"记 → 再练"）。

        拉取失败时传空列表即可：出题降级为"无历史记忆"模式，不阻断面试主流程。
        """
        self.long_term_memory = [p for p in (points or []) if isinstance(p, dict)]
        if self.long_term_memory:
            logger.debug("[session] %s 长期记忆回注入 %d 条未解决薄弱点",
                         self.session_id[:8], len(self.long_term_memory))

    def long_term_memory_for_prompt(self) -> list[dict]:
        """只在首轮注入历史薄弱点。

        一场会话内薄弱点集合不会变化，后续轮次再注入是纯粹的 token 浪费。
        """
        return self.long_term_memory if self.current_round == 0 else []

    # ===== v6.4: 出题依据透出（借鉴 MockFlow 面试页"本题依据"chip）=====

    def _anchor_labels(self) -> list[str]:
        """本场简历锚点覆盖的类别标签（按 ANCHOR_KEYS 固定顺序）。

        复用 question_gen 同款合并逻辑（LLM 五类输出优先、规则分类兜底），
        保证"本题依据"里说的锚点类别与出题 prompt 实际注入的一致。
        """
        raw = self.resume_points.get("anchors")
        flat = (list(self.resume_points.get("deep_dive_points") or [])
                + list(self.resume_points.get("vague_points") or []))
        merged = merge_anchor_sources(raw, flat)
        return [ANCHOR_META[k]["label"] for k in ANCHOR_KEYS if merged.get(k)]

    def question_basis(self, q: dict) -> str:
        """拼装"本题依据"说明，供前端在题目卡片上实时透出（v6.4）。

        刻意用**确定性拼装**而非让 LLM 自报依据：模型自报会编造
        （比如明明按锚点出题却说"根据 JD"），而压力题/破冰题/薄弱维度补强
        都是工程侧已知的事实，不需要也不应该交给模型描述。

        优先级：特殊题（压力/破冰/教练）> 薄弱维度补强 > JD 缺口 > 简历锚点。
        返回空串表示该题无可靠依据可说（前端不渲染 chip，宁缺毋谎）。
        """
        if not isinstance(q, dict):
            return ""
        if q.get("is_pressure") or q.get("question_type") == "pressure":
            topic = str(q.get("topic") or "").strip()
            return f"压力题，不基于简历与 JD（{topic}）" if topic else "压力题，不基于简历与 JD"
        qtype = str(q.get("question_type") or "")
        if qtype == "self_intro":
            return "固定破冰题"
        if qtype == "coach_tip":
            return "教练模式知识点讲解"
        parts: list[str] = []
        focus = str(q.get("focus_dimension_name") or "").strip()
        if focus:
            parts.append(f"薄弱维度补强：{focus}")
        elif self.jd_gaps:
            parts.append("优先考察 JD 缺口：" + "、".join(self.jd_gaps[:2]))
        labels = self._anchor_labels()
        if labels:
            parts.append("结合简历锚点（" + "、".join(labels[:3]) + "）")
        return "；".join(parts)

    async def generate_questions(self) -> list[dict]:
        info = self.current_round_info()
        questions = await generate_round_questions(
            llm_client=self.llm,
            resume_text=self.resume_text,
            jd_text=self.jd_text,
            round_idx=self.current_round,
            round_name=info["name"],
            count=info["question_count"],
            mode=self.mode,
            type_mix=self.question_type_mix,
            closing_instruction=self.closing_instruction(),   # v6.2 收尾阶段强控
            difficulty_instruction=self.difficulty_instruction(),  # v6.5 轮内难度自适应
            resume_points=self.resume_points,                 # v6.2 简历前置追问点
            avoid_questions=self.avoid_questions_payload(),   # v6.3 已问题目负向约束
            memory_points=self.long_term_memory_for_prompt(),  # v6.3 历史薄弱点回注入
            jd_gaps=self.jd_gaps,                             # v6.3 JD 匹配缺口优先考察
        )
        # v2.7: 教练模式——每轮开头插入知识点讲解
        if self.mode == "coach":
            tip = await generate_coach_tip(
                llm_client=self.llm,
                resume_text=self.resume_text,
                jd_text=self.jd_text,
                round_name=info["name"],
            )
            if tip:
                questions.insert(0, tip)

        # v2.7: 在首轮最前面插入自我介绍
        if self.include_self_intro and self.current_round == 0 and not self.self_intro_done:
            intro_q = {
                "index": -1,
                "question": "请你做一个简短的自我介绍，包括你的教育背景、核心技术栈以及最有代表性的项目经历。",
                "intent": "了解候选人的整体背景、沟通表达能力和职业定位",
                "question_type": "self_intro",
            }
            questions.insert(0, intro_q)
            self.self_intro_done = True

        questions = self._maybe_inject_pressure(questions)

        self.round_questions = questions
        self.current_question_idx = 0
        self._note_asked_questions(questions)   # v6.3: 登记已问题目，供后续换题去重
        return questions

    # ===== v6.3: 压力题注入 =====

    def _maybe_inject_pressure(self, questions: list[dict]) -> list[dict]:
        """按面试官攻击性概率在本轮追加一道压力题。

        三道闸门，任一不满足即不注入：
          1. 全局开关 / 整场限量 —— 压力题是调味不是主菜；
          2. 破冰轮（current_round == 0）与收尾轮不注入 —— 前者要让人放松，
             后者由 CLOSING_INSTRUCTION 强控收束，插入意外问题会破坏收尾；
          3. 按 attack_level 抽签 —— friendly/encouraging 风格注入概率为 0，
             否则会出现"友好型面试官突然刁难"的人设撕裂。

        追加而非替换：替换会让本轮题量少于配置，影响 min_questions 推进判定。
        """
        if not questions or not config.PRESSURE_QUESTION_ENABLED:
            return questions
        if self.pressure_injected >= config.PRESSURE_MAX_PER_SESSION:
            return questions
        if self.current_round == 0 or self.is_closing_round():
            return questions

        attack_level = self.current_interviewer().get("attack_level", 1)
        prob = config.PRESSURE_PROB_BY_ATTACK_LEVEL.get(attack_level, 0.0)
        if prob <= 0 or random.random() >= prob:
            return questions

        picked = sample_pressure_questions(
            count=1, exclude=self.asked_questions
        )
        if not picked:
            return questions

        pressure_q = dict(picked[0])
        pressure_q["index"] = len(questions)
        pressure_q["question_type"] = "pressure"
        questions.append(pressure_q)
        self.pressure_injected += 1
        logger.info("[session] %s 第 %d 轮注入压力题（%s，attack_level=%d）",
                    self.session_id[:8], self.current_round,
                    pressure_q.get("topic", ""), attack_level)
        return questions

    async def generate_extra_question(self) -> dict | None:
        """
        v2.6: 追加题按本轮薄弱维度定向生成，而不是再来一道同质题。
        v6.2: 收尾阶段强控不追加题（收尾轮的 max_extra_questions 本就是 0，
              此处为双保险，防止模式中途切换导致按错误配置追加）。
        """
        if self.is_closing_round():
            return None

        info = self.current_round_info()
        weak_key, weak_evidence = self.round_weak_dimension()

        avoid = self.avoid_questions_payload()
        questions = await generate_round_questions(
            llm_client=self.llm,
            resume_text=self.resume_text,
            jd_text=self.jd_text,
            round_idx=self.current_round,
            round_name=info["name"],
            count=1,
            mode=self.mode,
            focus_dimension=weak_key or None,
            weak_evidence=weak_evidence,
            type_mix=self.question_type_mix,
            closing_instruction=self.closing_instruction(),
            avoid_questions=avoid,   # v6.3: 换题必须给出新题
        )
        # v6.3 备选题兜底：模型若无视【严禁重复】约束又吐出一道已问过的题，
        # 就把这道重复题本身追加进排除清单再要一次——给出具体反例比反复强调规则有效。
        # 只重试一次：重试是一次完整的 LLM 往返，再重复就不是约束力度的问题了。
        if questions and self._is_duplicate_question(str(questions[0].get("question", ""))):
            repeated = str(questions[0].get("question", "")).strip()
            logger.info("[session] %s 换题命中已问题，带重复样本重试一次", self.session_id[:8])
            retried = await generate_round_questions(
                llm_client=self.llm,
                resume_text=self.resume_text,
                jd_text=self.jd_text,
                round_idx=self.current_round,
                round_name=info["name"],
                count=1,
                mode=self.mode,
                focus_dimension=weak_key or None,
                weak_evidence=weak_evidence,
                type_mix=self.question_type_mix,
                closing_instruction=self.closing_instruction(),
                avoid_questions=avoid + [repeated],
            )
            if retried and not self._is_duplicate_question(str(retried[0].get("question", ""))):
                questions = retried

        if questions:
            q = questions[0]
            q["is_extra"] = True
            if weak_key:
                q["focus_dimension"] = weak_key
                q["focus_dimension_name"] = FOCUS_DIMENSION_NAMES.get(weak_key, "")
                q["reason"] = f"上一轮回答在「{DIM_NAMES.get(weak_key, weak_key)}」上失分较多，追加一道针对性问题"
            self.round_questions.append(q)
            self.extra_questions_added += 1
            self._note_asked_questions([q])   # v6.3: 换题结果同样登记，防止连续换出同一道
            return q
        return None

    # ===== 实时雷达数据（v2.6） =====

    def radar_snapshot(self) -> dict:
        """
        面试进行中的实时雷达数据：各维度累计均分 + 最新一题得分。
        供前端每题诊断后即时刷新雷达图。
        """
        acc: dict[str, list[float]] = {k: [] for k in DIM_KEYS}
        for d in self.all_diagnoses:
            for k, v in (d.get("dimensions") or {}).items():
                if k in acc and isinstance(v, (int, float)) and v > 0:
                    acc[k].append(float(v))

        average = {k: (round(sum(v) / len(v), 2) if v else 0) for k, v in acc.items()}
        latest_dims = {}
        if self.all_diagnoses:
            latest_dims = {
                k: (self.all_diagnoses[-1].get("dimensions") or {}).get(k, 0)
                for k in DIM_KEYS
            }

        return {
            "labels": [DIM_NAMES[k] for k in DIM_KEYS],
            "keys": DIM_KEYS,
            "average": average,
            "latest": latest_dims,
            "weights": dict(self.dim_weights),
            "weighted_overall": weighted_score(average, self.dim_weights),
            "answered_count": len(self.all_diagnoses),
        }

    # ===== 综合报告 =====

    def build_report(self) -> dict:
        return build_report(self)
