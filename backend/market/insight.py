"""
[v8.2] 市场图表 AI 解读（backend/market/insight.py，L2）。

设计要点：

- **section 注册表**：每张图表卡片 = 一条注册项（数据描述函数 + 指令）。
  新增一张卡片只需在此加一条 ``Section``，路由与前端交互自动继承，
  不必改 ``routers/market.py``。
- **TTL 缓存 + 显式失效**：解读结果 5 分钟内复用；采集/导入新数据后由调用方
  调 ``invalidate()``，避免对着已经变化的数据念旧结论。
- **按需调用**：不做全量预计算——8 个 section 全跑一遍纯烧 token，
  而多数用户只看其中 2~3 张。
- **失败可降级**：无 Key / LLM 异常 / 数据不足一律返回 ``{"error": ...}``，
  由前端决定展示文案，**绝不影响图表本身的渲染**。

L2 层：仅依赖 L1（llm_client）与同层（analytics），禁止依赖 L3/L4。
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..llm_client import llm_client
from . import analytics

logger = logging.getLogger(__name__)

# 解读结果缓存时间（秒）。图表数据本身不缓存——SQL 聚合是毫秒级，
# 真正贵的是 LLM 调用，所以只缓存解读文本。
_TTL = 300.0

# { (section, keyword): (timestamp, result) }
_CACHE: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()

_SYSTEM = """你是一名招聘市场数据分析师，服务于求职者。
用户会给你一组从本地岗位库统计出的真实数据，请你基于**且仅基于**这些数据做解读。

硬约束：
1. 只使用给定数据里出现的数字，禁止编造、估算或引用任何外部数据；
2. 某个维度数据为 0 或缺失，就直说"该维度暂无数据"，不要脑补；
3. 结论必须落到求职决策上（选方向 / 选城市 / 谈薪资 / 补技能），不要复述数字；
4. 150-300 字，中文，直接说结论，不要问候语、不要小标题；
5. **不要使用任何 Markdown 标记**（不要用 #、*、-、数字序号），
   需要分段时用空行分隔即可；
6. 描述规模时用"本库 N 条岗位"限定样本范围，不得泛化为"整个市场"。

