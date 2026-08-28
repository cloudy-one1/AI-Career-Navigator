"""
面试报告生成模块 v2.6
从诊断数据中提取五维度趋势、强项弱项、提升建议。

v2.6 变更：
  - 总分改为按 JD 动态权重加权，与面试过程中的评分口径一致
  - 强弱项判定引入权重（加权失分），高权重维度失分优先被点名
  - 报告输出携带权重明细，供前端展示"这个岗位更看重什么"
"""

import logging
from datetime import datetime

from ..dimension_weights import (
    DEFAULT_WEIGHTS,
    DIM_KEYS,
    DIM_NAMES,
    describe_weights,
    weighted_score,
)

logger = logging.getLogger(__name__)


def build_report(session) -> dict:
    """
    生成综合面试报告。
    参数 session 需包含: session_id, mode, style, interviewer_history,
                     rounds, all_diagnoses, dim_weights
    """
    weights = getattr(session, "dim_weights", None) or dict(DEFAULT_WEIGHTS)

    all_scores = []
    dimension_trends = {k: {"scores": [], "rounds": []} for k in DIM_KEYS}

    round_summaries = {}
    for d in session.all_diagnoses:
        r = d.get("round", 0)
        dims = d.get("dimensions", {}) or {}
        if not dims:
            continue

        # v2.6: 优先复用诊断时已算好的加权分，缺失时按当前权重补算
        score = d.get("overall_score")
        if not score or score <= 0:
            score = weighted_score(dims, weights)
        if score <= 0:
            continue

        all_scores.append(score)
        if r not in round_summaries:
            round_summaries[r] = {"scores": [], "count": 0}
        round_summaries[r]["scores"].append(score)
        round_summaries[r]["count"] += 1

        for k in dimension_trends:
            if k in dims and dims[k]:
                dimension_trends[k]["scores"].append(dims[k])
                dimension_trends[k]["rounds"].append(r)

    # 轮次汇总
    rounds = []
    for r_idx in sorted(round_summaries.keys()):
        s = round_summaries[r_idx]
        r_data = session.rounds[r_idx] if r_idx < len(session.rounds) else {}
        rounds.append({
            "round_index": r_idx,
            "round_name": r_data.get("name", f"第{r_idx + 1}轮"),
            "questions_count": r_data.get("question_count", 0),
            "answers_count": s["count"],
            "avg_score": round(sum(s["scores"]) / len(s["scores"]), 2) if s["scores"] else 0,
        })

    overall_avg = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0

    # 各维度均分（未加权，用于展示各维度真实水平）
    dim_avgs = {}
    for k, v in dimension_trends.items():
        if v["scores"]:
            dim_avgs[k] = round(sum(v["scores"]) / len(v["scores"]), 2)

    strengths, weaknesses = analyze_trends(dimension_trends, weights)
    suggestions = generate_suggestions(strengths, weaknesses, overall_avg, weights, dim_avgs)

    # 各维度趋势
    trends = []
    for k, v in dimension_trends.items():
        if v["scores"]:
            trends.append({
                "dimension": k,
                "dimension_name": DIM_NAMES.get(k, k),
                "weight": weights.get(k, 0.20),
                "scores": v["scores"],
                "rounds": v["rounds"],
            })

    # v5.0: 逐题标准答案沉淀（修复"参考答案沉淀"恒为空缺陷）
    detailed_qa = []
    for d in session.all_diagnoses:
        q_text = d.get("question", "") or ""
        rewritten = d.get("rewritten_answer", "") or ""
        if not rewritten:
            continue
        detailed_qa.append({
            "round": d.get("round", 0),
            "round_name": d.get("round_name", ""),
            "question": q_text,
            "rewritten_answer": rewritten,
            "key_changes": d.get("key_changes", []) or [],
            "weakness_tags": d.get("weakness_tags", []) or [],
            "overall_score": d.get("overall_score", 0),
        })

    # v5.0: 薄弱点跨轮累计标签（供前端薄弱点面板 + 复盘）
    weakness_tag_summary = []
    counts = getattr(session, "_weakness_counts", {}) or {}
    for tag, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        weakness_tag_summary.append({"tag": tag, "count": cnt})

    return {
        "session_id": session.session_id,
        "mode": getattr(session, "mode", "simulation"),
        "stage": getattr(session, "stage", "phone_screen"),
        "interviewer_style": getattr(session, "style", "friendly"),
        "interviewer_history": getattr(session, "interviewer_history", []),
        "total_rounds": len(rounds),
        "rounds": rounds,
        "overall_avg": overall_avg,
        "scoring": {
            "weighted": True,
            "weights": dict(weights),
            "weight_names": {k: DIM_NAMES[k] for k in DIM_KEYS},
            "weight_desc": describe_weights(weights),
            "weight_reason": getattr(session, "weight_reason", ""),
            "weight_source": getattr(session, "weight_source", "default"),
        },
        "dimension_averages": dim_avgs,
        "dimension_trends": trends,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
        "detailed_qa": detailed_qa,
        "weakness_tag_summary": weakness_tag_summary,
    }


