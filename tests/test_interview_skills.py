"""
面试技能（Skill）状态机测试（v6.5，借鉴 interviewerAgent internal/skill）。

覆盖三层：
  1. 技能自身：步骤推进 / 完成判定 / prompt 内容 / 触发词
  2. Registry：优先级排序 / 按名取用 / 自动匹配 / 重名保护
  3. 会话集成：激活 / 技能轮推进 / 完成自动退出 / 未知与重复激活的降级
"""

import pytest

from backend.interview_skills import (
    ConceptTeachSkill,
    QuickQuizSkill,
    SkillContext,
    SkillRegistry,
    TechCompareSkill,
    default_registry,
)


class TestQuickQuiz:
    def test_total_steps(self):
        assert QuickQuizSkill().total_steps() == 5

    def test_advances_each_turn(self):
        skill, ctx = QuickQuizSkill(), SkillContext()
        for expected in range(2, 6):
            skill.on_turn_end(ctx, "B")
            assert ctx.step == expected

    def test_completes_after_five(self):
        skill, ctx = QuickQuizSkill(), SkillContext()
        for _ in range(5):
            assert skill.is_complete(ctx) is False
            skill.on_turn_end(ctx, "B")
        assert skill.is_complete(ctx) is True

    def test_prompt_mentions_current_step(self):
        skill, ctx = QuickQuizSkill(), SkillContext()
        assert "第 1/5" in skill.build_prompt(ctx)
        skill.on_turn_end(ctx, "A")
        assert "第 2/5" in skill.build_prompt(ctx)

    def test_prompt_uses_weak_tags(self):
        ctx = SkillContext(weak_tags=["量化程度", "STAR 完整性"])
        prompt = QuickQuizSkill().build_prompt(ctx)
        assert "量化程度" in prompt

    def test_trigger_keywords(self):
        skill, ctx = QuickQuizSkill(), SkillContext()
        assert skill.can_activate(ctx, "来几道题考考我")
        assert not skill.can_activate(ctx, "我在字节做过推荐系统")


class TestConceptTeach:
    def test_completes_on_understanding_marker(self):
        skill, ctx = ConceptTeachSkill(), SkillContext()
        skill.on_turn_end(ctx, "哦，我理解了")
        assert skill.is_complete(ctx) is True

    def test_completes_after_max_rounds(self):
        skill, ctx = ConceptTeachSkill(), SkillContext()
        for _ in range(4):
            skill.on_turn_end(ctx, "还是有点模糊")
        assert skill.is_complete(ctx) is True

    def test_not_complete_midway(self):
        skill, ctx = ConceptTeachSkill(), SkillContext()
        skill.on_turn_end(ctx, "嗯，继续")
        assert skill.is_complete(ctx) is False


class TestTechCompare:
    def test_five_dimensions(self):
        assert TechCompareSkill().total_steps() == 5

    def test_prompt_walks_dimensions(self):
        skill, ctx = TechCompareSkill(), SkillContext()
        first = skill.build_prompt(ctx)
        skill.on_turn_end(ctx, "Redis 更快")
        second = skill.build_prompt(ctx)
        assert first != second          # 每轮推进一个维度，prompt 必须变化

    def test_completes_after_all_dimensions(self):
        skill, ctx = TechCompareSkill(), SkillContext()
        for _ in range(5):
            skill.on_turn_end(ctx, "……")
        assert skill.is_complete(ctx) is True