输出 JSON：{"text": "你的解读"}"""


# ============================================================
# 数据描述函数（纯函数：charts dict → 描述文本，可单测）
# ============================================================

def _top(items: list, limit: int) -> list:
    return (items or [])[:limit]


def _describe_overview(charts: dict) -> str:
    total = charts.get("total", 0)
    if not total:
        return ""
    cities = "、".join(f"{c['city']}({c['cnt']})" for c in _top(charts.get("city"), 5))
    skills = "、".join(f"{s['skill']}({s['count']})" for s in _top(charts.get("skill"), 8))
    edu = max(charts.get("education") or [], key=lambda x: x["count"], default=None)
    salary = [s for s in (charts.get("salary") or []) if s["count"] > 0]
    hot_band = max(salary, key=lambda x: x["count"], default=None)
    exp = max((charts.get("experience") or []), key=lambda x: x["count"], default=None)

    parts = [f"本库共 {total} 条岗位。"]
    if cities:
        parts.append(f"城市 Top5：{cities}。")
    if hot_band:
        parts.append(f"岗位最集中的薪资档：{hot_band['label']}（{hot_band['count']}个）。")
    if edu and edu["count"]:
        parts.append(f"学历要求最多：{edu['label']}（{edu['count']}个）。")
    if exp and exp["count"]:
        parts.append(f"经验要求最多：{exp['label']}（{exp['count']}个）。")
    if skills:
        parts.append(f"高频技能：{skills}。")
    return "\n".join(parts)


def _describe_salary(charts: dict) -> str:
    items = [s for s in (charts.get("salary") or []) if s["count"] > 0]
    if not items:
        return ""
    total = sum(s["count"] for s in items)
    return (
        f"薪资分布（共 {total} 条有薪资数据的岗位，单位千元/月）："
        + "、".join(f"{s['label']} {s['count']}个" for s in items)
    )


def _describe_education(charts: dict) -> str:
    items = [e for e in (charts.get("education") or []) if e["count"] > 0]
    if not items:
        return ""
    return "学历分布：" + "、".join(f"{e['label']} {e['count']}个" for e in items)


def _describe_experience(charts: dict) -> str:
    items = [e for e in (charts.get("experience") or []) if e["count"] > 0]
    if not items:
        return ""
    return "经验要求分布：" + "、".join(f"{e['label']} {e['count']}个" for e in items)


def _describe_city(charts: dict) -> str:
    items = _top(charts.get("city"), 10)
    if not items:
        return ""
    total = charts.get("total", 0)
    return (
        f"本库共 {total} 条岗位，城市分布 Top10："
        + "、".join(f"{c['city']} {c['cnt']}个" for c in items)
    )


def _describe_geo(charts: dict) -> str:
    """地图卡片：侧重区域集中与城市群，而非逐城市罗列。"""
    items = charts.get("city") or []
    if not items:
        return ""
    total = charts.get("total", 0)
    top = _top(items, 10)
    head = top[0]
    share = round(head["cnt"] / total * 100, 1) if total else 0
    return (
        f"本库共 {total} 条岗位，覆盖 {len(items)} 个城市。\n"
        f"岗位最多的城市是{head['city']}（{head['cnt']}个，占 {share}%）。\n"
        f"城市分布 Top10："
        + "、".join(f"{c['city']} {c['cnt']}个" for c in top)
    )


def _describe_skill(charts: dict) -> str:
    items = _top(charts.get("skill"), 20)
    if not items:
        return ""
    return "岗位标签/技能词频 Top20：" + "、".join(
        f"{s['skill']}({s['count']}次)" for s in items
    )


def _cross_desc(charts: dict, key: str, title: str) -> str:
    data = charts.get(key) or {}
    labels = data.get("labels") or []
    if not labels:
        return ""
    rows = []
    for i, lb in enumerate(labels):
        cnt = (data.get("counts") or [])[i] if i < len(data.get("counts") or []) else 0
        avg = (data.get("avg_salaries") or [])[i] if i < len(data.get("avg_salaries") or []) else 0
        if cnt:
            rows.append(f"{lb} 平均{avg}K（{cnt}个）")
    if not rows:
        return ""
    return f"{title}：" + "；".join(rows)


def _describe_cross_exp(charts: dict) -> str:
    return _cross_desc(charts, "cross_exp", "经验 vs 平均薪资")


def _describe_cross_edu(charts: dict) -> str:
    return _cross_desc(charts, "cross_edu", "学历 vs 平均薪资")


def _describe_keyword(charts: dict) -> str:
    items = charts.get("keyword_dist") or []
    if not items:
        return ""
    return "已采集关键词分布：" + "、".join(f"{k['keyword']} {k['cnt']}个" for k in items)


# ============================================================
# section 注册表
# ============================================================

@dataclass(frozen=True)
class Section:
    key: str
    title: str
    describe: Callable[[dict], str]
    instruction: str


SECTIONS: dict[str, Section] = {
    s.key: s for s in (
        Section(
            key="overview", title="市场总览",
            describe=_describe_overview,
            instruction="请给出整体判断：这批岗位的整体画像是什么（什么城市、什么薪距、什么学历门槛、"
                        "要什么技能），以及求职者据此应当如何定位自己的目标区间。",
        ),
        Section(
            key="salary", title="薪资分布",
            describe=_describe_salary,
            instruction="请分析主力薪资区间落在哪一档、高低薪各自占比、薪资结构是否两极分化，"
                        "并给出求职者谈薪时的锚点建议。",
        ),
        Section(
            key="education", title="学历分布",
            describe=_describe_education,
            instruction="请分析市场主流学历门槛是什么、高学历要求岗位占比多少，"
                        "以及学历不占优时应当靠什么弥补。",
        ),
        Section(
            key="experience", title="经验分布",
            describe=_describe_experience,
            instruction="请分析市场最需求的年资段是哪个、应届与资深各自的空间有多大，"
                        "并给出不同年资求职者的切入策略。",
        ),
        Section(
            key="city", title="城市分布",
            describe=_describe_city,
            instruction="请分析岗位在地域上的集中趋势、头部城市占比是否过高，"
                        "并给出求职者选择城市（或考虑异地机会）的具体建议。",
        ),
        Section(
            key="geo", title="岗位地理分布",
            describe=_describe_geo,
            instruction="请结合城市分布分析岗位集中在哪几个城市群（如京津冀/长三角/珠三角/成渝），"
                        "头部城市的集中度意味着什么，以及非头部城市求职者应当如何取舍"
                        "（本地机会少时是转远程、 relocate 还是换方向）。",
        ),
        Section(
            key="skill", title="热门技能",
            describe=_describe_skill,
            instruction="请分析这些高频标签里哪些是真正的硬技能、哪些只是福利与制度性描述，"
                        "并指出当下最值得优先补齐的 2-3 项技能。",
        ),
        Section(
            key="cross_exp", title="薪资 × 经验",
            describe=_describe_cross_exp,
            instruction="请分析薪资随经验增长的斜率：哪个年资段涨幅最大、是否存在平台期，"
                        "并给出跳槽时机上的建议。",
        ),
        Section(
            key="cross_edu", title="薪资 × 学历",
            describe=_describe_cross_edu,
            instruction="请分析学历带来的薪资溢价到底有多大、性价比如何，"
                        "并给出「是否值得为此提升学历」的务实判断。",
        ),
        Section(
            key="keyword", title="关键词分布",
            describe=_describe_keyword,
            instruction="请分析当前库里已采集了哪些方向、样本量是否足够支撑结论，"
                        "并指出还缺哪些方向的样本值得补采。",
        ),
    )
}


# ============================================================
# 对外接口
# ============================================================

def invalidate() -> None:
    """清空全部解读缓存。采集完成或导入新数据后必须调用。"""
    with _lock:
        _CACHE.clear()
    logger.debug("市场 AI 解读缓存已清空")


def _evict_expired(now: float) -> None:
    """惰性清理过期条目，防止缓存随关键词组合无限膨胀。"""
    expired = [k for k, (ts, _) in _CACHE.items() if now - ts > _TTL]
    for k in expired:
        _CACHE.pop(k, None)


async def analyze(section: str, keyword: Optional[str] = None,
                  fresh: bool = False) -> dict:
    """
    对指定图表 section 生成 AI 解读。

    返回:
        成功 -> {"section", "title", "text", "cached", "model"}
        失败 -> {"error": "<原因>", "section"}
    调用方（路由/前端）负责把 error 展示为友好文案，**不要抛异常**——
    解读是增强能力，失败不应影响图表本身。
    """
    spec = SECTIONS.get(section)
    if spec is None:
        return {"error": f"无效的解读类型: {section}", "section": section}

    cache_key = (section, keyword or "")
    now = time.time()

    if not fresh:
        with _lock:
            hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _TTL:
            return {**hit[1], "cached": True}

    charts = await analytics.get_charts(keyword=keyword)
    if not charts.get("total"):
        return {"error": "当前市场库为空，请先采集或导入岗位数据", "section": section}

    desc = (spec.describe(charts) or "").strip()
    if not desc:
        return {"error": "该维度暂无足够数据支撑解读", "section": section}

    user_prompt = f"{desc}\n\n{spec.instruction}"

    # chat_json 是同步阻塞调用，必须丢进线程——否则会卡死整个 FastAPI 事件循环。
    # 外层再兜一层 try：解读是增强能力，任何异常都只应降级，不能把请求打穿。
    try:
        data = await asyncio.to_thread(
            llm_client.chat_json, _SYSTEM, user_prompt, 0.3, 900, "market"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("市场解读调用异常 section=%s: %s", section, e)
        return {"error": f"AI 解读暂时不可用（{type(e).__name__}）", "section": section}

    if not isinstance(data, dict) or "error" in data:
        reason = (data or {}).get("error", "AI 解读暂时不可用") if isinstance(data, dict) else "AI 解读暂时不可用"
        logger.warning("市场解读失败 section=%s: %s", section, reason)
        return {"error": str(reason), "section": section}

    text = str(data.get("text") or "").strip()
    if not text:
        return {"error": "AI 未返回有效解读内容", "section": section}

    result = {
        "section": section,
        "title": spec.title,
        "text": text,
        "cached": False,
        "model": llm_client.resolve_task_model("market"),
    }

    with _lock:
        _CACHE[cache_key] = (time.time(), result)
        _evict_expired(time.time())

    logger.info("市场解读完成 section=%s keyword=%s 字数=%d", section, keyword or "(全部)", len(text))
    return result
