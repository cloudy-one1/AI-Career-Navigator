"""
动态难度调度器（v6.5，借鉴 interviewerAgent `internal/difficulty/scheduler.go`）。

对方的设计：三阶段（basic/experience/design）× 5 档难度，连续 2 次达标升档、
连续 2 次失手降档，阶段题数达标后升阶；难度与阶段作为【出题指令】注入 system prompt。

**本项目的关键取舍：只抄"轮内难度自适应"，不抄"阶段推进"。**
理由：我们的阶段/轮次推进是 v6.2 落地的**工程强控**（按轮次计数判定 + closing 强控），
如果再让难度调度器反过来决定阶段流转，就等于把已经收敛的可控性又交回给统计信号。
因此本模块只回答一件事：**当前这道题该出多难**。

与对方的两点实质差异：
1. **评分制不同**：对方是 0-100，我们是五维 1-5 加权分。阈值换算为
   ≥4.0 升档 / ≤2.0 降档 / 2.0~4.0 中性（中性同时清零两侧连续计数）。
2. **信号源不同（也是对方最大的坑）**：它苦于没有真实评分，只能用"回复长度"代理，
   导致整套调度是噪声（研读报告 §16.1）。我们直接用 `diagnosis_engine` 的加权总分。

**必须配套做的归因披露**：难度升降会改变出题分布，而诊断评分是固定标准——
候选人分数变低时，必须能分清是"他变差了"还是"难度升了一档"。
因此本模块导出 `trace`（每题的难度档），由报告披露、WS 推送变更事件。
"""

from __future__ import annotations

# 难度档描述（对齐本项目的诊断语境：不是"题更难"，而是"追问到哪一层"）
DIFFICULTY_DESCRIPTIONS = {
    1: "概念确认层：只确认是否了解、是否用过，不做深挖",
    2: "原理复述层：要求讲清机制与基本流程",
    3: "应用与权衡层：要求举例说明，并解释为什么这么选、为什么不选别的",
    4: "深挖与边界层：追问异常情况、性能边界、踩过的坑与真实排查过程",
    5: "开放设计层：无标准答案，考察技术视野、取舍判断与业务落地意识",
}


class DifficultyState:
    """调度器状态（可序列化，随会话持久化的语义一致）。"""

    def __init__(self, level: int = 3):
        self.level = level
        self.consec_up = 0      # 连续达标次数
        self.consec_down = 0    # 连续失手次数
        self.trace: list[dict] = []   # [{"score":…, "level":…}] 每题一条

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "consec_up": self.consec_up,
            "consec_down": self.consec_down,
            "trace": list(self.trace),
        }


class DifficultyScheduler:
    """轮内难度自适应：连续 N 次达标升档、连续 N 次失手降档。

    只管"这道题出多难"，不管"该进哪个阶段"——阶段归 v6.2 的工程强控。
    """

    def __init__(self, initial: int = 3, min_level: int = 1, max_level: int = 5,
                 up_score: float = 4.0, down_score: float = 2.0, consec: int = 2,
                 state: DifficultyState | None = None):
        self.min_level = min_level
        self.max_level = max_level
        self.up_score = up_score
        self.down_score = down_score
        self.consec = consec
        self.state = state or DifficultyState(level=initial)

    def record(self, score: float) -> tuple[bool, int]:
        """记录一次得分。返回 (是否变档, 方向) —— 方向 1=升, -1=降, 0=不变。

        无效分数（None/非数字/0）直接忽略：诊断失败不该被当成"得了 0 分"，
        否则会连续两次降到底档（这正是"用错误信号驱动调度"的典型后果）。
        """
        try:
            s = float(score)
        except (TypeError, ValueError):
            return False, 0
        if s <= 0:
            return False, 0

        st = self.state
        if s >= self.up_score:
            st.consec_up += 1
            st.consec_down = 0
        elif s <= self.down_score:
            st.consec_down += 1
            st.consec_up = 0
        else:
            # 中性区：两侧连续计数同时清零（避免隔一次达标就被累计升档）
            st.consec_up = 0
            st.consec_down = 0

        changed, direction = False, 0
        if st.consec_up >= self.consec and st.level < self.max_level:
            st.level += 1
            st.consec_up = 0
            changed, direction = True, 1
        elif st.consec_down >= self.consec and st.level > self.min_level:
            st.level -= 1
            st.consec_down = 0
            changed, direction = True, -1

        st.trace.append({"score": round(s, 2), "level": st.level})
        return changed, direction

    def build_prompt(self) -> str:
        """当前难度的出题指令片段（由会话层注入出题 prompt）。"""
        level = self.state.level
        desc = DIFFICULTY_DESCRIPTIONS.get(level, DIFFICULTY_DESCRIPTIONS[3])
        return (
            f"\n\n【出题难度指令】本轮当前难度档：{level}/{self.max_level}。\n"
            f"{desc}。\n"
            "只按当前档位的深度出题，不要擅自加深或放水；"
            "候选人答得好会在后续题里自然升档，不需要你提前加码。"
        )

    def summary(self) -> dict:
        """报告披露用：难度轨迹 + 峰值/终值（解决分数归因问题）。"""
        levels = [t["level"] for t in self.state.trace] or [self.state.level]
        return {
            "enabled": True,
            "initial_level": self.state.trace[0]["level"] if self.state.trace else self.state.level,
            "final_level": self.state.level,
            "peak_level": max(levels),
            "lowest_level": min(levels),
            "changed_times": len({t["level"] for t in self.state.trace}) - 1,
            "trace": list(self.state.trace),
        }
