"""
[v3.1 NEW] 简历-岗位 Gap 分析器

六维度透明评分（带权重）：
  1. 技能匹配      — 35%  你的技能 vs JD 要求的技能栈
  2. 城市/地点    — 15%  你当前/期望城市 vs 岗位所在地
  3. 学历匹配      — 15%  学历层次 vs 岗位要求
  4. 经验年限      — 15%  工作经验 vs 岗位要求的年限
  5. 薪资预期      — 10%  期望薪资 vs 市场范围
  6. 可信度        — 10%  简历信息的一致性 / 是否有夸大嫌疑

每个维度输出：score(1-5)、evidence、gap、suggestion。

市场数据交叉参考：当 market.db 中有对应岗位数据时，自动注入薪资分位、
学历分布等作为"基准参照"，让用户知道自己在市场中的位置。

[学术诚信披露，2026-08] market.db 中的岗位数据来自本人此前已完成并提交的采集项目
（job-crawler）的 data.db，本次仅做管道整合（market/importer 字段映射 + store upsert），
**不含数据采集工作量**。若评审基于"本次周期实际产出了什么"，此部分可辩护性较弱，
已在此主动披露；详细口径见 README「已知局限」。
"""
import asyncio
import json
import logging
from typing import Optional

from .llm_client import LLMClient
from .market.store import get_stats as get_market_stats, query_jobs as query_market_jobs
from .market.service import find_relevant_snapshot

logger = logging.getLogger(__name__)

# ——— 维度定义 ———

GAP_DIMENSIONS = [
    {"key": "skills",    "name": "技能匹配",   "weight": 0.35},
    {"key": "location",  "name": "城市/地点",  "weight": 0.15},
    {"key": "education", "name": "学历匹配",   "weight": 0.15},
    {"key": "experience","name": "经验年限",   "weight": 0.15},
    {"key": "salary",    "name": "薪资预期",   "weight": 0.10},
    {"key": "credibility","name": "可信度",    "weight": 0.10},
]


# ——— Prompts ———

_GAP_SYSTEM = """你是一位专业的求职顾问，负责对候选人简历和目标岗位进行 Gap 分析。

请用中文输出，严格遵循以下 JSON 结构：

{
  "skills":     {"score":<1-5>, "evidence":"简历中有什么技能 vs JD需要什么技能", "gap":"差距描述", "suggestion":"补强建议"},
  "location":   {"score":<1-5>, "evidence":"简历中的城市 vs 岗位所在城市", "gap":"差距描述", "suggestion":"择城建议"},
  "education":  {"score":<1-5>, "evidence":"学历/专业 vs 岗位学历要求", "gap":"差距描述", "suggestion":"进修/考证建议"},
  "experience": {"score":<1-5>, "evidence":"工作年限/经历 vs 岗位经验要求", "gap":"差距描述", "suggestion":"经验补足建议"},
  "salary":     {"score":<1-5>, "evidence":"期望/当前薪资 vs 岗位薪资范围", "gap":"差距描述", "suggestion":"薪资谈判/让步建议"},
  "credibility":{"score":<1-5>, "evidence":"简历信息一致性/可信度评估", "gap":"差距描述", "suggestion":"简历优化建议"},
  "overall_assessment": "一句话总结：候选人离这个岗位有多远",
  "risk_level": "低/中/高"
}

评分标准（1-5）：
  5 = 完全匹配，无明显差距
  4 = 轻微差距，稍作调整即可
  3 = 中等差距，需要一定努力弥补
  2 = 较大差距，需要系统性提升
  1 = 严重不匹配，可能需要重新定位目标

市场数据（如有）仅作参考基准，评分仍以 JD 要求为准。"""


def _build_gap_user_prompt(resume: str, jd: str, market_snapshot: Optional[dict] = None) -> str:
    parts = [
        "以下是候选人简历：",
        "---简历---",
        resume[:4000],
        "---岗位描述---",
        jd[:3000],
    ]
    if market_snapshot:
        parts.append("---市场参考数据（同岗位真实招聘）---")
        parts.append(json.dumps(_compact_market_snapshot(market_snapshot), ensure_ascii=False, indent=2))
        parts.append("（以上市场数据供参考，以 JD 要求为主要评分依据）")

    parts.append("请按系统提示的格式输出 Gap 分析 JSON。")
    return "\n".join(parts)


