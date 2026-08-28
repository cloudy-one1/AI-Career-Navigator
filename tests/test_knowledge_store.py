"""
KnowledgeStore 命名空间知识库测试（v6.0，对标 career-copilot SimpleRagService）。

覆盖：命名空间隔离 / 检索排序与预算 / augment_prompt 注入与零副作用 / 统计与清理。
"""

from backend.knowledge_store import (
    KnowledgeStore,
    NAMESPACE_CAREER,
    NAMESPACE_INTERVIEW,
    NAMESPACE_RESUME,
    get_knowledge_store,
)


def _store() -> KnowledgeStore:
    return KnowledgeStore()


class TestNamespace:
    def test_short_name_normalized(self):
        s = _store()
        s.add_document("career", "报告", "向量数据库在 RAG 中用于召回相关片段" * 3)
        assert s.namespaces() == [NAMESPACE_CAREER]

    def test_isolation_between_namespaces(self):
        s = _store()
        s.add_document(NAMESPACE_INTERVIEW, "面试题库", "Python GIL 全局解释器锁限制多线程并行" * 5)
        s.add_document(NAMESPACE_CAREER, "行业报告", "前端工程师需要掌握 React 与 TypeScript" * 5)

        hits_interview = s.retrieve(NAMESPACE_INTERVIEW, "Python GIL 多线程")
        hits_career = s.retrieve(NAMESPACE_CAREER, "React TypeScript 前端")
        assert hits_interview and all("GIL" in h["text"] for h in hits_interview)
        assert hits_career and all("React" in h["text"] for h in hits_career)
        # 互不串库：面试命名空间检索不到职业内容
        assert s.retrieve(NAMESPACE_INTERVIEW, "React TypeScript") == []

    def test_add_document_returns_added_chunks(self):
        s = _store()
        n = s.add_document(NAMESPACE_RESUME, "简历", "短文本")
        assert n == 1
        assert s.add_document(NAMESPACE_RESUME, "空文本", "") == 0


class TestRetrieve:
    def test_ranking_and_top_k(self):
        s = _store()
        s.add_document(NAMESPACE_INTERVIEW, "块A", "RAG 检索增强生成的核心是向量召回与重排序" * 10)
        s.add_document(NAMESPACE_INTERVIEW, "块B", "完全无关的内容，讲的是做饭和旅游攻略之类" * 10)
        hits = s.retrieve(NAMESPACE_INTERVIEW, "RAG 向量召回", top_k=1)
        assert len(hits) == 1
        assert hits[0]["source"] == "块A"
        assert "RAG" in hits[0]["matched_terms"][0] or hits[0]["matched_terms"]

    def test_empty_namespace_returns_empty(self):
        assert _store().retrieve(NAMESPACE_CAREER, "任何问题") == []

    def test_hit_requires_term_match(self):
        s = _store()
        s.add_document(NAMESPACE_INTERVIEW, "块A", "RAG 向量检索" * 10)
        # 查询词与内容零交集 → 无命中（不把无关块当知识注入）
        assert s.retrieve(NAMESPACE_INTERVIEW, "量子力学薛定谔方程", top_k=3) == []


class TestAugmentPrompt:
    def test_augment_injects_block(self):
        s = _store()
        s.add_document(NAMESPACE_CAREER, "报告", "2026 年 AI 工程师岗位需求增长" * 8)
        prompt = s.augment_prompt("你是职业顾问。", NAMESPACE_CAREER, "AI 工程师 岗位需求")
        assert prompt.startswith("你是职业顾问。")
        assert "【参考知识库相关内容】" in prompt
        assert "2026 年 AI 工程师岗位需求增长" in prompt
        assert "严禁据此编造" in prompt

    def test_no_hit_returns_original(self):
        s = _store()
        original = "你是职业顾问。"
        assert s.augment_prompt(original, NAMESPACE_CAREER, "毫无相关的提问xyz") == original

    def test_empty_system_prompt_returned_as_is(self):
        s = _store()
        s.add_document(NAMESPACE_CAREER, "报告", "内容" * 50)
        assert s.augment_prompt("", NAMESPACE_CAREER, "内容") == ""


class TestStatsAndClear:
    def test_stats(self):
        s = _store()
        s.add_document(NAMESPACE_INTERVIEW, "A", "内容文本" * 30)
        s.add_document(NAMESPACE_INTERVIEW, "B", "另一段内容" * 30)
        stats = s.stats(NAMESPACE_INTERVIEW)
        assert stats[NAMESPACE_INTERVIEW]["chunks"] >= 2
        assert stats[NAMESPACE_INTERVIEW]["sources"] == 2

    def test_clear_single_and_all(self):
        s = _store()
        s.add_document(NAMESPACE_INTERVIEW, "A", "内容" * 30)
        s.add_document(NAMESPACE_CAREER, "B", "内容" * 30)
        s.clear(NAMESPACE_INTERVIEW)
        assert s.namespaces() == [NAMESPACE_CAREER]
        s.clear()
        assert s.namespaces() == []

    def test_singleton(self):
        assert get_knowledge_store() is get_knowledge_store()
