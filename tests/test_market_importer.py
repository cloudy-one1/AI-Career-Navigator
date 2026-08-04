"""
market/importer.py 测试：行映射函数 _map_data_row / _map_jobs_row
和关键词推断 _infer_keyword_from_title。
"""

import pytest
from backend.market.importer import (
    _map_data_row,
    _map_jobs_row,
    _infer_keyword_from_title,
)


class TestMapDataRow:
    """_map_data_row() — project1-enhanced data 表 → 标准 dict"""

    def test_basic_mapping(self):
        row = {
            "post": "Python开发工程师",
            "company": "阿里巴巴",
            "address": "杭州",
            "salary_min": 15,
            "salary_max": 30,
            "exper": "3-5年",
            "edu": "本科",
            "keywords": "Python,Django,MySQL",
            "content": "负责后端API开发与数据库设计",
            "job_url": "http://example.com/job/123",
            "dateT": "2024-01-01",
        }
        result = _map_data_row(row, None)
        assert result["title"] == "Python开发工程师"
        assert result["company"] == "阿里巴巴"
        assert result["city"] == "杭州"
        assert result["salary_min"] == 15
        assert result["salary_max"] == 30
        assert "Python" in result["tags"]
        assert "Django" in result["tags"]
        assert "MySQL" in result["tags"]

    def test_keyword_from_filter(self):
        row = {"post": "数据分析师", "company": "字节", "address": "北京",
               "salary_min": 20, "salary_max": 40, "exper": "1-3年",
               "edu": "本科", "keywords": "", "content": "", "job_url": "", "dateT": ""}
        result = _map_data_row(row, "数据分析")
        assert result["keyword"] == "数据分析"

    def test_keyword_inferred_when_no_filter(self):
        row = {"post": "Go后端开发工程师", "company": "腾讯", "address": "深圳",
               "salary_min": 25, "salary_max": 50, "exper": "3-5年",
               "edu": "本科", "keywords": "Go", "content": "", "job_url": "", "dateT": ""}
        result = _map_data_row(row, None)
        assert "Go" in result["keyword"]

    def test_empty_fields_handled(self):
        row = {"post": "", "company": "", "address": "", "salary_min": None,
               "salary_max": None, "exper": "", "edu": "", "keywords": "",
               "content": "", "job_url": "", "dateT": ""}
        result = _map_data_row(row, None)
        assert result["title"] == ""
        assert result["salary_raw"] == "?-?K/月"
        # edu="" → str("")=""（get 的默认值 "不限" 在 key 存在时不会被用）
        assert result["education"] == ""


class TestMapJobsRow:
    """_map_jobs_row() — 标准 jobs 表 → 标准 dict"""

    def test_basic_mapping(self):
        row = {
            "title": "Java 高级开发",
            "category": "Java开发",
            "company": "美团",
            "city": "上海",
            "salary": "20-40K",
            "salary_min": 20000,
            "salary_max": 40000,
            "experience": "3-5年",
            "education": "本科",
            "job_tags": "Java,Spring,微服务",
            "description": "负责系统架构设计",
            "url": "http://example.com/job/456",
            "crawl_time": "2024-06-01",
        }
        result = _map_jobs_row(row, None)
        assert result["keyword"] == "Java开发"
        assert result["company"] == "美团"
        assert result["city"] == "上海"
        assert result["salary_min"] == 20000

    def test_keyword_overrides_category(self):
        row = {
            "title": "", "category": "大数据", "company": "", "city": "",
            "salary": "", "salary_min": None, "salary_max": None,
            "experience": "", "education": "", "job_tags": "",
            "description": "", "url": "", "crawl_time": "",
        }
        result = _map_jobs_row(row, "自定义关键词")
        assert result["keyword"] == "自定义关键词"


class TestInferKeyword:
    """_infer_keyword_from_title()"""

    @pytest.mark.parametrize("title,expected_contains", [
        ("Python开发工程师", "Python"),
        ("Java高级开发工程师", "Java"),
        ("数据分析实习生", "数据"),
        ("Go（高级工程师）", "Go"),
        ("前端开发岗", "前端"),  # 去掉后缀"开发岗"后剩"前端"
        ("", ""),
    ])
    def test_infer(self, title, expected_contains):
        result = _infer_keyword_from_title(title)
        if expected_contains:
            assert expected_contains in result
        else:
            assert result == ""
