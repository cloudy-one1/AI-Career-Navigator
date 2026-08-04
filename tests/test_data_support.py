"""
data_support.py 测试：技能匹配、岗位列表。
实际 API: match_skills(jd_keywords: list[str]), get_all_positions() -> list[str]
"""

import pytest
from backend import data_support


class TestMatchSkills:
    """match_skills() — 根据 JD 关键词列表匹配岗位类别"""

    def test_python_keyword_matches_backend(self):
        result = data_support.match_skills(["Python"])
        assert len(result) >= 1, f"Python 应匹配至少一个岗位: {result}"
        # result 应包含 Python 相关岗位
        positions = [r["position"] for r in result if r["position"] != "通用"]
        assert any("Python" in p or "后端" in p or "开发" in p for p in positions)

    def test_multiple_keywords_better_match(self):
        result = data_support.match_skills(["Python", "Django", "MySQL"])
        assert len(result) >= 1
        # 应包含技能列表
        for r in result:
            assert "skills" in r
            assert isinstance(r["skills"], list)

    def test_empty_keywords_returns_generic_only(self):
        """空关键词返回通用技能列表（只有一个'通用'条目）"""
        result = data_support.match_skills([])
        assert len(result) == 1
        assert result[0]["position"] == "通用"

    def test_no_match_keywords_returns_generic_fallback(self):
        """未命中任何岗位时返回通用技能"""
        result = data_support.match_skills(["xyznotexist123"])
        assert len(result) >= 1
        assert any(r["position"] == "通用" for r in result)

    def test_generic_skill_includes_universal(self):
        """所有查询都应附带'通用'岗位"""
        result = data_support.match_skills(["Python"])
        positions = [r["position"] for r in result]
        assert "通用" in positions

    def test_result_order_by_hits(self):
        """结果按匹配命中数降序排列"""
        result = data_support.match_skills(["Java", "Spring", "微服务"])
        if len(result) >= 2:
            # 排除通用后，前面命中数应 >= 后面
            non_generic = [r for r in result if r["position"] != "通用"]
            if len(non_generic) >= 2:
                assert non_generic[0]["match_count"] >= non_generic[1]["match_count"]


class TestGetAllPositions:
    """get_all_positions() — 获取所有支持的岗位类型"""

    def test_returns_list_of_strings(self):
        positions = data_support.get_all_positions()
        assert isinstance(positions, list)
        assert len(positions) >= 3
        assert all(isinstance(p, str) for p in positions)

    def test_contains_common_positions(self):
        positions = data_support.get_all_positions()
        position_str = " ".join(positions)
        assert any(t in position_str for t in ["Python", "Java", "前端", "后端"])