def _compact_market_snapshot(ms: dict) -> dict:
    """压缩市场快照，只保留分析所需的核心字段"""
    compact: dict = {}
    if ms.get("avg_salary"):
        compact["平均薪资"] = f"{ms['avg_salary'].get('avg_k','?')}K"
        compact["薪资区间"] = f"{ms['avg_salary'].get('min_k','?')}-{ms['avg_salary'].get('max_k','?')}K"
    if ms.get("education_distribution"):
        compact["学历分布"] = {e["education"]: e["cnt"] for e in ms["education_distribution"]}
    if ms.get("top_skills"):
        compact["热门技能Top10"] = [s["skill"] for s in ms["top_skills"][:10]]
    if ms.get("total"):
        compact["样本量"] = ms["total"]
    return compact


# ——— 核心分析函数 ———

async def analyze_gap(
    resume_text: str,
    jd_text: str,
    *,
    keyword: Optional[str] = None,
    use_market: bool = True,
    llm_client: Optional[LLMClient] = None,
) -> dict:
    """
    核心 Gap 分析。

    参数：
      resume_text:  简历全文
      jd_text:      岗位描述全文
      keyword:      搜索关键词（用于市场数据查询）；为空则从 JD 中提取
      use_market:   是否尝试查询 market.db 获取基准数据

    返回：
      {
        "dimensions": [{key,name,weight,score,evidence,gap,suggestion}, ...],
        "overall_score": float,   # 加权总分 (1-5)
        "overall_assessment": str,
        "risk_level": str,
        "market_source": dict|null  # 若有市场数据则返回样本量与关键词
      }
    """
    # 1. 尝试获取市场基准数据
    market_snapshot = None
    market_source = None
    market_reference = None
    if use_market:
        try:
            kw = keyword or _extract_keyword_from_jd(jd_text)
            if kw:
                market_snapshot = await get_market_stats(keyword=kw)
                if market_snapshot and market_snapshot.get("total", 0) > 0:
                    market_source = {"keyword": kw, "total": market_snapshot["total"]}
                    market_reference = _build_market_reference(kw, market_snapshot, resume_text)
                    logger.info("Gap分析加载市场数据: keyword=%s, samples=%d", kw, market_snapshot["total"])
                else:
                    market_snapshot = None
        except Exception as e:
            logger.warning("市场数据查询失败（不影响主流程）: %s", e)

    # 2. LLM Gap 分析
    client = llm_client or LLMClient()
    user_prompt = _build_gap_user_prompt(resume_text, jd_text, market_snapshot)

    try:
        raw = await asyncio.to_thread(
            client.chat_json, _GAP_SYSTEM, user_prompt, 0.3, 2048, "market",
        )  # v6.2: 任务级模型绑定（岗位差距分析）
    except Exception as e:
        logger.error("Gap分析LLM调用失败: %s", e)
        return _fallback_gap_result(str(e))

    # 3. 规范化并计算加权总分
    dimensions = _normalize_dimensions(raw)
    overall = _compute_weighted_overall(dimensions)

    overall_assessment = raw.get("overall_assessment", "") or _fallback_assessment(overall)
    risk_level = raw.get("risk_level", "") or _infer_risk_level(overall)

    return {
        "dimensions": dimensions,
        "overall_score": round(overall, 2),
        "overall_assessment": overall_assessment,
        "risk_level": risk_level,
        "market_source": market_source,
        "market_reference": market_reference,
    }


# ——— 市场基准参照构建 ———