def analyze_trends(dimension_trends: dict, weights: dict | None = None) -> tuple[list[str], list[str]]:
    """
    分析维度趋势，找出强项弱项。
    v2.6: 弱项按"加权失分"排序 —— 同样是 2.8 分，岗位更看重的维度会被优先点名。
    """
    w = weights or DEFAULT_WEIGHTS
    strengths, weaknesses = [], []
    dim_avgs = {}

    for k, v in dimension_trends.items():
        if v["scores"]:
            dim_avgs[k] = sum(v["scores"]) / len(v["scores"])

    if not dim_avgs:
        return strengths, weaknesses

    avg_of_avgs = sum(dim_avgs.values()) / len(dim_avgs)

    weak_items = []
    strong_items = []
    for k, avg in dim_avgs.items():
        name = DIM_NAMES.get(k, k)
        wk = w.get(k, 0.25)
        label = f"{name}（平均 {avg:.1f} 分，权重 {wk * 100:.0f}%）"
        if avg >= avg_of_avgs + 0.3:
            strong_items.append((avg * wk, label))
        elif avg <= avg_of_avgs - 0.3:
            weak_items.append(((5.0 - avg) * wk, label))

    strengths = [label for _, label in sorted(strong_items, key=lambda x: -x[0])]
    weaknesses = [label for _, label in sorted(weak_items, key=lambda x: -x[0])]

    return strengths, weaknesses


def generate_suggestions(strengths: list[str], weaknesses: list[str],
                         overall_avg: float, weights: dict | None = None,
                         dim_avgs: dict | None = None) -> str:
    """生成提升建议（v2.6: 结合岗位权重给出优先级）"""
    w = weights or DEFAULT_WEIGHTS
    parts = []

    if overall_avg < 2.5:
        parts.append("整体偏弱，建议先夯实基础知识，再练习面试表达。")
    elif overall_avg < 3.5:
        parts.append("整体及格水平，有提升空间。")
    else:
        parts.append("整体表现良好，继续保持。")

    parts.append(f"本岗位评分权重：{describe_weights(w)}（总分按此加权计算）。")

    if weaknesses:
        parts.append("需要重点关注（按对本岗位的影响排序）：" + "；".join(weaknesses))
    if strengths:
        parts.append("你的优势：" + "；".join(strengths))

    # 针对权重最高维度给出定向建议
    if dim_avgs:
        top_key = max(DIM_KEYS, key=lambda k: w.get(k, 0.25))
        top_score = dim_avgs.get(top_key)
        if top_score is not None and top_score < 3.5:
            parts.append(
                f"优先级最高：本岗位最看重「{DIM_NAMES[top_key]}」"
                f"（权重 {w.get(top_key, 0.25) * 100:.0f}%），而你在该维度仅 {top_score:.1f} 分，"
                f"{_dimension_advice(top_key)}"
            )

    parts.append(
        "通用建议：多使用 STAR 方法组织回答（情境-任务-行动-结果），"
        "每次回答尽量给出具体数字和量化指标。"
    )

    return "\n\n".join(parts)


