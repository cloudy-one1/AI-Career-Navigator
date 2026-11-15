"""
market/remote_source.py 测试：Remotive 岗位映射、payload 解析、导入链路与
路由端点。transport 注入假实现，全程无网络。
"""

import pytest

from backend.market import remote_source
from backend.market.remote_source import (
    import_remote,
    map_remotive_job,
    map_remotive_payload,
)


def make_job(**overrides) -> dict:
    """Remotive API 返回的单条岗位（ realistic 形态）"""
    job = {
        "id": 12345,
        "url": "https://remotive.com/remote-jobs/some-slug",
        "title": "Senior Python Engineer",
        "company_name": "Acme Corp",
        "category": "Software Development",
        "job_type": "full_time",
        "candidate_required_location": "Worldwide",
        "salary": "$60k - $90k",
        "tags": ["Python", "Django", " PostgreSQL "],
        "publication_date": "2026-11-01T10:30:00",
        "description": "<p>Build <b>APIs</b> &amp; services<br/>with Python</p>",
    }
    job.update(overrides)
    return job


def make_transport(payload=None, error=None, calls=None):
    """假 transport：同步可调用，签名与 _http_get_json 对齐，记录调用便于断言"""
    def transport(url, timeout=15):
        if calls is not None:
            calls.append(url)
        if error is not None:
            raise error
        return payload
    return transport


class TestMapRemotiveJob:
    """单条岗位 → market.db 标准记录"""

    def test_full_mapping(self):
        result = map_remotive_job(make_job(), "Python")
        assert result["source"] == "remotive"
        assert result["source_id"] == "12345"
        assert result["keyword"] == "Python"
        assert result["title"] == "Senior Python Engineer"
        assert result["company"] == "Acme Corp"
        assert result["city"] == "海外远程"           # 远程岗位统一统计桶
        assert result["salary_raw"] == "$60k - $90k"
        assert result["salary_min"] is None           # 外币刻意不入数值列
        assert result["salary_max"] is None
        assert result["exp_min"] is None
        assert result["education"] == "不限"
        assert result["tags"] == ["Python", "Django", "PostgreSQL"]  # 去空白
        assert result["collected_at"] == "2026-11-01T10:30:00"        # 源时间透传
        assert result["url"].startswith("https://remotive.com/")

    def test_description_strips_html_and_keeps_location(self):
        result = map_remotive_job(make_job(), "Python")
        assert "[地点: Worldwide]" in result["description"]
        assert "Build APIs & services with Python" in result["description"]
        assert "<p>" not in result["description"]
        assert "<b>" not in result["description"]

    def test_missing_optional_fields(self):
        result = map_remotive_job({
            "id": 1, "title": "DevOps Engineer",
        }, "DevOps")
        assert result["city"] == "海外远程"           # 无地点也有统一桶
        assert result["salary_raw"] == ""
        assert result["salary_min"] is None
        assert result["company"] == ""
        assert result["collected_at"] == ""           # upsert 端会落当前时间

    def test_empty_title_kept_for_payload_filter(self):
        """title 由 payload 层过滤（空标题整条丢弃），本函数保留字段直通"""
        result = map_remotive_job(make_job(title="  "), "Python")
        assert result["title"] == ""

    def test_salary_never_parsed_into_numeric_columns(self):
        """防回归：任何形态的 salary 都不得污染 CNY 薪资分档"""
        for raw in ("$60k - $90k", "€80,000 per year", "", None):
            result = map_remotive_job(make_job(salary=raw), "Python")
            assert result["salary_min"] is None
            assert result["salary_max"] is None
            assert result["salary_raw"] == (raw or "")


class TestMapRemotivePayload:
    """payload → 记录列表；坏结构宽容"""

    def test_normal_payload(self):
        payload = {"jobs": [make_job(), make_job(id=2, title="Frontend Dev")],
                   "jobCount": 2}
        jobs = map_remotive_payload(payload, "Python")
        assert len(jobs) == 2
        assert {j["title"] for j in jobs} == {"Senior Python Engineer", "Frontend Dev"}

    def test_empty_and_bad_payloads(self):
        assert map_remotive_payload({}, "Python") == []
        assert map_remotive_payload({"jobs": []}, "Python") == []
        assert map_remotive_payload({"jobs": "oops"}, "Python") == []
        assert map_remotive_payload(None, "Python") == []

    def test_drops_non_dict_and_empty_title_entries(self):
        payload = {"jobs": [
            make_job(),
            "not-a-dict",
            make_job(id=3, title=""),
            make_job(id=4, title="QA Engineer"),
        ]}
        jobs = map_remotive_payload(payload, "QA")
        assert [j["source_id"] for j in jobs] == ["12345", "4"]


class TestImportRemote:
    """拉取 + 映射链路（transport 注入）"""

    @pytest.mark.asyncio
    async def test_fetch_and_map(self):
        calls = []
        jobs = await import_remote(
            "Python", 50,
            transport=make_transport({"jobs": [make_job()]}, calls=calls))
        assert len(jobs) == 1
        assert jobs[0]["source"] == "remotive"
        assert calls and "remotive.com/api/remote-jobs" in calls[0]
        assert "search=Python" in calls[0]

    @pytest.mark.asyncio
    async def test_empty_keyword_rejected(self):
        with pytest.raises(ValueError):
            await import_remote("   ", transport=make_transport())

    @pytest.mark.asyncio
    async def test_network_error_propagates(self):
        """网络异常必须向上抛（与 importer 静默吞错的口径刻意不同）"""
        with pytest.raises(RuntimeError):
            await import_remote("Python", transport=make_transport(
                error=RuntimeError("network down")))


class TestRouterEndpoint:
    """POST /api/market/import/remote —— 服务注入 + 落库 + 统计分源"""

    def test_import_remote_end_to_end(self, client, monkeypatch):
        async def fake_fetch(keyword, limit, transport=None):
            return {"jobs": [make_job()]}

        monkeypatch.setattr(remote_source, "fetch_remote_jobs", fake_fetch)
        resp = client.post("/api/market/import/remote",
                           data={"keyword": "Python", "limit": 50})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["source"] == "remotive"
        assert body["imported"] == 1

        stats = client.get("/api/market/stats").json()
        assert stats["total"] == 1
        assert {"source": "remotive", "cnt": 1} in stats["sources"]

    def test_upstream_failure_returns_502(self, client, monkeypatch):
        async def boom(keyword, limit, transport=None):
            raise RuntimeError("remote server down")

        monkeypatch.setattr(remote_source, "fetch_remote_jobs", boom)
        resp = client.post("/api/market/import/remote",
                           data={"keyword": "Python"})
        assert resp.status_code == 502
        assert "remote server down" in resp.json()["detail"]

    def test_limit_clamped(self, client, monkeypatch):
        seen = {}

        async def fake_fetch(keyword, limit, transport=None):
            seen["limit"] = limit
            return []

        monkeypatch.setattr(remote_source, "fetch_remote_jobs", fake_fetch)
        resp = client.post("/api/market/import/remote",
                           data={"keyword": "Go", "limit": 9999})
        assert resp.status_code == 200
        assert seen["limit"] == remote_source._MAX_LIMIT
