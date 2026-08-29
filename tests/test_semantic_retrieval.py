"""v6.4: 检索语义近似通道（借鉴 MockFlow 零依赖混合召回）测试。

覆盖：
- bigram_tokens / bigram_cosine 基础性质（相同文本、无重叠、改写表述）；
- _score_chunks 双通道：零词命中但字面高度重叠的块被语义闸补召回；
  双闸取严（绝对下限 + 相对最高相似度）；无 query_text 时行为与 v6.3 一致；
- 加成只影响排序不改词条主导地位；
- knowledge_store.retrieve 同步受益（同层复用单点评分）；
- 纯语义入选块在证据块头部标注 bigram 相似度（可解释性）。
"""

import pytest

from backend.knowledge_store import KnowledgeStore
from backend.resume_retriever import (
    EvidenceChunk,
    ResumeRetriever,
    bigram_cosine,
    bigram_tokens,
    extract_terms,
)


# ===== bigram 基础性质 =====

class TestBigramBasics:
    def test_identical_text_similarity_is_one(self):
        text = "检索召回率优化实践"
        assert bigram_cosine(text, text) == pytest.approx(1.0)

    def test_disjoint_text_similarity_is_zero(self):
        assert bigram_cosine("向量检索召回", "团队管理经验") == 0.0

    def test_empty_side_similarity_is_zero(self):
        assert bigram_cosine("", "检索召回") == 0.0
        assert bigram_cosine("检索召回", "") == 0.0

    def test_rewritten_expression_has_positive_similarity(self):
        # 同义改写：词命中为 0（extract_terms 取整段中文串，互不为子串），
        # 但共享 bigram（检索/召回/回率），相似度应为正且明显高于无关文本
        rewritten = bigram_cosine("向量检索的召回率怎么提升", "检索召回率优化实践")
        unrelated = bigram_cosine("向量检索的召回率怎么提升", "团队管理心得分享")
        assert rewritten > 0
        assert rewritten > unrelated

    def test_bigram_tokens_mixed_language(self):
        tokens = bigram_tokens("RAG 检索")
        assert "rag" in tokens
        assert "检索" in tokens

    def test_ascii_word_not_split_into_bigrams(self):
        tokens = bigram_tokens("redis")
        assert "redis" in tokens
        assert "re" not in tokens or tokens.get("re", 0) == 0


# ===== 双通道评分 =====

QUERY = "向量检索的召回率怎么提升"
# 与 QUERY 零词命中（整段中文串互不为子串）但共享多个 bigram 的改写块
REWRITE_CHUNK = "检索召回率优化实践：先扩召回再重排。"
# 与 QUERY 完全无关的块
UNRELATED_CHUNK = "讲述个人团队协作与时间管理的心得体会。"


def _build_retriever(*texts: str) -> ResumeRetriever:
    r = ResumeRetriever()
    for i, t in enumerate(texts):
        r.add_document(f"材料{i + 1}", t)
    return r


class TestDualChannelScoring:
    def test_semantic_only_chunk_admitted_with_query(self):
        r = _build_retriever(UNRELATED_CHUNK, REWRITE_CHUNK)
        ranked = r._score_chunks(extract_terms(QUERY), query_text=QUERY)
        ids = {c.chunk_id for c in ranked}
        # 改写块零词命中，仅凭语义近似入选
        rewrite = next(c for c in r.chunks if c.text.startswith("检索召回率"))
        assert rewrite.chunk_id in ids
        assert not rewrite.matched_terms
        assert rewrite.semantic_sim > 0

    def test_unrelated_chunk_still_rejected(self):
        r = _build_retriever(UNRELATED_CHUNK)
        ranked = r._score_chunks(extract_terms(QUERY), query_text=QUERY)
        assert all(not c.matched_terms for c in ranked) or not ranked
        unrelated = r.chunks[0]
        assert unrelated not in ranked

    def test_no_query_text_keeps_v63_behavior(self):
        """无 query_text 时零词命中的块不得凭语义入选（向后兼容）。"""
        r = _build_retriever(REWRITE_CHUNK)
        ranked = r._score_chunks(extract_terms(QUERY))
        assert ranked == []

    def test_gate_requires_absolute_floor(self):
        """全场相似度都很低时，即使相对比例达标也不入选（矮子里不拔将军）。

        该块与查询仅共享一个 bigram（提升），且块较长稀释了相似度（约 0.07），
        低于绝对下限 0.12，不得入选。
        """
        low_sim_chunk = "在年底绩效复盘中提升组织协同效率的实践。"
        r = _build_retriever(low_sim_chunk)
        ranked = r._score_chunks(extract_terms(QUERY), query_text=QUERY)
        assert ranked == []

    def test_term_hit_unchanged_by_semantic_channel(self):
        """命中词条的块入选资格不受影响；语义加成只推高其排序分。"""
        # 中文词条取整段 CJK 串，命中需要块内原文包含查询串
        hit_chunk_text = QUERY + "的常用手段包括扩大候选集与重排序。"
        r = _build_retriever(UNRELATED_CHUNK, REWRITE_CHUNK, hit_chunk_text)
        ranked = r._score_chunks(extract_terms(QUERY), query_text=QUERY)
        hits = [c for c in ranked if c.matched_terms]
        assert hits, "词条命中的块必须入选"
        # 词条块分值 = priority + 命中数×8 + 加成，加成占比应很小
        for c in hits:
            assert c.semantic_bonus < len(c.matched_terms) * 8.0

    def test_semantic_bonus_pushes_ranking(self):
        """同词条命中数下，与查询字面重叠更高的块排前面。"""
        verbatim = QUERY                       # 与查询逐字相同，sim≈1.0
        diluted = QUERY + "。" + UNRELATED_CHUNK * 6   # 同样命中词条，但长尾稀释相似度
        r = _build_retriever(diluted, verbatim)
        ranked = r._score_chunks(extract_terms(QUERY), query_text=QUERY)
        assert len(ranked) == 2
        assert ranked[0].semantic_sim > ranked[1].semantic_sim
        assert ranked[0].text.startswith(QUERY)

    def test_trace_includes_semantic_sim(self):
        r = _build_retriever(REWRITE_CHUNK)
        records = list(r.trace_retrieval(QUERY))
        assert records
        assert "semantic_sim" in records[0]


# ===== knowledge_store 复用 =====

class TestKnowledgeStoreSemanticRecall:
    def test_retrieve_recalls_semantic_only_chunk(self):
        store = KnowledgeStore()
        store.add_document("rag:interview", "检索手册", REWRITE_CHUNK)
        hits = store.retrieve("rag:interview", QUERY, top_k=3)
        assert len(hits) == 1
        assert hits[0]["matched_terms"] == []
        assert hits[0]["score"] > 0

    def test_retrieve_rejects_unrelated(self):
        store = KnowledgeStore()
        store.add_document("rag:interview", "协作笔记", UNRELATED_CHUNK)
        assert store.retrieve("rag:interview", QUERY, top_k=3) == []


# ===== 证据块标注 =====

class TestEvidenceBlockLabel:
    def test_semantic_only_chunk_labeled_with_similarity(self):
        chunk = EvidenceChunk(chunk_id=0, text=REWRITE_CHUNK)
        chunk.semantic_sim = 0.3712
        assert "bigram 相似度 0.37" in chunk.to_block()

    def test_term_hit_chunk_label_unchanged(self):
        chunk = EvidenceChunk(chunk_id=0, text=REWRITE_CHUNK, matched_terms=["召回"])
        assert "命中:召回" in chunk.to_block()
        assert "bigram" not in chunk.to_block()
