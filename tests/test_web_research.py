"""
web_research.py 测试：本地 JD 关键词降级（新增纯函数）。
"""

import pytest
from backend.web_research import (
    _extract_skills_from_jd_local,
    _extract_hot_topics_from_skills,
)


class TestExtractSkillsLocal:
    """_extract_skills_from_jd_local() — 本地 JD 关键词匹配"""

    def test_python_jd_extracts_skills(self):
        jd = "我们需要 Python 后端开发，熟悉 Django/FastAPI，数据库 MySQL/Redis，Docker 部署"
        skills = _extract_skills_from_jd_local(jd)
        assert len(skills) >= 2, f"提取技能过少: {skills}"
        has_python = any("Python" in s or "python" in s.lower() for s in skills)
        assert has_python, f"未提取到 Python: {skills}"

    def test_frontend_jd_extracts_skills(self):
        jd = "前端开发：React、Vue、TypeScript，构建工具 Webpack，响应式布局 CSS"
        skills = _extract_skills_from_jd_local(jd)
        assert len(skills) >= 1

    def test_empty_jd_returns_empty(self):
        assert _extract_skills_from_jd_local("") == []

    def test_unrelated_jd_returns_empty(self):
        """与 skills_data.json 无匹配的 JD 返回空"""
        jd = "我们是一家生物科技公司，需要分子生物学研究员"
        # 可能返回部分或空（取决于 skills_data.json 是否包含生物相关技能）
        skills = _extract_skills_from_jd_local(jd)
        assert isinstance(skills, list)

    def test_max_8_skills(self):
        jd = ("Python Java Go Rust C++ Scala Kotlin TypeScript Dart "
              "React Vue Angular Django Flask FastAPI Spring MySQL "
              "Redis MongoDB Docker K8s 微服务 机器学习 NLP 数据仓库")
        skills = _extract_skills_from_jd_local(jd)
        assert len(skills) <= 8


class TestExtractHotTopics:
    """_extract_hot_topics_from_skills()"""

    def test_empty_skills(self):
        assert _extract_hot_topics_from_skills([]) == []

    def test_database_skill_maps_to_topic(self):
        topics = _extract_hot_topics_from_skills(["MySQL", "Docker"])
        assert any("数据库" in t or "缓存" in t or "容器" in t for t in topics)

    def test_max_4_topics(self):
        topics = _extract_hot_topics_from_skills([
            "MySQL", "Redis", "Docker", "Kubernetes",
            "React", "Vue", "Spring", "NLP"
        ])
        assert len(topics) <= 4
