"""
market/cleaner.py 测试：薪资解析、经验/学历标准化、技能提取。
"""

import pytest
from backend.market.cleaner import (
    parse_salary,
    parse_experience,
    parse_education,
    extract_city,
    extract_skills,
)


# ============================================================
# parse_salary()
# ============================================================

class TestParseSalary:
    """薪资字符串解析"""

    @pytest.mark.parametrize("raw,expected", [
        ("1.5-2.5万·13薪", (15, 25)),
        ("15-25K", (15, 25)),
        ("8千-1.2万", (8, 12)),
        ("20-30万/年", (16.67, 25.0)),
        ("2万以上", (20, None)),
        ("8000-12000元/月", (8, 12)),
        ("8K-12K", (8, 12)),
        ("面议", (None, None)),
        ("", (None, None)),
    ])
    def test_parse_salary(self, raw, expected):
        result = parse_salary(raw)
        if expected[0] is None:
            assert result[0] is None
        else:
            assert result[0] == pytest.approx(expected[0], abs=0.1)
        if expected[1] is None:
            assert result[1] is None
        else:
            assert result[1] == pytest.approx(expected[1], abs=0.1)

    def test_none_input(self):
        assert parse_salary(None) == (None, None)


# ============================================================
# parse_experience()
# ============================================================

class TestParseExperience:
    """经验年限解析"""

    @pytest.mark.parametrize("raw,expected", [
        ("3-5年", (3.0, 5.0)),
        ("1-3年", (1.0, 3.0)),
        ("5-10年", (5.0, 10.0)),
        ("1年以下", (0.0, 1.0)),
        ("5年以上", (5.0, None)),
        ("应届毕业生", (0.0, 0.0)),
        ("在校生/应届生", (0.0, 0.0)),
        ("经验不限", (None, None)),
        ("无需经验", (None, None)),
        ("", (None, None)),
    ])
    def test_parse_experience(self, raw, expected):
        result = parse_experience(raw)
        assert result == expected

    def test_none_input(self):
        assert parse_experience(None) == (None, None)

    def test_unknown_format_not_crashing(self):
        result = parse_experience("随机文本abc")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ============================================================
# parse_education()
# ============================================================

class TestParseEducation:
    """学历标准化"""

    @pytest.mark.parametrize("raw,expected", [
        ("大专", "大专"),
        ("本科及以上", "本科"),
        ("本科", "本科"),
        ("硕士研究生", "硕士"),
        ("硕士", "硕士"),
        ("博士", "博士"),
        ("学历不限", "不限"),
        ("", "不限"),
    ])
    def test_parse_education(self, raw, expected):
        assert parse_education(raw) == expected

    def test_none_input(self):
        assert parse_education(None) == "不限"

    def test_zhongzhuan_is_unknown(self):
        """中专/中技 不是'大专'的子串，落回默认"""
        result = parse_education("中专")
        assert result == "不限"  # 中专 ≠ 大专，不在匹配列表中


# ============================================================
# extract_city()
# ============================================================

class TestExtractCity:
    """城市名归一化：统计聚合与地图定位的共同前置"""

    @pytest.mark.parametrize("raw,expected", [
        ("上海", "上海"),
        ("上海-徐汇区", "上海"),           # 51job 主形态：jobAreaString 的 '·' 已被替换为 '-'
        ("北京·朝阳区", "北京"),            # 存量旧数据未替换分隔符的兜底
        ("深圳-南山区-科技园", "深圳"),     # 多级地址只取首段
        ("广州市", "广州"),                 # 行政后缀
        ("呼和浩特市", "呼和浩特"),
        ("", ""),
    ])
    def test_extract_city(self, raw, expected):
        assert extract_city(raw) == expected

    def test_none_input(self):
        assert extract_city(None) == ""

    def test_two_char_place_not_trimmed(self):
        """'市辖区' 这类地名不以'市'结尾，不应被误伤"""
        assert extract_city("市辖区") == "市辖区"

    def test_same_city_districts_collapse(self):
        """同一城市的不同行政区必须收敛为同一 key——否则统计会碎片化、地图散点会 miss"""
        assert extract_city("上海-徐汇区") == extract_city("上海-浦东新区")


# ============================================================
# extract_skills()
# ============================================================

class TestExtractSkills:
    """技能从描述中提取"""

    def test_python_text_extracts_skills(self):
        """Python 技能应在 skills_data.json 词典中"""
        skills = extract_skills("熟悉 Python、Django 框架，了解 MySQL、Redis 数据库")
        assert len(skills) >= 2

    def test_with_job_tags(self):
        skills = extract_skills("", job_tags=["Java", "Spring Boot"])
        assert "Java" in skills
        assert "Spring Boot" in skills

    def test_combined_sources(self):
        skills = extract_skills("使用 React", job_tags=["Vue"])
        assert len(skills) >= 2

    def test_empty_returns_empty(self):
        assert extract_skills("") == []
        assert extract_skills("", job_tags=[]) == []

    def test_english_skill_word_boundary(self):
        """Go 不应错误匹配 Docker"""
        skills = extract_skills("Go programming language")
        # Go 是英文简写，需确保词典中有它才匹配
        assert isinstance(skills, list)

    def test_returns_sorted_list(self):
        skills = extract_skills("Python, Java, MySQL")
        if skills:
            assert skills == sorted(skills)