def _dimension_advice(key: str) -> str:
    """针对单个维度的具体改进动作。"""
    return {
        "star_completeness": "建议每段经历都先交代背景与目标，最后必须收在可验证的结果上。",
        "quantification": "建议提前整理每个项目的关键数字（提升比例、耗时、规模、成本），回答时主动带出。",
        "logic_coherence": "建议采用'结论先行 + 分点论证'的结构，并说明方案取舍的原因。",
        "job_relevance": "建议逐条对照 JD 要求，为每项核心能力准备一段对应的亲身经历。",
        "professional_depth": "建议在描述技术方案时补充'为什么选这个方案而非其他'以及关键权衡的思考过程。",
    }.get(key, "建议围绕该维度做专项练习。")


def generate_review_markdown(report: dict) -> str:
    """v2.7: 生成复盘文件（Markdown 格式，侧重学习改进）"""
    lines = []
    lines.append("# 面试复盘报告")
    lines.append(f"\n**生成时间**: {report.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M'))}")
    lines.append(f"**面试模式**: {report.get('interview_mode', '模拟面试')}")
    lines.append(f"**总得分**: {report.get('overall_avg', 0):.2f} / 5.0")
    lines.append("\n---\n")

    # 1. 本轮诊断速览
    lines.append("## 一、诊断速览\n")
    for rd in report.get("rounds", []):
        rd_name = rd.get("round_name", "未知轮次")
        rd_score = rd.get("avg_score", 0)
        emoji = "🟢" if rd_score >= 4 else ("🟡" if rd_score >= 3 else "🔴")
        lines.append(f"- **{emoji} {rd_name}**: {rd_score:.2f} 分")
    lines.append("")

    # 2. 薄弱维度识别（v3.3: 对齐 build_report 实际 schema，
    #    旧代码读 rounds[].dimension_details —— 该字段不存在，导出恒为空）
    lines.append("## 二、薄弱维度（优先改进）\n")
    weights_map = (report.get("scoring") or {}).get("weights") or {}
    dim_avgs = report.get("dimension_averages") or {}
    weakness_items = []
    for dim_key, score in dim_avgs.items():
        if score < 3.5:
            name = DIM_NAMES.get(dim_key, dim_key)
            wk = weights_map.get(dim_key, 0.2)
            weakness_items.append(((5.0 - score) * wk,
                                   f"{name}（平均 {score:.2f} 分，权重 {wk * 100:.0f}%）",
                                   _dimension_advice(dim_key)))
    if weakness_items:
        weakness_items.sort(key=lambda x: -x[0])
        for _, label, advice in weakness_items[:3]:
            lines.append(f"- **{label}**")
            lines.append(f"  - 改进建议: {advice}")
    else:
        lines.append("- 各维度均在 3.5 分以上，无明显短板，继续保持！")
    lines.append("")

    # 3. 薄弱点标签汇总（v5.0: 跨轮累计）
    tag_summary = report.get("weakness_tag_summary") or []
    if tag_summary:
        lines.append("## 三、薄弱点标签（跨轮累计）\n")
        for item in tag_summary[:10]:
            tag = item.get("tag", "")
            cnt = item.get("count", 1)
            if tag:
                lines.append(f"- **{tag}**（出现 {cnt} 次）")
        lines.append("")

    # 4. 可背诵的标准答案
    lines.append("## 四、参考答案沉淀\n")
    lines.append(
        "> 以下是将你的回答优化后的标准版本，建议背诵核心要点。\n"
    )
    for qa in report.get("detailed_qa", []):
        q = qa.get("question", "")
        rewritten = qa.get("rewritten_answer", "")
        if rewritten:
            lines.append(f"### Q: {q}")
            lines.append(f"{rewritten}")
            lines.append("")

    # 5. 下次面试 TODO
    lines.append("## 五、下次面试 TODO\n")
    lines.append("- [ ] 针对薄弱维度专项练习")
    lines.append("- [ ] 熟背参考答案的核心结构")
    lines.append("- [ ] 用量化数据替换模糊描述")
    lines.append("- [ ] 练习 STAR 法则完整叙事")
    lines.append("")

    # 6. 原始报告链接
    lines.append("---\n")
    lines.append(
        "> 完整诊断数据见系统内的「综合报告」页面。"
    )

    return "\n".join(lines)
