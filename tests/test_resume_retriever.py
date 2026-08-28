"""
backend/resume_retriever.py 测试：简历轻量检索与证据包 (v5.0)。

对标 agent-interview-coach 的 interview_corpus 思路：本地关键词 + 优先级加权、
严格上下文预算、输出【本轮证据包】。覆盖分块、噪声过滤、文件名优先级、
命中打分、预算硬限（单源/总块/总字符）、无证据兜底提示、溯源。
"""

from backend.resume_retriever import (
    ResumeRetriever,
    build_evidence_package,
    extract_terms,
    trace_retrieval,
    DEFAULT_PRIORITY,
    FILE_PRIORITY,
    MAX_CHARS_PER_FILE,
    MAX_CHUNKS_PER_SOURCE,
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_CHUNKS,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    _NO_EVIDENCE_MESSAGE,
    _noisy_name,
)

RESUME = (
    "候选人张三，5年后端经验，主导开发了 RAG 检索增强生成系统，"
    "使用 Elasticsearch 做向量检索，Redis 做缓存。"
    "负责电商订单系统的架构设计，MySQL 分库分表。"
    "擅长高并发、分布式系统、微服务治理。"
    "曾在创业公司负责技术团队搭建，具备技术管理能力。"
)


class TestExtractTerms:
    def test_empty(self):
        assert extract_terms("") == []
        assert extract_terms(None) == []

    def test_english_and_chinese(self):
        terms = extract_terms("RAG 和 Redis 缓存")
        assert "rag" in terms
        assert "redis" in terms
        assert "缓存" in terms

    def test_dedup_lowercase(self):
        terms = extract_terms("RAG rag RAG")
        assert terms.count("rag") == 1


class TestNoisyName:
    def test_noisy_patterns(self):
        assert _noisy_name("简历_副本.docx") is True
        assert _noisy_name("~$简历.docx") is True
        assert _noisy_name("证件照.png") is True
        assert _noisy_name("简历.pdf") is False


class TestDocumentPriority:
    def test_default_priority(self):
        r = ResumeRetriever([("项目说明.txt", "一些项目说明内容", None)])
        assert r.chunks[0].priority == DEFAULT_PRIORITY

    def test_filename_priority(self):
        r = ResumeRetriever([("终极简历.pdf", RESUME, None)])
        assert r.chunks[0].priority == FILE_PRIORITY["终极简历"]

    def test_skip_noisy_source(self):
        r = ResumeRetriever([("简历_副本.docx", RESUME, None)])
        assert r.chunks == []


class TestChunking:
    def test_small_doc_single_chunk(self):
        r = ResumeRetriever([("简历", "短文本", None)])
        assert len(r.chunks) == 1

    def test_large_doc_multiple_chunks(self):
        big = "技术" * 5000  # 10000 字符
        r = ResumeRetriever([("简历", big, None)])
        assert len(r.chunks) > 1
        assert all(len(c.text) <= 2000 for c in r.chunks)

    def test_truncate_too_long(self):
        # 构造超长文档：以单个字符为单元，源文远超 MAX_CHARS_PER_FILE
        big = "技" * (MAX_CHARS_PER_FILE + 10_000)
        r = ResumeRetriever([("简历", big, None)])
        assert len(r.chunks) > 1
        # 单块不超过分块上限
        assert all(len(c.text) <= CHUNK_SIZE for c in r.chunks)
        # 分块总量受限：源文被截断到预算内，重叠最多使总量膨胀 CHUNK_SIZE/(CHUNK_SIZE-OVERLAP) 倍
        total = sum(len(c.text) for c in r.chunks)
        cap = MAX_CHARS_PER_FILE * CHUNK_SIZE / (CHUNK_SIZE - CHUNK_OVERLAP)
        assert total <= cap + 2000


class TestSelectContext:
    def test_no_chunks(self):
        r = ResumeRetriever()
        assert r.select_context("你好") == _NO_EVIDENCE_MESSAGE

    def test_no_match_message(self):
        r = ResumeRetriever([("简历", RESUME, None)])
        out = r.select_context("聊聊兴趣爱好和旅行经历")
        assert out == _NO_EVIDENCE_MESSAGE

    def test_match_builds_package(self):
        r = ResumeRetriever([("简历", RESUME, None)])
        out = r.select_context("我做过 RAG 检索增强生成，用的 Elasticsearch")
        assert "本轮证据包" in out
        assert "命中" in out
        assert "RAG" in out or "elasticsearch" in out.lower()

    def test_source_filter(self):
        r = ResumeRetriever([
            ("简历", RESUME, None),
            ("项目经历", "RAG 系统上线", 90),
        ])
        # 仅检索 source='简历'
        out = r.select_context("RAG 系统", source_name="简历")
        assert "项目经历" not in out


class TestBudgetLimits:
    def _many_chunks(self):
        # 单个文档拆成多块，所有块都命中
        text = "缓存 技术 分布式" * 1000
        r = ResumeRetriever([("简历", text, None)])
        return r, text

    def test_max_chunks_per_source(self):
        r, text = self._many_chunks()
        r.add_document("项目", "缓存 技术 分布式" * 1000, 80)
        out = r.select_context("缓存 技术 分布式")
        # 单源最多 MAX_CHUNKS_PER_SOURCE
        assert out.count("[证据 简历") <= MAX_CHUNKS_PER_SOURCE
        assert out.count("[证据 项目") <= MAX_CHUNKS_PER_SOURCE

    def test_total_chunk_budget(self):
        r = ResumeRetriever([("简历", "技术 分布式 缓存 微服务" * 2000, None)])
        trace = list(r.trace_retrieval("技术 分布式 缓存 微服务"))
        selected = [t for t in trace if t["selected"]]
        assert len(selected) <= MAX_CONTEXT_CHUNKS
        assert sum(t["chars"] for t in selected) <= MAX_CONTEXT_CHARS


class TestTrace:
    def test_trace_empty(self):
        assert list(ResumeRetriever().trace_retrieval("你好")) == []

    def test_trace_fields(self):
        r = ResumeRetriever([("简历", RESUME, None)])
        rows = list(r.trace_retrieval("RAG Elasticsearch"))
        assert rows
        row = rows[0]
        for key in ("chunk_id", "source", "matched_terms", "score", "chars", "selected", "reason"):
            assert key in row
        assert row["source"] == "简历"


class TestBuildEvidencePackage:
    def test_build_no_resume(self):
        assert build_evidence_package("", "你好") == _NO_EVIDENCE_MESSAGE

    def test_build_with_resume(self):
        out = build_evidence_package(RESUME, "我做过 RAG 和 Redis 缓存")
        assert "本轮证据包" in out

    def test_trace_helper(self):
        rows = trace_retrieval(RESUME, "RAG")
        assert rows and rows[0]["source"] == "简历"
