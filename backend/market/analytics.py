"""
[v8.2] 市场图表数据聚合（backend/market/analytics.py，L2）。

职责：为「数据分析」视图提供**一次性取回、可直接渲染**的图表数据。

与 store.get_stats() 的分工（两者刻意分开，不要合并）：
  - ``store.get_stats()``：面向 Gap 分析的精简摘要，被 ``gap_analyzer`` 依赖，
    字段契约有回归测试钉住，不随图表需求变动；
  - 本模块：面向可视化的完整分布，维度更全、分档更细，可随卡片需求自由演进。
  "给 LLM 看的摘要"与"给人看的图表"关注点不同，合并只会互相牵制。

设计原则：
  - 纯 SQL 取行 + Python 侧聚合（与 store.get_stats 的技能聚合风格一致）；
    样本量在万级以内，换来的是分档顺序完全可控、空档位也能输出 0。
  - 空库返回规范空态（total=0 + 各维度空数组），前端无需特判。
  - L2 层：仅依赖 L1（config）与同层（cleaner / store），禁止依赖 L3/L4。
"""

import json
import logging
from collections import Counter
from typing import Optional

from .cleaner import extract_city, parse_education
from .store import get_db

logger = logging.getLogger(__name__)

# 单次聚合的行数上限：防御性保护，避免极端库把内存撑爆
_MAX_ROWS = 20000

# ===== 分档定义（标签顺序即图表 X 轴顺序，改动会影响前端刻度）=====

# 薪资档（月薪千元），8 档口径与 job-crawler 一致
SALARY_BINS = (
    (0, 5, "<5K"),
    (5, 8, "5-8K"),
    (8, 11, "8-11K"),
    (11, 14, "11-14K"),
    (14, 17, "14-17K"),
    (17, 20, "17-20K"),
    (20, 23, "20-23K"),
    (23, None, "23K+"),
)

# 经验档（以最低要求 exp_min 为依据，单位：年）
EXP_LABELS = ("应届/在校", "1年以下", "1-3年", "3-5年", "5-10年", "10年以上", "经验不限")

# 学历档（复用 cleaner 的归一化枚举，保证与 Gap 分析口径一致）
EDU_LABELS = ("不限", "大专", "本科", "硕士", "博士")

TOP_N_CITY = 15
TOP_N_SKILL = 20
TOP_N_KEYWORD = 10


def salary_bucket(mid: float) -> str:
    """薪资中位数 → 档位标签。左闭右开，末档开放。"""
    for lo, hi, label in SALARY_BINS:
        if mid >= lo and (hi is None or mid < hi):
            return label
    return SALARY_BINS[-1][2]


def exp_bucket(exp_min: Optional[float], exp_max: Optional[float]) -> str:
    """
    经验要求 → 档位标签。

    口径对齐 ``cleaner.parse_experience`` 的约定：
      (None, None) → 经验不限；(0, 0) → 应届/在校/实习。
    """
    if exp_min is None and exp_max is None:
        return "经验不限"
    if exp_min == 0 and exp_max == 0:
        return "应届/在校"
    v = exp_min if exp_min is not None else 0.0
    if v < 1:
        return "1年以下"
    if v < 3:
        return "1-3年"
    if v < 5:
        return "3-5年"
    if v < 10:
        return "5-10年"
    return "10年以上"


def _ordered(counter: Counter, labels) -> list[dict]:
    """按固定档位顺序输出（含 0 值档位），保证图表 X 轴刻度稳定不跳变。"""
    return [{"label": lb, "count": counter.get(lb, 0)} for lb in labels]


def _cross(buckets: dict, labels) -> dict:
    """分档 → {labels, avg_salaries, counts}，供双轴图（柱=数量、线=均薪）使用。"""
    out_labels, avgs, counts = [], [], []
    for lb in labels:
        vals = buckets.get(lb) or []
        out_labels.append(lb)
        counts.append(len(vals))
        avgs.append(round(sum(vals) / len(vals), 1) if vals else 0)
    return {"labels": out_labels, "avg_salaries": avgs, "counts": counts}


async def get_charts(keyword: Optional[str] = None) -> dict:
    """
    一次性返回全部分析卡片所需的图表数据。

    返回结构（空库时为 total=0 + 各维度空数组）:
        {
          total, keyword,
          salary:     [{label, count}]          8 档
          education:  [{label, count}]          5 档
          experience: [{label, count}]          7 档
          city:       [{city, cnt}]             归一化后 Top15
          skill:      [{skill, count}]          Top20
          cross_exp:  {labels, avg_salaries, counts}
          cross_edu:  {labels, avg_salaries, counts}
          keyword_dist: [{keyword, cnt}]        Top10
        }
    """
    where = "WHERE keyword = ?" if keyword else ""
    params = [keyword] if keyword else []

    salary_counter: Counter = Counter()
    edu_counter: Counter = Counter()
    exp_counter: Counter = Counter()
    city_counter: Counter = Counter()
    skill_counter: Counter = Counter()
    kw_counter: Counter = Counter()
    exp_salary: dict = {}
    edu_salary: dict = {}
    total = 0

    db = await get_db()
    try:
        async with db.execute(
            f"""SELECT keyword, city, salary_min, salary_max, exp_min, exp_max,
                       education, tags
                FROM job_postings {where} LIMIT {_MAX_ROWS}""",
            params,
        ) as cur:
            rows = await cur.fetchall()
    finally:
        await db.close()

    for r in rows:
        total += 1
        kw_counter[str(r["keyword"] or "未分类")] += 1

        city_name = extract_city(r["city"])
        if city_name:
            city_counter[city_name] += 1

        edu = parse_education(r["education"])
        edu_counter[edu] += 1

        exp_lb = exp_bucket(r["exp_min"], r["exp_max"])
        exp_counter[exp_lb] += 1

        s_min, s_max = r["salary_min"], r["salary_max"]
        if s_min is not None and s_max is not None:
            mid = (s_min + s_max) / 2
            salary_counter[salary_bucket(mid)] += 1
            exp_salary.setdefault(exp_lb, []).append(mid)
            edu_salary.setdefault(edu, []).append(mid)

        try:
            for t in json.loads(r["tags"] or "[]"):
                t = str(t).strip()
                if t:
                    skill_counter[t] += 1
        except Exception:  # noqa: BLE001 - 单条脏 tags 不应中断整批聚合
            continue

    logger.info("图表数据聚合完成: keyword=%s, rows=%d", keyword or "(全部)", total)

    return {
        "total": total,
        "keyword": keyword,
        "salary": _ordered(salary_counter, [lb for _, _, lb in SALARY_BINS]),
        "education": _ordered(edu_counter, EDU_LABELS),
        "experience": _ordered(exp_counter, EXP_LABELS),
        "city": [{"city": c, "cnt": n} for c, n in city_counter.most_common(TOP_N_CITY)],
        "skill": [{"skill": s, "count": n} for s, n in skill_counter.most_common(TOP_N_SKILL)],
        "cross_exp": _cross(exp_salary, EXP_LABELS),
        "cross_edu": _cross(edu_salary, EDU_LABELS),
        "keyword_dist": [{"keyword": k, "cnt": n} for k, n in kw_counter.most_common(TOP_N_KEYWORD)],
    }
