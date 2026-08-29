"""
company_profiles.py 测试（v6.5）：YAML 加载 / 关键词匹配 / prompt 片段生成 / 降级容错。
借鉴来源：interviewerAgent 的 companies/*.yaml 配置层。
"""

import os
import textwrap

import pytest

from backend import company_profiles as cp


class TestBuiltInProfiles:
    """仓库自带 3 份公司配置能被加载（import 时已加载）"""

    def test_three_seed_profiles_loaded(self):
        names = {p["name"] for p in cp.list_profiles()}
        assert {"bytedance", "tencent", "alibaba"} <= names

    def test_get_profile_by_name(self):
        p = cp.get_profile("bytedance")
        assert p is not None
        assert "字节" in p["display_name"]
        assert p["role_description"]
        assert p["evaluation_rubric"]

    def test_get_profile_strips_whitespace(self):
        assert cp.get_profile("  tencent  ") is not None

    def test_get_profile_unknown_returns_none(self):
        assert cp.get_profile("unknown-corp") is None

    def test_get_profile_empty_returns_none(self):
        assert cp.get_profile(None) is None
        assert cp.get_profile("") is None

    def test_display_name_is_match_keyword(self):
        """展示名自动进入匹配关键词：JD 写全称也能命中"""
        p = cp.get_profile("alibaba")
        assert "阿里巴巴" in p["match_keywords"]


class TestMatchProfile:
    """match_profile() — JD 关键词自动匹配"""

    def test_match_bytedance(self):
        assert cp.match_profile("字节跳动 招聘后端开发") is not None
        assert cp.match_profile("字节跳动 招聘后端开发")["name"] == "bytedance"

    def test_match_by_short_keyword(self):
        assert cp.match_profile("面的是腾讯的岗位")["name"] == "tencent"

    def test_match_english_keyword(self):
        assert cp.match_profile("Join ByteDance as backend engineer")["name"] == "bytedance"

    def test_no_hit_returns_none(self):
        assert cp.match_profile("一家没有名字的公司") is None

    def test_empty_jd_returns_none(self):
        assert cp.match_profile("") is None
        assert cp.match_profile(None) is None

    def test_explicit_selection_ignored_by_match(self):
        """match_profile 只看 JD，与显式选择无关（显式优先逻辑在 main.py）"""
        p = cp.match_profile("腾讯后端")
        assert p["name"] == "tencent"


class TestPromptBlocks:
    """company_role_block / company_round_block / company_rubric"""

    def test_role_block_contains_header_and_name(self):
        block = cp.company_role_block(cp.get_profile("bytedance"))
        assert "【目标公司面试风格" in block
        assert "字节跳动" in block
        assert "面试官" in block

    def test_role_block_none_profile(self):
        assert cp.company_role_block(None) == ""
        assert cp.company_role_block({}) == ""

    def test_round_block_hits_tech_round(self):
        """拟真模式轮次名"技术广度"应命中 bytedance 的技术轮指令"""
        block = cp.company_round_block(cp.get_profile("bytedance"), "技术广度")
        assert "【本轮公司特定考察要求】" in block
        assert "选型" in block or "概念" in block

    def test_round_block_hits_traditional_round(self):
        """传统模式轮次名"技术一面"同样命中（关键词匹配兼容双模式）"""
        block = cp.company_round_block(cp.get_profile("tencent"), "技术一面")
        assert "【本轮公司特定考察要求】" in block

    def test_round_block_no_match_returns_empty(self):
        """"破冰环节"不该命中任何公司轮次指令"""
        assert cp.company_round_block(cp.get_profile("bytedance"), "破冰环节") == ""

    def test_round_block_multiple_rules_concatenated(self):
        """轮次名同时命中多条规则时全部注入"""
        profile = {
            "rounds": [
                {"match": ["技术"], "instructions": "规则A"},
                {"match": ["广度"], "instructions": "规则B"},
            ],
        }
        block = cp.company_round_block(profile, "技术广度")
        assert "规则A" in block and "规则B" in block

    def test_rubric(self):
        assert "评级" in cp.company_rubric(cp.get_profile("alibaba"))
        assert cp.company_rubric(None) == ""


class TestSessionIntegration:
    """InterviewSession 角色卡集成（不触发 LLM，纯 prompt 组装）"""

    def _make_session(self, profile):
        from backend.interview_engine.session import InterviewSession

        return InterviewSession(
            session_id="t" * 12,
            resume_text="候选人简历",
            jd_text="岗位描述",
            llm_client=None,
            diagnosis_engine=None,
            company_profile=profile,
        )

    def test_role_prompt_contains_company_block(self):
        sess = self._make_session(cp.get_profile("bytedance"))
        prompt = sess.get_interviewer_role_prompt()
        assert "【目标公司面试风格" in prompt
        assert "【你在评判什么】" in prompt   # 既有角色卡仍在

    def test_role_prompt_none_profile_unchanged(self):
        sess = self._make_session(None)
        prompt = sess.get_interviewer_role_prompt()
        assert "【目标公司面试风格" not in prompt
        assert "【你在评判什么】" in prompt

    def test_default_company_profile_empty(self):
        """不传 company_profile 时默认空 dict，向后兼容既有调用方"""
        sess = self._make_session(None)
        assert sess.company_profile == {}


class TestDegradation:
    """降级容错：坏文件跳过 / 目录不存在返回空 / reload 可用"""

    def _write(self, path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(content))

    def test_missing_dir_returns_empty(self, tmp_path):
        assert cp.load_profiles(str(tmp_path / "no_such_dir")) == {}

    def test_broken_yaml_skipped_but_good_loaded(self, tmp_path):
        self._write(tmp_path / "bad.yaml", "name: [unclosed")
        self._write(tmp_path / "good.yaml", """
            name: goodco
            display_name: 好公司
            role_description: 测试人格
        """)
        result = cp.load_profiles(str(tmp_path))
        assert list(result) == ["goodco"]
        assert result["goodco"]["display_name"] == "好公司"

    def test_empty_yaml_file_skipped(self, tmp_path):
        self._write(tmp_path / "empty.yaml", "# 只有注释\n")
        assert cp.load_profiles(str(tmp_path)) == {}

    def test_profile_without_name_skipped(self, tmp_path):
        self._write(tmp_path / "anon.yaml", """
            display_name: 无名公司
            role_description: 测试
        """)
        assert cp.load_profiles(str(tmp_path)) == {}

    def test_profile_without_content_skipped(self, tmp_path):
        """人格/轮次/量表全空的配置没有注入价值"""
        self._write(tmp_path / "hollow.yaml", """
            name: hollow
            display_name: 空壳公司
        """)
        assert cp.load_profiles(str(tmp_path)) == {}

    def test_str_match_normalizes_to_list(self, tmp_path):
        """match 写成字符串也能用（schema 宽容性）"""
        self._write(tmp_path / "s.yaml", """
            name: sco
            display_name: S公司
            role_description: 测试
            rounds:
              - match: 技术
                instructions: 技术轮规则
        """)
        result = cp.load_profiles(str(tmp_path))
        block = cp.company_round_block(result["sco"], "技术广度")
        assert "技术轮规则" in block

    def test_reload_rebuilds_registry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cp, "PROFILES_DIR", str(tmp_path))
        assert cp.reload() == {}
        self._write(tmp_path / "r.yaml", """
            name: reloadco
            display_name: 重载公司
            role_description: 测试
        """)
        assert list(cp.reload()) == ["reloadco"]
        # 恢复真实注册表，避免污染其它用例
        cp.reload()
