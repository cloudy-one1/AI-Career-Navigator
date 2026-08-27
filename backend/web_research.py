"""
岗位画像研究模块 v2.5
使用 DuckDuckGo Instant Answer API 搜索岗位信息，通过 LLM 分析提炼面试要点。
无需 API Key，轻量级实现。

v3.1 降级：DDG 被墙时，从 skills_data.json 本地匹配 JD 关键词提取 key_skills，
不再返回空数组。
"""

import logging
import urllib.request
import urllib.parse
import json
import os
import re
from asyncio import to_thread
from pathlib import Path

logger = logging.getLogger(__name__)

# DuckDuckGo Instant Answer API (免费，无需 API Key)
DDG_API = "https://api.duckduckgo.com/"


# ── 本地降级：skills_data.json 关键词匹配 ──

_SKILLS_DATA: dict | None = None


def _load_skills_data() -> dict:
    """延迟加载 skills_data.json"""
    global _SKILLS_DATA
    if _SKILLS_DATA is not None:
        return _SKILLS_DATA
    skills_path = Path(__file__).parent / "skills_data.json"
    if skills_path.exists():
        try:
            _SKILLS_DATA = json.loads(skills_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载 skills_data.json 失败: {e}")
            _SKILLS_DATA = {}
    else:
        _SKILLS_DATA = {}
    return _SKILLS_DATA


def _extract_skills_from_jd_local(jd_text: str) -> list[str]:
    """
    从 JD 文本中提取关键技能（纯本地匹配，不依赖外部 API）。
    遍历 skills_data.json 各岗位的 keywords，统计命中数，
    取命中最多的 TOP 2 岗位的 skills 列表合并去重。
    """
    skills_data = _load_skills_data()
    if not skills_data or not jd_text:
        return []

    jd_lower = jd_text.lower()
    scored: list[tuple[int, str]] = []

    for category, cat_data in skills_data.items():
        if category == "通用":
            continue
        keywords = cat_data.get("keywords", [])
        score = sum(1 for kw in keywords if kw.lower() in jd_lower)
        if score > 0:
            scored.append((score, category))

    scored.sort(reverse=True)
    top_categories = scored[:2]

    skills_set: set[str] = set()
    for _, cat in top_categories:
        for skill in skills_data[cat].get("skills", []):
            skills_set.add(skill)

    result = list(skills_set)[:8]  # 最多 8 个
    if result:
        logger.info(f"本地 JD 匹配: 命中品类 {[c for _,c in top_categories]}, 提取 {len(result)} 个技能")
    return result


def _extract_hot_topics_from_skills(skills: list[str]) -> list[str]:
    """从技能列表反推可能的面试话题（本地生成）"""
    topic_keywords = {
        "数据库": "数据库设计与优化",
        "微服务": "微服务架构与治理",
        "Docker": "容器化与 CI/CD",
        "Kubernetes": "容器编排与生产运维",
        "React": "React 组件化与状态管理",
        "Vue": "Vue 响应式原理与生态",
        "TypeScript": "TypeScript 类型系统与工程化",
        "算法": "数据结构与算法",
        "机器学习": "机器学习算法与模型评估",
        "NLP": "NLP 技术与迁移学习",
        "Redis": "缓存策略与高可用",
        "Spring": "Spring 全家桶与 AOP",
        "MySQL": "MySQL 优化与分库分表",
    }
    topics = set()
    for skill in skills:
        for kw, topic in topic_keywords.items():
            if kw.lower() in skill.lower():
                topics.add(topic)
    return list(topics)[:4]


def _fetch_ddg(query: str) -> dict:
    """同步请求 DDG API"""
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
    url = f"{DDG_API}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AI-Interviewer/2.5"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"DDG 搜索失败 ({query}): {e}")
        return {}


