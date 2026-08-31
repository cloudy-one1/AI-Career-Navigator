"""
[AI求职陪跑] 采集原始数据 → 标准岗位 dict 适配层。

字段对齐 ``backend.market.store.upsert_jobs`` 的输入契约
（与 ``importer._map_data_row`` 的输出结构一致，便于后续统一消费）。

原始字段（来自 ``python_job_scraper.scrape_jobs``）:
    post / company / address / salary_raw / edu / exper /
    dateT("05-15 发布") / scrape_date(完整时间戳) / content / keywords / job_url
"""
import logging
import uuid

from .salary_parser import parse_salary as crawl_parse_salary
from ..cleaner import parse_experience

logger = logging.getLogger("market.crawler.adapters")

_SOURCE = "51job"
_DESC_LIMIT = 4000


def _salary_to_k(value: float) -> float | None:
    """crawler salary_parser 对面议返回 (0.0, 0.0)，统一为 None 以对齐 store 契约"""
    if value is None or value <= 0:
        return None
    return round(value, 2)


def to_standard_job(raw: dict, keyword: str, city: str, job_id: str = "") -> dict:
    """
    单条采集原始记录 → 标准 job dict。

    参数:
        raw:      job-crawler 采集器返回的原始岗位 dict
        keyword:  用户输入的搜索关键词（写入 keyword 列）
        city:     岗位城市（优先取 raw['address']，兜底该参数）
        job_id:   source_id 兜底值（job_url 为空时保证唯一性）
    """
    title = str(raw.get("post", "") or "").strip()
    company = str(raw.get("company", "") or "").strip()
    address = str(raw.get("address", "") or "").strip()
    salary_raw = str(raw.get("salary_raw", "") or "").strip()
    exper_raw = str(raw.get("exper", "") or "").strip()
    edu_raw = str(raw.get("edu", "") or "").strip()
    keywords_raw = str(raw.get("keywords", "") or "").strip()
    content = str(raw.get("content", "") or "")
    job_url = str(raw.get("job_url", "") or "").strip()
    date_t = str(raw.get("dateT", "") or "")
    scrape_date = str(raw.get("scrape_date", "") or "")

    s_min, s_max = crawl_parse_salary(salary_raw)
    exp_min, exp_max = parse_experience(exper_raw)

    # 标签：job-crawler 的 keywords 为空格分隔的 jobTags
    tags = [t for t in (t.strip() for t in keywords_raw.split()) if t]

    # source_id：job_url 优先，空时用 job_id 兜底；仍为空则生成稳定占位避免 UNIQUE 冲突
    source_id = job_url or job_id
    if not source_id:
        source_id = f"crawl:{uuid.uuid5(uuid.NAMESPACE_URL, f'{title}|{company}|{address}')}"

    # collected_at：完整时间戳优先（scrape_date），"05-15 发布" 兜底
    collected_at = scrape_date or date_t

    return {
        "source": _SOURCE,
        "source_id": source_id,
        "keyword": keyword or title,
        "title": title,
        "company": company,
        "city": address or city,
        "salary_raw": salary_raw,
        "salary_min": _salary_to_k(s_min),
        "salary_max": _salary_to_k(s_max),
        "exp_min": exp_min,
        "exp_max": exp_max,
        "education": edu_raw or "不限",
        "tags": tags,
        "description": content[:_DESC_LIMIT],
        "url": job_url,
        "collected_at": collected_at,
    }


def build_jd_text(job: dict) -> str:
    """把一条标准岗位记录组装为 Gap 分析可用的 JD 文本（纯文本拼接）。"""
    lines = [
        f"职位名称：{job.get('title', '')}",
        f"公司：{job.get('company', '')}",
        f"工作地点：{job.get('city', '')}",
    ]
    salary_raw = job.get("salary_raw") or ""
    if job.get("salary_min") and job.get("salary_max"):
        salary_raw = salary_raw or f"{job['salary_min']}-{job['salary_max']}K/月"
    if salary_raw:
        lines.append(f"薪资待遇：{salary_raw}")

    if job.get("education"):
        lines.append(f"学历要求：{job['education']}")
    exp_raw = ""
    if job.get("exp_min") is not None and job.get("exp_max") is not None:
        exp_raw = f"{job['exp_min']}-{job['exp_max']}年"
    elif job.get("exp_min") is not None:
        exp_raw = f"{job['exp_min']}年以上"
    if exp_raw:
        lines.append(f"经验要求：{exp_raw}")

    tags = job.get("tags") or []
    if tags:
        lines.append(f"技能要求：{'、'.join(str(t) for t in tags)}")

    description = job.get("description") or ""
    if description:
        lines.append("职位描述：")
        lines.append(description)

    return "\n".join(lines)