def _build_market_reference(keyword: str, stats: dict, resume_text: str) -> dict:
    """从市场统计数据构建前端可直接渲染的市场参照对象"""
    total = stats.get("total", 0)
    avg_salary = stats.get("avg_salary", {}) or {}
    top_cities = [c["city"] for c in stats.get("cities", [])[:5]]
    top_skills = [s["skill"] for s in stats.get("top_skills", [])[:10]]
    edu_dist = stats.get("education_distribution", [])[:5]

    # 生成一句话总结
    salary_summary = ""
    if avg_salary.get("avg_k"):
        salary_summary = f"市场均薪 {avg_salary['avg_k']}K (区间 {avg_salary.get('min_k','?')}-{avg_salary.get('max_k','?')}K)"
    top_edu = edu_dist[0]["education"] if edu_dist else "不限"

    summary = (
        f"基于 {total} 条「{keyword}」真实岗位数据"
        f"{'，' + salary_summary if salary_summary else ''}"
        f"，{top_edu} 学历占比最高。"
    )

    return {
        "keyword": keyword,
        "total_samples": total,
        "avg_salary_k": avg_salary.get("avg_k"),
        "salary_range": f"{avg_salary.get('min_k', '?')}-{avg_salary.get('max_k', '?')}K" if avg_salary.get("min_k") else "",
        "top_cities": top_cities,
        "education_distribution": [{"education": e["education"], "count": e["cnt"]} for e in edu_dist],
        "top_skills": top_skills,
        "summary": summary,
    }


def _extract_keyword_from_jd(jd: str) -> str:
    """从 JD 文本中提取最可能的搜索关键词（简单启发式）"""
    # 常见岗位关键词
    keywords = [
        "架构师", "Java", "Python", "前端", "后端", "全栈", "算法", "AI", "机器学习",
        "深度学习", "数据分析", "产品经理", "项目经理", "测试", "运维", "DBA",
        "Golang", "C++", "React", "Vue", "Node.js", "Spring", "Docker", "Kubernetes",
        "大数据", "Hadoop", "Spark", "Flutter", "iOS", "Android", "安全",
    ]
    jd_lower = jd.lower()
    for kw in keywords:
        if kw.lower() in jd_lower:
            return kw
    # fallback: 取标题第一行或前10个非停用词
    return ""


def _normalize_dimensions(raw: dict) -> list[dict]:
    """规范化维度输出，确保所有必要字段存在"""
    dims = []
    for dim in GAP_DIMENSIONS:
        key = dim["key"]
        d = raw.get(key, {})
        if not isinstance(d, dict):
            d = {}
        score = d.get("score", 3)
        try:
            score = max(1, min(5, int(score)))
        except (ValueError, TypeError):
            score = 3
        dims.append({
            "key": key,
            "name": dim["name"],
            "weight": dim["weight"],
            "score": score,
            "evidence": d.get("evidence", "") or "（未提供）",
            "gap": d.get("gap", "") or "（未提供）",
            "suggestion": d.get("suggestion", "") or "（未提供）",
        })
    return dims


def _compute_weighted_overall(dimensions: list[dict]) -> float:
    """计算六维度加权总分"""
    total = sum(d["score"] * d["weight"] for d in dimensions)
    # 权重和为 1.0，不需要除
    return total


def _fallback_gap_result(error: str) -> dict:
    """LLM 调用失败时的降级结果"""
    dims = []
    for dim in GAP_DIMENSIONS:
        dims.append({
            "key": dim["key"],
            "name": dim["name"],
            "weight": dim["weight"],
            "score": 3,
            "evidence": "",
            "gap": "",
            "suggestion": "",
        })
    return {
        "dimensions": dims,
        "overall_score": 3.0,
        "overall_assessment": f"Gap分析暂时不可用（{error}），请稍后重试",
        "risk_level": "未知",
        "market_source": None,
        "market_reference": None,
    }


def _fallback_assessment(score: float) -> str:
    if score >= 4.0:
        return "候选人高度匹配该岗位，可以考虑投递或争取更高级别。"
    elif score >= 3.0:
        return "候选人与岗位存在中等差距，建议针对性补强后投递。"
    else:
        return "候选人与岗位差距较大，建议先提升核心技能或考虑更匹配的岗位方向。"


def _infer_risk_level(overall: float) -> str:
    if overall >= 4.0:
        return "低"
    elif overall >= 3.0:
        return "中"
    else:
        return "高"
