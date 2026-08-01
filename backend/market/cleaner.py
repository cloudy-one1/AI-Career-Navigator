"""
[v3.0] 招聘数据清洗：薪资/经验/学历标准化 + 技能标签提取。
纯函数模块：不依赖网络与数据库，便于单元测试。
"""

import json
import logging
import re
from typing import Optional

from ..config import config

logger = logging.getLogger(__name__)

# ===== 薪资解析 =====
# 统一为"月薪千元" (min, max)；无法解析/面议 → (None, None)

_SALARY_SPLIT = re.compile(r"[-~—～]")


def _num_to_k(value: float, unit: str) -> float:
    """数值 + 单位 → 千元"""
    if unit == "万":
        return value * 10
    if unit in ("千", "K", "k"):
        return value
    if unit == "元":
        return value / 1000
    # 无单位启发：>=1000 视为元，否则视为 K
    return value / 1000 if value >= 1000 else value


def _parse_segment(seg: str, fallback_unit: str = "") -> Optional[float]:
    """解析单侧薪资片段，如 '1.5万' / '8千' / '25K' / '8000'"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万|千|K|k|元)?", seg)
    if not m:
        return None
    return _num_to_k(float(m.group(1)), m.group(2) or fallback_unit)


def _plausible(k: Optional[float]) -> bool:
    """月薪千元合理性：0.5K–500K"""
    return k is not None and 0.5 <= k <= 500


def parse_salary(raw: str) -> tuple[Optional[float], Optional[float]]:
    """
    解析薪资为月薪千元区间 (min, max)。

    支持形态：
      '1.5-2.5万·13薪' → (15, 25)      '15-25K' → (15, 25)
      '8千-1.2万'       → (8, 12)       '150-250元/天' → 日薪×21.75
      '20-30万/年'      → 年薪/12        '2万以上' → (20, None)
      '8000-12000元/月' → (8, 12)       '面议'/空 → (None, None)
    """
    if not raw or not raw.strip():
        return (None, None)
    s = raw.strip()
    if "面议" in s:
        return (None, None)

    # 日薪：X-Y元/天 → 月薪 ≈ 日薪 × 21.75
    if "天" in s:
        parts = _SALARY_SPLIT.split(s, maxsplit=1)
        if len(parts) == 2:
            lo = _parse_segment(parts[0], "元")
            hi = _parse_segment(parts[1], "元")
            if lo and hi:
                return (round(lo * 21.75, 2), round(hi * 21.75, 2))
        return (None, None)

    # 年薪：X-Y万/年 → 月薪 = 年薪 / 12（左侧缺省单位取右侧，同标准区间）
    if "/年" in s or "年薪" in s:
        parts = _SALARY_SPLIT.split(s, maxsplit=1)
        if len(parts) == 2:
            m_right = re.search(r"(万|千|K|k|元)", parts[1])
            right_unit = m_right.group(1) if m_right else ""
            lo = _parse_segment(parts[0], right_unit)
            hi = _parse_segment(parts[1])
            if lo and hi:
                return (round(lo / 12, 2), round(hi / 12, 2))
        return (None, None)

    # 只有下限：'2万以上'
    if "以上" in s:
        k = _parse_segment(s)
        return (k, None) if _plausible(k) else (None, None)

    # 标准区间 X-Y：单位可能只在右侧（'1.5-2.5万'），也可能两侧不同（'8千-1.2万'）
    parts = _SALARY_SPLIT.split(s, maxsplit=1)
    if len(parts) == 2:
        m_right = re.search(r"(万|千|K|k|元)", parts[1])
        right_unit = m_right.group(1) if m_right else ""
        lo = _parse_segment(parts[0], right_unit)
        hi = _parse_segment(parts[1])
        if _plausible(lo) and _plausible(hi):
            if lo > hi:
                lo, hi = hi, lo
            return (round(lo, 2), round(hi, 2))
    return (None, None)


# ===== 学历标准化 =====
# 有序枚举：不限 < 大专 < 本科 < 硕士 < 博士（代表最低要求）

EDU_LEVELS = ["不限", "大专", "本科", "硕士", "博士"]


def parse_education(raw: str) -> str:
    """归一化为最低学历要求枚举。'本科及以上' → '本科'；'学历不限' → '不限'"""
    if not raw:
        return "不限"
    s = raw.strip()
    if "博士" in s:
        return "博士"
    if "硕士" in s or "研究生" in s:
        return "硕士"
    if "本科" in s:
        return "本科"
    if "大专" in s or "专科" in s:
        return "大专"
    return "不限"


# ===== 经验标准化 =====

def parse_experience(raw: str) -> tuple[Optional[float], Optional[float]]:
    """
    解析经验要求为 (min_years, max_years)。
    '3-5年' → (3,5)；'5年以上' → (5,None)；'1年以下' → (0,1)；
    应届/在校/实习 → (0,0)；不限/无法解析 → (None,None)
    """
    if not raw:
        return (None, None)
    s = raw.strip()
    if "应届" in s or "在校" in s or "实习" in s:
        return (0.0, 0.0)
    if "不限" in s or "无需" in s:
        return (None, None)
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~—～]\s*(\d+(?:\.\d+)?)\s*年", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*年以上", s)
    if m:
        return (float(m.group(1)), None)
    m = re.search(r"(\d+(?:\.\d+)?)\s*年以下", s)
    if m:
        return (0.0, float(m.group(1)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*年", s)
    if m:
        v = float(m.group(1))
        return (v, v)
    return (None, None)


# ===== 技能标签提取 =====

_SKILLS_CACHE: Optional[dict] = None


def _load_skills_dict() -> dict:
    """加载技能词典 {关键词: 岗位类别}（惰性缓存，文件缺失时降级为空表）"""
    global _SKILLS_CACHE
    if _SKILLS_CACHE is None:
        _SKILLS_CACHE = {}
        try:
            with open(config.SKILLS_DATA_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for category, info in data.items():
                for kw in info.get("keywords", []):
                    _SKILLS_CACHE[kw] = category
        except Exception as e:
            logger.warning(f"技能词典加载失败，技能提取将只依赖 jobTags: {e}")
    return _SKILLS_CACHE


def extract_skills(text: str, job_tags: Optional[list] = None) -> list[str]:
    """
    从 JD 文本 + 官方 jobTags 提取技能标签。
    jobTags 直接采信；自由文本用技能词典做大小写不敏感匹配。
    """
    skills: set[str] = set()
    for tag in (job_tags or []):
        tag = str(tag).strip()
        if tag:
            skills.add(tag)
    if text:
        lower = text.lower()
        for kw in _load_skills_dict():
            if kw.isascii():
                # 英文关键词用词边界匹配：避免 django 误中 Go、mysql 误中 SQL
                if re.search(rf"(?<![A-Za-z0-9+#]){re.escape(kw.lower())}(?![A-Za-z0-9+#])",
                             lower):
                    skills.add(kw)
            elif kw.lower() in lower:
                skills.add(kw)
    return sorted(skills)