class TestRegistry:
    def test_default_registry_has_three(self):
        names = {s["name"] for s in default_registry().list()}
        assert names == {"quick_quiz", "concept_teach", "tech_compare"}

    def test_sorted_by_priority_desc(self):
        reg = default_registry()
        priorities = [s["priority"] for s in reg.list()]
        assert priorities == sorted(priorities, reverse=True)
        assert priorities[0] == 80      # quick_quiz 最高

    def test_get_by_name(self):
        assert default_registry().get("tech_compare") is not None
        assert default_registry().get("nope") is None

    def test_match_picks_highest_priority_hit(self):
        """自动匹配：命中多个时取优先级最高的"""
        reg = default_registry()
        ctx = SkillContext()
        # "不太懂区别" 同时命中 concept_teach(70) 与 tech_compare(50)
        matched = reg.match(ctx, "这两个的区别我不太懂")
        assert matched is not None
        assert matched.name == "concept_teach"

    def test_match_returns_none_without_hit(self):
        assert default_registry().match(SkillContext(), "我做过三个项目") is None

    def test_match_survives_skill_error(self):
        """单个技能判定抛异常不影响其它技能匹配"""
        class Boom(QuickQuizSkill):
            name = "boom"
            priority = 99

            def can_activate(self, ctx, trigger):
                raise RuntimeError("boom")

        reg = SkillRegistry([Boom(), TechCompareSkill()])
        assert reg.match(SkillContext(), "对比一下两者").name == "tech_compare"

    def test_duplicate_name_rejected(self):
        reg = SkillRegistry([QuickQuizSkill()])
        reg.register(QuickQuizSkill())
        assert len(reg.list()) == 1


class TestSessionIntegration:
    """技能与 InterviewSession 的接线（关键：技能轮不进诊断）"""

    def _session(self):
        from backend.interview_engine.session import InterviewSession

        return InterviewSession(
            session_id="s" * 12, resume_text="简历", jd_text="岗位",
            llm_client=None, diagnosis_engine=None,
        )

    def test_activate_unknown_skill(self):
        s = self._session()
        event = s.activate_skill("nope")
        assert event["ok"] is False
        assert s.is_skill_active() is False

    def test_activate_and_deactivate(self):
        s = self._session()
        event = s.activate_skill("quick_quiz")
        assert event["ok"] is True
        assert s.is_skill_active() is True
        assert s.active_skill == "quick_quiz"
        ended = s.deactivate_skill()
        assert ended["ok"] is True
        assert s.is_skill_active() is False

    def test_cannot_activate_while_active(self):
        s = self._session()
        s.activate_skill("quick_quiz")
        second = s.activate_skill("tech_compare")
        assert second["ok"] is False
        assert s.active_skill == "quick_quiz"   # 仍是第一个

    def test_skill_prompt_empty_when_inactive(self):
        assert self._session().skill_prompt() == ""

    def test_skill_prompt_overrides_role_prompt(self):
        """技能模式下 skill_prompt 非空，且不复用面试官角色卡"""
        s = self._session()
        s.activate_skill("tech_compare")
        prompt = s.skill_prompt()
        assert "【技术对比模式】" in prompt
        assert "【你在评判什么】" not in prompt

    def test_advance_completes_and_auto_exits(self):
        """走完 5 步自动退出技能，回到普通面试"""
        s = self._session()
        s.activate_skill("quick_quiz")
        for i in range(5):
            progress = s.advance_skill("B")
        assert progress["completed"] is True
        assert s.is_skill_active() is False     # 自动退回正式面试

    def test_advance_tracks_step(self):
        s = self._session()
        s.activate_skill("quick_quiz")
        p1 = s.advance_skill("A")
        assert p1["completed"] is False
        assert p1["step"] == 2
        assert p1["total"] == 5

    def test_advance_without_active_skill_is_noop(self):
        s = self._session()
        assert s.advance_skill("随便")["ok"] is False

    def test_deactivate_without_active_skill_is_noop(self):
        s = self._session()
        assert s.deactivate_skill()["ok"] is False

    def test_skill_turn_not_recorded_as_answer(self):
        """技能轮不得污染 answer_history / 诊断记录"""
        s = self._session()
        s.activate_skill("quick_quiz")
        for _ in range(3):
            s.advance_skill("B")
        assert s.all_diagnoses == []
        assert s.answer_history == []
