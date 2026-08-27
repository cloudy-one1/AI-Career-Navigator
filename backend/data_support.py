"""
数据支撑模块：根据岗位关键词匹配相关技能要求（静态数据集）。
"""

import json
import os
from .config import config

# 启动时加载一次
_skills_data: dict = {}


def _load_skills():
    """加载静态技能数据。"""
    global _skills_data
    if _skills_data:
        return _skills_data
    if os.path.exists(config.SKILLS_DATA_PATH):
        with open(config.SKILLS_DATA_PATH, "r", encoding="utf-8") as f:
            _skills_data = json.load(f)
    return _skills_data


def match_skills(jd_keywords: list[str]) -> list[dict]:
    """
    根据 JD 关键词匹配岗位类型，返回推荐的技能要求。

    Args:
        jd_keywords: 从 JD 中提取的关键词列表

    Returns:
        匹配到的岗位类型及其推荐技能 [{position: str, skills: [str]}, ...]
    """
    data = _load_skills()
    if not data:
        return []

    matched = []
    # 计算每个岗位的命中率
    for position, info in data.items():
        if position == "通用":
            continue
        pos_keywords = info.get("keywords", [])
        if not pos_keywords:
            continue
        hits = sum(1 for kw in jd_keywords if kw.lower() in " ".join(pos_keywords).lower())
        if hits > 0:
            matched.append({
                "position": position,
                "skills": info.get("skills", []),
                "match_count": hits,
            })

    # 按匹配度排序，取前 3
    matched.sort(key=lambda x: x["match_count"], reverse=True)
    result = matched[:3]

    # 附上通用技能
    if "通用" in data:
        result.append({
            "position": "通用",
            "skills": data["通用"].get("skills", []),
            "match_count": 0,
        })

    return result


def get_all_positions() -> list[str]:
    """获取所有支持的岗位类型。"""
    data = _load_skills()
    return [k for k in data.keys() if k != "通用"]
