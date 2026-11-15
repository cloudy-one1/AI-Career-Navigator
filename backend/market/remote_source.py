"""
[v8.23] 国际远程岗位采集源（Remotive 公开 API，免 key 免注册）。

为什么需要它：51job 管道覆盖国内市场，但「远程工作/海外机会」在 domestic
源里天然缺席——它是求职定位决策里完全独立的维度。Remotive 是公开的远程
岗位聚合 API（免 key、限流友好），作为 job-crawler 之外的第二个采集源接入
同一条 import → store 管道，字段映射口径与 ``importer._map_*_row`` 一致。

货币口径（重要）：Remotive 的 salary 是自由文本（多为 "$50k-$90k" 这类
美元/欧元区间）。**刻意不解析进 salary_min/salary_max 数值列**——market.db
的薪资分档统计口径是"月薪千元（人民币）"，混入外币会污染国内薪资分布。
原始字符串保留在 salary_raw 供展示，数值列留空让国内薪资统计保持纯净。

地点口径：远程岗位的地点五花八门（Worldwide / EMEA / USA / Remote），
city 统一落「海外远程」做单一统计桶，原始地点前缀进 description（供
JD 文本与 Gap 分析保留信息）。

HTTP 用标准库 urllib + ``asyncio.to_thread``（与 ``backend.web_research``
同款，零新增依赖）；fetch 可注入，测试全程无网络。

import 路径示例：from backend.market.remote_source import import_remote
"""

import asyncio
import html as html_mod
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
_HTTP_TIMEOUT = 15          # 单次请求超时，秒
_MAX_LIMIT = 200            # 单次导入上限（API 与统计合理性的双重边界）
_REMOTE_CITY = "海外远程"    # 远程岗位的统一统计桶
_DESC_MAX_CHARS = 4000      # 与 importer 各映射函数的 description 截断同口径
_UA = "AI-Career-Navigator/1.0 (market insights)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _http_get_json(url: str, timeout: float = _HTTP_TIMEOUT) -> dict:
    """标准库 GET → JSON。失败抛异常，由调用方归约为可读错误。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def fetch_remote_jobs(keyword: str, limit: int = 50,
                            transport=None) -> dict:
    """请求 Remotive 搜索接口，返回原始 payload（失败抛异常）。

    transport 可注入：同步可调用，签名与 ``_http_get_json`` 对齐
    (url, timeout) -> dict；测试注入假实现即可全程无网络。
    """
    limit_n = max(1, min(int(limit), _MAX_LIMIT))
    if transport is None:
        params = urllib.parse.urlencode({"search": keyword, "limit": limit_n})
        url = f"{REMOTIVE_API_URL}?{params}"
        payload = await asyncio.to_thread(_http_get_json, url)
    else:
        url = f"{REMOTIVE_API_URL}?search={urllib.parse.quote(keyword)}&limit={limit_n}"
        payload = await asyncio.to_thread(transport, url, _HTTP_TIMEOUT)
    return payload if isinstance(payload, dict) else {}


def _strip_html(raw: str) -> str:
    """HTML → 纯文本：剥标签、还原实体、折叠空白。"""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html_mod.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def map_remotive_job(job: dict, keyword: str) -> dict:
    """Remotive 单条岗位 → market.db 标准记录（字段口径同 importer）。"""
    title = str(job.get("title", "") or "").strip()
    company = str(job.get("company_name", "") or "").strip()
    location = str(job.get("candidate_required_location", "") or "").strip()
    url = str(job.get("url", "") or "")

    desc_text = _strip_html(str(job.get("description", "") or ""))
    description = f"[地点: {location}] {desc_text}".strip()[:_DESC_MAX_CHARS]

    tags = [str(t).strip() for t in (job.get("tags") or []) if str(t).strip()]

    return {
        "source": "remotive",
        "source_id": str(job.get("id") or url),
        "keyword": (keyword or "").strip() or title,
        "title": title,
        "company": company,
        "city": _REMOTE_CITY,
        # 外币薪资刻意不入数值列（防污染国内薪资分档），原文保留展示
        "salary_raw": str(job.get("salary", "") or ""),
        "salary_min": None,
        "salary_max": None,
        "exp_min": None,
        "exp_max": None,
        "education": "不限",
        "tags": tags,
        "description": description,
        "url": url,
        "collected_at": str(job.get("publication_date", "") or ""),
    }


def map_remotive_payload(payload: dict, keyword: str) -> list[dict]:
    """Remotive payload（{"jobs": [...]}）→ 标准记录列表；坏结构返回空表。"""
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    return [map_remotive_job(j, keyword) for j in jobs
            if isinstance(j, dict) and str(j.get("title") or "").strip()]


async def import_remote(keyword: str, limit: int = 50,
                        transport=None) -> list[dict]:
    """拉取并映射国际远程岗位，返回可直接传给 store.upsert_jobs() 的列表。

    网络异常向上抛——调用方（路由层）负责归约为可读错误；与
    importer 静默吞错的口径不同：本地库缺失是"无数据"，网络失败是
    "本次没采到"，语义不同必须让路由层感知。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        raise ValueError("keyword 不能为空")
    payload = await fetch_remote_jobs(keyword, limit, transport=transport)
    jobs = map_remotive_payload(payload, keyword)
    logger.info("Remotive 远程岗位拉取完成: keyword=%s, 映射 %d 条", keyword, len(jobs))
    return jobs


def clamp_limit(limit: Any) -> int:
    """路由层限幅：1~_MAX_LIMIT，非法输入回落默认 50。"""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return 50
    return max(1, min(n, _MAX_LIMIT))
