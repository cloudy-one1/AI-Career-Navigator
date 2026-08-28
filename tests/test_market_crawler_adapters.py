"""
market/crawler/adapters.py 测试：to_standard_job 字段映射 / 薪资解析 /
描述截断 / 空值兜底 / build_jd_text JD 组装。
"""

from backend.market.crawler.adapters import to_standard_job, build_jd_text

RAW = {
    "post": "Python开发工程师",
    "company": "测试科技",
    "address": "北京",
    "salary_raw": "1.5-2万/月",
    "edu": "本科",
    "exper": "3-5年",
    "dateT": "05-15 发布",
    "scrape_date": "2026-08-27 10:00:00",
    "content": "负责后端开发与系统设计工作 " * 500,  # 超长，验证截断
    "keywords": "Python Flask 后端",
    "job_url": "https://jobs.51job.com/beijing/123.html",
}


class TestToStandardJob:
    """to_standard_job() — 采集原始记录 → 标准 job dict"""

    def test_basic_mapping(self):
        job = to_standard_job(RAW, "python", "北京", "")
        assert job["source"] == "51job"
        assert job["source_id"] == RAW["job_url"]
        assert job["title"] == "Python开发工程师"
        assert job["company"] == "测试科技"
        assert job["city"] == "北京"
        assert job["salary_min"] == 15.0          # 1.5万/月 → 15K
        assert job["salary_max"] == 20.0          # 2万/月 → 20K
        assert job["exp_min"] == 3.0
        assert job["exp_max"] == 5.0
        assert job["education"] == "本科"
        assert job["tags"] == ["Python", "Flask", "后端"]
        assert job["url"] == RAW["job_url"]
        assert job["collected_at"] == RAW["scrape_date"]
        assert job["keyword"] == "python"

    def test_description_truncated_to_4000(self):
        job = to_standard_job(RAW, "python", "北京", "")
        assert len(job["description"]) == 4000

    def test_salary_negotiable(self):
        raw = dict(RAW, salary_raw="面议")
        job = to_standard_job(raw, "python", "北京", "")
        assert job["salary_min"] is None
        assert job["salary_max"] is None

    def test_experience_unlimited(self):
        raw = dict(RAW, exper="不限")
        job = to_standard_job(raw, "python", "北京", "")
        assert job["exp_min"] is None
        assert job["exp_max"] is None

    def test_source_id_fallback_to_job_id(self):
        raw = dict(RAW, job_url="")
        job = to_standard_job(raw, "python", "北京", "job-xyz")
        assert job["source_id"] == "job-xyz"

    def test_source_id_auto_generated_when_empty(self):
        raw = dict(RAW, job_url="")
        job = to_standard_job(raw, "python", "北京", "")
        assert job["source_id"].startswith("crawl:")

    def test_city_fallback_to_argument(self):
        raw = dict(RAW, address="")
        job = to_standard_job(raw, "python", "上海", "")
        assert job["city"] == "上海"

    def test_empty_fields(self):
        raw = {k: "" for k in RAW}
        job = to_standard_job(raw, "python", "北京", "x")
        assert job["education"] == "不限"
        assert job["tags"] == []
        assert job["salary_min"] is None


class TestBuildJdText:
    """build_jd_text() — 标准 job dict → Gap 分析用 JD 文本"""

    def test_contains_key_fields(self):
        job = to_standard_job(RAW, "python", "北京", "")
        text = build_jd_text(job)
        assert "Python开发工程师" in text
        assert "测试科技" in text
        assert "工作地点：北京" in text
        assert "学历要求：本科" in text
        assert "3.0-5.0年" in text
        assert "Python" in text
        assert "职位描述" in text
        assert "负责后端开发" in text

    def test_salary_uses_raw_when_present(self):
        job = to_standard_job(RAW, "python", "北京", "")
        text = build_jd_text(job)
        assert "1.5-2万/月" in text

    def test_missing_description_ok(self):
        job = to_standard_job({k: "" for k in RAW}, "python", "北京", "x")
        text = build_jd_text(job)
        assert text  # 不抛异常即可
