"""
v6.3 注入去重测试（借鉴 HakiMeet 的 _injected_cache，并修正其指纹缺陷）。

覆盖三层：
1. content_hash 的跨进程稳定性（HakiMeet 用内置 hash() 踩坑之处）；
2. ResumeRetriever.select_context_tracked 的排除 / 预算 / 耗尽回退；
3. KnowledgeStore.retrieve / augment_prompt_tracked 的排除与指纹记账。

设计要点（也是本轮改动的验收口径）：
- **先过滤再走预算**：被排除的名额不能白占上下文预算；
- **耗尽必须回退**：长会话后期所有块都会被注入过，若不做回退，
  证据包会恒为空，诊断侧失去依据——去重不得以能力退化为代价；
- **向后兼容**：select_context / augment_prompt 仍返回 str。
"""

import pytest

from backend.resume_retriever import (
    ResumeRetriever,
    content_hash,
    _NO_EVIDENCE_MESSAGE,
)
from backend.knowledge_store import (
    NAMESPACE_INTERVIEW,
    KnowledgeStore,
)


# ── 测试语料：刻意让三块各自命中不同关键词，便于验证排除行为 ──
BLOCK_A = "候选人主导 Redis 缓存架构设计，支撑大促高并发流量削峰"
BLOCK_B = "订单系统采用 MySQL 分库分表，解决高并发下的数据倾斜问题"
BLOCK_C = "负责 Kubernetes 容器化改造与微服务治理体系建设"

# "Redis 高并发" 只命中 A；"高并发" 同时命中 A、B
QUERY_AB = "高并发 架构 数据库"
QUERY_A = "Redis 缓存"


def _build_retriever() -> ResumeRetriever:
    r = ResumeRetriever()
    r.add_document("简历", BLOCK_A)
    r.add_document("项目文档", BLOCK_B)
    r.add_document("补充说明", BLOCK_C)
    return r


class TestContentHash:
    """指纹必须跨进程稳定 —— 这是它能当去重键的前提。"""

    def test_stable_across_calls(self):
        assert content_hash("同一段文本") == content_hash("同一段文本")

    def test_digest_format(self):
        # blake2b(digest_size=8) → 16 位十六进制，定长便于比对与入库
        digest = content_hash("任意文本")
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)

    def test_leading_trailing_whitespace_normalized(self):
        assert content_hash("  前后空白  ") == content_hash("前后空白")

    def test_different_text_different_hash(self):
        assert content_hash("文本甲") != content_hash("文本乙")

    def test_none_and_empty_safe(self):
        assert content_hash(None) == content_hash("")
        assert isinstance(content_hash(None), str)

    def test_not_builtin_hash(self):
        """与内置 hash() 的区别：内置 hash 受 PYTHONHASHSEED 随机化影响。

        这里只断言"结果可预测"——content_hash 对同一输入永远给同一输出，
        而内置 hash 不保证（此为 HakiMeet 的实现缺陷，本项目不复用）。
        """
        expected = content_hash("固定输入")
        # 模拟"另一个进程"重新计算
        assert content_hash("固定输入") == expected


