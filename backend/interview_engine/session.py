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

from ..config import config
from ..question_gen import generate_round_questions, FOCUS_DIMENSION_NAMES, generate_coach_tip
from ..dimension_weights import (
    DEFAULT_WEIGHTS,
    DIM_KEYS,
    DIM_NAMES,
    analyze_jd_weights,
    describe_weights,
    weighted_score,
)
from ..resume_retriever import build_evidence_package, ResumeRetriever
from .report import build_report

logger = logging.getLogger(__name__)

# v5.0: 不会答/示弱信号检测（对标 agent-interview-coach 的 coaching recovery）
UNCERTAIN_ANSWER_MARKERS = (
    "不会", "不懂", "没思路", "答不上来", "不知道", "不清楚",
    "没做过", "不太了解", "不了解", "没接触过", "忘了",
)


class InterviewSession:
    """单次面试会话的状态机 (v2.6 / v5.0)"""

    # ===== 生命周期 =====

    def __init__(self, session_id: str, resume_text: str, jd_text: str,
                 llm_client, diagnosis_engine, interview_style: str = "friendly",
                 db=None, mode: str = "simulation",
                 stage: str = "phone_screen",
                 include_self_intro: bool = False,
                 question_type_mix: dict = None):
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
        self._retriever: ResumeRetriever | None = None
        self.mode_changed = False                     # 最近一次是否切换过模式（前端可提示）

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
        }

    def get_interviewer_system_prompt(self) -> str:
        return self.current_interviewer().get("prompt_modifier", "")

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

    def record_answer(self, answer_text: str, diagnosis: dict | None = None):
        """记录一次回答与其诊断结果，并前移题目指针。"""
        self.round_answers.append(answer_text)
        self.last_answer_text = answer_text
        self.follow_up_count = 0  # 新题目，重置追问计数

        q = self.current_question
        question_text = q.get("question", "") if isinstance(q, dict) else str(q or "")

        self.answer_history.append({
            "round": self.current_round,
            "question_idx": self.current_question_idx,
            "question": question_text,
            "answer": answer_text,
        })

        if diagnosis:
            diag_with_round = copy.deepcopy(diagnosis)
            diag_with_round["round"] = self.current_round
            diag_with_round["round_name"] = self.current_round_info()["name"]
            diag_with_round["question_idx"] = self.current_question_idx
            diag_with_round["question"] = question_text
            self.round_diagnoses.append(diag_with_round)
            self.all_diagnoses.append(diag_with_round)
            self.pending_follow_up = str(diagnosis.get("follow_up_question", "") or "").strip()
            # v5.0: 薄弱点跨轮累计
            tags = diagnosis.get("weakness_tags") or []
            if tags:
                self.accumulate_weaknesses(tags)
        else:
            self.pending_follow_up = ""

        self.current_question_idx += 1

    # ===== v5.0: 简历证据 / 不会答恢复 / 多模式 =====

    def _evidence_for(self, answer_text: str) -> str:
        """按候选人当前回答检索简历，生成【本轮证据包】。"""
        if self._retriever is None:
            self._retriever = ResumeRetriever()
            if self.resume_text and self.resume_text.strip():
                self._retriever.add_document("简历", self.resume_text)
        return self._retriever.select_context(answer_text)

    def needs_recovery(self, answer_text: str) -> bool:
        """检测候选人是否表示"不会/不懂/没思路"，触发不会答恢复。"""
        if not answer_text:
            return False
        low = answer_text.strip().lower()
        return any(m in low for m in UNCERTAIN_ANSWER_MARKERS)

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

    async def handle_answer(self, answer_text: str) -> dict:
        """
        非流式处理一次回答（降级路径 / 兼容 main.py 契约）。
        流式主流程请使用 stream_answer()。
        v5.0: 注入简历证据包 + 不会答恢复信号。
        """
        q = self.current_question
        question_text = q.get("question", "") if isinstance(q, dict) else str(q or "")
        recovery_requested = self.needs_recovery(answer_text)

        diagnosis = await self.diagnosis.diagnose(
            question=question_text,
            answer=answer_text,
            resume_text=self.resume_text,
            jd_text=self.jd_text,
            weights=self.dim_weights,
            evidence_package=self._evidence_for(answer_text),
            mode=self.mode,
            recovery_requested=recovery_requested,
        )
        self.record_answer(answer_text, diagnosis)
        if recovery_requested:
            self.recovery_active = True
        return diagnosis

    async def stream_answer(self, answer_text: str):
        """
        v2.6 主流程：流式诊断一次回答。
        逐条 yield 诊断消息；结束时自动 record_answer，
        并把 Diagnostician 产出的 follow_up_question 暂存到 pending_follow_up。
        v5.0: 注入简历证据包 + 不会答恢复信号。
        """
        q = self.current_question
        question_text = q.get("question", "") if isinstance(q, dict) else str(q or "")
        question_type = self._get_question_type()
        recovery_requested = self.needs_recovery(answer_text)

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
        ):
            if msg.get("type") == "diagnosis_done":
                final_result = msg.get("data")
            yield msg

        self.record_answer(answer_text, final_result)
        if recovery_requested:
            self.recovery_active = True

    def handle_follow_up_answer(self, answer_text: str):
        """
        记录追问的补充回答（main.py 契约）。
        追问补充不单独计为一道题，而是并入上一题的回答语境，
        避免"一次追问 = 一道题"扭曲轮次进度与均分。
        """
        self.last_answer_text = answer_text
        if self.answer_history:
            self.answer_history[-1].setdefault("follow_ups", []).append(answer_text)
        if self.round_answers:
            self.round_answers[-1] = f"{self.round_answers[-1]}\n[追问补充] {answer_text}"
        self.pending_follow_up = ""

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
        if self.follow_up_count >= config.FOLLOW_UP_MAX_COUNT:
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
            return preset

        weak_name = ""
        if diag:
            weak_name = diag.get("weakest_dimension_name", "")

        try:
            follow_up = await asyncio.to_thread(
                self.llm.chat,
                (
                    f"{self.get_interviewer_system_prompt()}\n"
                    "你需要对候选人刚才的回答进行追问。"
                    "追问应当像真实面试官的追问，自然、简短、直击要害，不超过 50 字。"
                    + (f"\n请重点针对候选人的薄弱环节【{weak_name}】发问。" if weak_name else "")
                ),
                (
                    f"候选人刚才的回答：{self.last_answer_text[:500]}\n\n"
                    "请给出一个自然的追问，直接输出追问本身，不要任何前缀。"
                ),
                0.8,
                200,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"追问生成失败: {e}")
            return "能否再详细说说？"

        return follow_up.strip() if follow_up else "能否再详细说说？"

    # ===== 题目生成 =====

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

        self.round_questions = questions
        self.current_question_idx = 0
        return questions

    async def generate_extra_question(self) -> dict | None:
        """
        v2.6: 追加题按本轮薄弱维度定向生成，而不是再来一道同质题。
        """
        info = self.current_round_info()
        weak_key, weak_evidence = self.round_weak_dimension()

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
        )
        if questions:
            q = questions[0]
            q["is_extra"] = True
            if weak_key:
                q["focus_dimension"] = weak_key
                q["focus_dimension_name"] = FOCUS_DIMENSION_NAMES.get(weak_key, "")
                q["reason"] = f"上一轮回答在「{DIM_NAMES.get(weak_key, weak_key)}」上失分较多，追加一道针对性问题"
            self.round_questions.append(q)
            self.extra_questions_added += 1
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