def _extract_text_from_ddg(result: dict) -> str:
    """从 DDG 返回结果中提取有用文本"""
    parts = []

    # Abstract
    abstract = result.get("Abstract", "").strip()
    if abstract:
        parts.append(abstract)

    # AbstractText
    abstract_text = result.get("AbstractText", "").strip()
    if abstract_text and abstract_text not in abstract:
        parts.append(abstract_text)

    # RelatedTopics
    for topic in result.get("RelatedTopics", []):
        text = topic.get("Text", "").strip()
        if text:
            parts.append(text)

    # Answer
    answer = result.get("Answer", "").strip()
    if answer:
        parts.append(f"Answer: {answer}")

    return "\n".join(parts)


async def search_position_info(position: str, company: str = "") -> str:
    """
    搜索岗位相关信息，返回汇总的文本描述。
    返回格式：可读的自然语言描述，包含岗位职责、技能要求、面试重点。
    """
    queries = [
        f"{position} job description responsibilities skills",
        f"{position} interview questions technical",
    ]
    if company:
        queries.insert(0, f"{company} {position} hiring interview")

    all_texts = []
    for q in queries[:3]:  # 最多 3 次查询
        result = await to_thread(_fetch_ddg, q)
        text = _extract_text_from_ddg(result)
        if text:
            all_texts.append(text)

    return "\n\n---\n".join(all_texts)


async def enrich_jd_with_research(llm_client, jd_text: str, position: str = "",
                                   company: str = "") -> dict:
    """
    通过搜索 + LLM 分析，将原始 JD 丰富为结构化的面试画像。

    返回:
    {
        "enriched_jd": str,        # 丰富后的 JD 文本
        "key_skills": [str],       # 核心技能
        "hot_topics": [str],       # 热门面试话题
        "search_summary": str,     # 搜索结果的浓缩摘要
    }
    """
    # 尝试从 JD 文本中提取职位名称
    if not position:
        position = "技术岗位"

    # 1. 搜索
    search_text = await search_position_info(position, company)

    if not search_text:
        logger.info("web research: 未获取到搜索结果，启用本地 JD 关键词提取降级")
        local_skills = _extract_skills_from_jd_local(jd_text)
        local_topics = _extract_hot_topics_from_skills(local_skills)
        return {
            "enriched_jd": jd_text,
            "key_skills": local_skills,
            "hot_topics": local_topics,
            "search_summary": f"（DDG API 不可用，本地提取 {len(local_skills)} 个技能）",
            "source": "fallback",  # 标识降级来源，区别于正常搜索的 LLM 分析
        }

    # 2. LLM 分析
    system_prompt = (
        "你是一位专业的 HR 分析师。请分析以下搜索结果和岗位描述，"
        "提炼出面试时需要关注的核心要点。"
    )
    user_prompt = f"""原始岗位描述：
{jd_text[:2000] if jd_text else '未提供'}

关于「{position}」的搜索结果：
{search_text[:3000]}

请输出 JSON：
{{
    "enriched_jd": "结合搜索结果补充后的完整岗位描述（500-800字）",
    "key_skills": ["技能1", "技能2", ...],
    "hot_topics": ["面试常见话题1", "话题2", ...],
    "search_summary": "搜索结果的简洁总结（100字内）"
}}"""

    try:
        result = llm_client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=1024,
        )
        enriched_jd = result.get("enriched_jd", jd_text)
        key_skills = result.get("key_skills", [])
        hot_topics = result.get("hot_topics", [])
        search_summary = result.get("search_summary", "")

        logger.info(f"web research: 提炼出 {len(key_skills)} 个技能, {len(hot_topics)} 个话题")
        return {
            "enriched_jd": enriched_jd,
            "key_skills": key_skills,
            "hot_topics": hot_topics,
            "search_summary": search_summary,
        }
    except Exception as e:
        logger.error(f"LLM 分析搜索结果失败: {e}")
        return {
            "enriched_jd": jd_text,
            "key_skills": [],
            "hot_topics": [],
            "search_summary": search_text[:200],
        }