class TestSelectContextTracked:
    def test_first_round_returns_text_and_nonempty_hashes(self):
        text, hashes = _build_retriever().select_context_tracked(QUERY_AB)
        assert hashes, "首轮必须返回本次入选块的指纹"
        assert text != _NO_EVIDENCE_MESSAGE
        assert BLOCK_A in text

    def test_second_round_excludes_previously_injected(self, monkeypatch):
        """预算只够 1 块时，第二轮应给出**不同**的块而不是原块。"""
        monkeypatch.setattr("backend.resume_retriever.MAX_CONTEXT_CHUNKS", 1)
        r = _build_retriever()
        first_text, first_hashes = r.select_context_tracked(QUERY_AB)
        second_text, second_hashes = r.select_context_tracked(
            QUERY_AB, exclude_hashes=set(first_hashes)
        )
        assert first_hashes and second_hashes
        assert set(first_hashes).isdisjoint(second_hashes), "第二轮不得重复注入已注入块"
        assert BLOCK_A in first_text
        assert BLOCK_A not in second_text
        assert BLOCK_B in second_text

    def test_filtering_happens_before_budget(self, monkeypatch):
        """被排除的块不能占用预算名额（否则新块会被挤掉）。"""
        monkeypatch.setattr("backend.resume_retriever.MAX_CONTEXT_CHUNKS", 1)
        r = _build_retriever()
        _, first = r.select_context_tracked(QUERY_AB)
        # 排除首轮块后，预算仍应被一个新块占满，而不是返回空
        text, second = r.select_context_tracked(QUERY_AB, exclude_hashes=set(first))
        assert len(second) == 1 and second[0] not in set(first)
        assert text != _NO_EVIDENCE_MESSAGE

    def test_exhausted_falls_back_to_reuse(self):
        """所有块都被注入过时，回退复用，避免证据包恒为空。"""
        r = _build_retriever()
        _, first = r.select_context_tracked(QUERY_AB)
        exhausted = set(first)
        # 构造"全部已注入"：把 A/B/C 三块指纹一次性排除
        for block in (BLOCK_A, BLOCK_B, BLOCK_C):
            exhausted.add(content_hash(block))
        text, hashes = r.select_context_tracked(QUERY_AB, exclude_hashes=exhausted)
        assert text != _NO_EVIDENCE_MESSAGE, "耗尽时必须回退复用，不能退化为空证据包"
        assert hashes

    def test_reuse_can_be_disabled(self):
        r = _build_retriever()
        _, first = r.select_context_tracked(QUERY_AB)
        text, hashes = r.select_context_tracked(
            QUERY_AB, exclude_hashes=set(first), allow_reuse_when_exhausted=False
        )
        # 关闭回退后，无新块即明确返回无证据提示
        assert text == _NO_EVIDENCE_MESSAGE or not hashes

    def test_no_chunks_returns_no_evidence(self):
        text, hashes = ResumeRetriever().select_context_tracked("任意查询")
        assert text == _NO_EVIDENCE_MESSAGE
        assert hashes == []

    def test_select_context_still_returns_str(self):
        """向后兼容：只想要文本时仍是 str，且 exclude_hashes 生效。"""
        r = _build_retriever()
        text = r.select_context(QUERY_A)
        assert isinstance(text, str)
        _, hashes = r.select_context_tracked(QUERY_A)
        filtered = r.select_context(QUERY_A, exclude_hashes=set(hashes))
        assert isinstance(filtered, str)


@pytest.fixture()
def store():
    ks = KnowledgeStore()
    ks.add_document(NAMESPACE_INTERVIEW, "面经A", BLOCK_A)
    ks.add_document(NAMESPACE_INTERVIEW, "面经B", BLOCK_B)
    ks.add_document(NAMESPACE_INTERVIEW, "面经C", BLOCK_C)
    yield ks
    ks.clear()


class TestKnowledgeStoreDedup:
    def test_retrieve_result_carries_fingerprint(self, store):
        hits = store.retrieve(NAMESPACE_INTERVIEW, QUERY_AB, top_k=2)
        assert hits, "检索应有命中"
        for h in hits:
            assert h["content_hash"] == content_hash(h["text"])

    def test_exclude_hashes_filters_hits(self, store):
        first = store.retrieve(NAMESPACE_INTERVIEW, QUERY_AB, top_k=1)
        assert len(first) == 1
        excluded = {first[0]["content_hash"]}
        second = store.retrieve(NAMESPACE_INTERVIEW, QUERY_AB, top_k=1,
                                exclude_hashes=excluded)
        assert all(h["content_hash"] not in excluded for h in second)

    def test_augment_prompt_tracked_records_only_injected(self, store):
        base = "你是面试官。"
        prompt, injected = store.augment_prompt_tracked(
            base, NAMESPACE_INTERVIEW, QUERY_AB, top_k=1
        )
        assert injected, "注入后必须返回本轮实际注入的指纹"
        assert prompt != base

        # 第二轮排除首轮指纹后，注入内容与首轮不重复
        prompt2, injected2 = store.augment_prompt_tracked(
            base, NAMESPACE_INTERVIEW, QUERY_AB, top_k=1,
            exclude_hashes=set(injected),
        )
        assert set(injected).isdisjoint(injected2)

    def test_augment_prompt_tracked_no_hit_returns_empty(self, store):
        base = "你是面试官。"
        prompt, injected = store.augment_prompt_tracked(
            base, NAMESPACE_INTERVIEW, "区块链 智能合约 挖矿", top_k=2
        )
        assert prompt == base
        assert injected == []

    def test_augment_prompt_backward_compatible(self, store):
        """augment_prompt 返回类型不变（str），仅新增可选去重参数。"""
        out = store.augment_prompt("你是面试官。", NAMESPACE_INTERVIEW, QUERY_AB)
        assert isinstance(out, str)

    def test_empty_system_prompt_is_noop(self, store):
        prompt, injected = store.augment_prompt_tracked("", NAMESPACE_INTERVIEW, QUERY_AB)
        assert prompt == ""
        assert injected == []
