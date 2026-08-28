"""
简历轻量检索与证据包 (v5.0)

对标 agent-interview-coach 的 interview_corpus.py 思路：
本地关键词 + 优先级加权检索（无向量库），严格上下文预算，输出【本轮证据包】，
供诊断引擎与追问引擎在生成时"只能依据证据或候选人亲述"，杜绝编造经历。

分层契约：本模块属 L2 领域层，仅依赖 L1（config/logger），被 L3 业务层调用。
不引入任何第三方检索依赖（本地优先、零托管依赖）。
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 分块参数 ──
CHUNK_SIZE = 2000            # 单块最大字符数
CHUNK_OVERLAP = 250          # 相邻块重叠字符数（避免关键词被切分丢失）
MAX_CHARS_PER_FILE = 120_000 # 单文档最多纳入检索的字符数

# ── 检索预算（硬限，防 token 膨胀）──
MAX_CONTEXT_CHUNKS = 4       # 最多选入的证据块数
MAX_CONTEXT_CHARS = 6_000    # 证据包总字符预算
MAX_CHUNKS_PER_SOURCE = 2    # 单一来源最多选入块数
SEARCH_HEAD_CHARS = 800      # 评分时仅在块前 N 字符内匹配关键词（对齐 GitHub 实现）

# ── 文件名优先级启发式 ──
FILE_PRIORITY = {
    "协议": 100,
    "背景": 98,
    "终极简历": 95,
    "简历": 95,
    "个人": 90,
}
DEFAULT_PRIORITY = 60
NOISY_NAME_PATTERNS = ("backup", "副本", "~$", "证件照", "备份")

# ── 关键词提取 ──
_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}")


@dataclass
class EvidenceChunk:
    """单块候选证据。"""

    chunk_id: int
    text: str
    source: str = "简历"
    priority: float = DEFAULT_PRIORITY
    matched_terms: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.priority + len(self.matched_terms) * 8.0

    def to_block(self) -> str:
        terms = "、".join(self.matched_terms) if self.matched_terms else "无"
        return f"[证据 {self.source}·#{self.chunk_id}｜命中:{terms}]\n{self.text.strip()}"


def _noisy_name(name: str) -> bool:
    return any(p in name for p in NOISY_NAME_PATTERNS)


def extract_terms(text: str) -> list[str]:
    """提取 2 字以上英文词 / 2 字以上中文词的词干集合。"""
    if not text:
        return []
    seen: set[str] = set()
    for m in _TERM_RE.finditer(text):
        token = m.group(0).lower()
        if token not in seen:
            seen.add(token)
    return list(seen)


class ResumeRetriever:
    """基于候选人简历/项目材料构建的轻量检索器。

    用法：构建后调用 select_context(用户回答) 得到【本轮证据包】文本；
    或调用 trace_retrieval() 获取检索过程溯源（调试用）。
    """

    def __init__(self, documents: list[tuple[str, str, float]] | None = None):
        """documents: [(source_name, text, priority), ...]；缺省为单简历（source='简历'）。"""
        self.chunks: list[EvidenceChunk] = []
        self._chunk_id = 0
        if documents:
            for name, text, priority in documents:
                self.add_document(name, text, priority)

    # ── 构建 ──

    def add_document(self, source: str, text: str, priority: float | None = None) -> None:
        """把一份文档分块加入索引。自动截断超长文档、跳过噪声文件名。"""
        if not text or _noisy_name(source):
            return
        text = text[:MAX_CHARS_PER_FILE].strip()
        if not text:
            return
        if priority is None:
            priority = DEFAULT_PRIORITY
            for key, val in FILE_PRIORITY.items():
                if key in source:
                    priority = val
                    break
        chunks = self._chunk_text(text)
        for seg in chunks:
            self.chunks.append(EvidenceChunk(
                chunk_id=self._chunk_id,
                text=seg,
                source=source,
                priority=priority,
            ))
            self._chunk_id += 1
        logger.debug("[resume_retriever] %s 分块 %d 段 (priority=%.0f)", source, len(chunks), priority)

    def _chunk_text(self, text: str) -> list[str]:
        """按 CHUNK_SIZE 分块，相邻块保留 CHUNK_OVERLAP 重叠。"""
        if len(text) <= CHUNK_SIZE:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            chunks.append(text[start:end])
            if end == len(text):
                break
            start = end - CHUNK_OVERLAP
        return chunks

    # ── 检索 ──

    def _score_chunks(self, terms: list[str]) -> list[EvidenceChunk]:
        term_set = set(terms)
        for chunk in self.chunks:
            head = chunk.text[:SEARCH_HEAD_CHARS].lower()
            chunk.matched_terms = [t for t in term_set if t in head]
        # 仅保留命中至少一个关键词的块，避免把无关块当证据塞进上下文
        hits = [c for c in self.chunks if c.matched_terms]
        return sorted(hits, key=lambda c: c.score, reverse=True)

    def select_context(self, user_text: str, source_name: str | None = None) -> str:
        """按用户当前回答检索简历，组装【本轮证据包】。

        预算硬限：最多 MAX_CONTEXT_CHUNKS 块、单源 MAX_CHUNKS_PER_SOURCE、
        总字符 MAX_CONTEXT_CHARS。无匹配时返回提示语（诊断引擎据此转向澄清追问）。
        """
        if not self.chunks:
            return _NO_EVIDENCE_MESSAGE
        terms = extract_terms(user_text or "")
        ranked = self._score_chunks(terms)

        # 预算：单源限制 + 总块数限制
        per_source: dict[str, int] = {}
        picked: list[EvidenceChunk] = []
        total_chars = 0
        for chunk in ranked:
            if len(picked) >= MAX_CONTEXT_CHUNKS:
                break
            src = chunk.source
            if source_name and src != source_name:
                continue
            if per_source.get(src, 0) >= MAX_CHUNKS_PER_SOURCE:
                continue
            if total_chars + len(chunk.text) > MAX_CONTEXT_CHARS:
                continue
            picked.append(chunk)
            per_source[src] = per_source.get(src, 0) + 1
            total_chars += len(chunk.text)

        if not picked:
            return _NO_EVIDENCE_MESSAGE

        blocks = "\n\n".join(c.to_block() for c in picked)
        return (
            "【本轮证据包】以下片段来自候选人简历/材料（仅作追问依据）：\n\n"
            f"{blocks}\n\n"
            "证据使用硬规则：只能依据上述证据或候选人本轮亲述来评价/追问；"
            "证据未覆盖之处必须用澄清式追问核实，不得编造候选人经历。"
        )

    # ── 溯源（调试）──

    def trace_retrieval(self, user_text: str) -> list[dict]:
        """返回检索过程详情：各块命中词、得分、是否入选及原因。"""
        if not self.chunks:
            return []
        terms = extract_terms(user_text or "")
        ranked = self._score_chunks(terms)
        per_source: dict[str, int] = {}
        picked_ids: set[int] = set()
        total_chars = 0
        for chunk in ranked:
            src = chunk.source
            reason = ""
            if len(picked_ids) >= MAX_CONTEXT_CHUNKS:
                reason = "超总块数预算"
            elif per_source.get(src, 0) >= MAX_CHUNKS_PER_SOURCE:
                reason = "超单源预算"
            elif total_chars + len(chunk.text) > MAX_CONTEXT_CHARS:
                reason = "超总字符预算"
            else:
                picked_ids.add(chunk.chunk_id)
                per_source[src] = per_source.get(src, 0) + 1
                total_chars += len(chunk.text)
                reason = "入选"
            yield {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "matched_terms": chunk.matched_terms,
                "score": round(chunk.score, 1),
                "chars": len(chunk.text),
                "selected": chunk.chunk_id in picked_ids,
                "reason": reason,
            }


_NO_EVIDENCE_MESSAGE = (
    "【本轮证据包】本轮未检索到与当前回答直接相关的简历证据。"
    "请基于候选人本轮亲述进行评价与追问；如需核实其经历细节，请用澄清式追问，不要凭空编造。"
)


def build_evidence_package(
    resume_text: str,
    user_text: str,
    extra_documents: list[tuple[str, str, float]] | None = None,
) -> str:
    """便捷函数：一步构建检索器并返回【本轮证据包】。

    Args:
        resume_text: 简历全文（resume_parser 输出）。
        user_text: 候选人当前回答/提问。
        extra_documents: 可选附加材料 [(来源名, 文本, 优先级), ...]。
    """
    retriever = ResumeRetriever()
    if resume_text and resume_text.strip():
        retriever.add_document("简历", resume_text)
    if extra_documents:
        for name, text, priority in extra_documents:
            retriever.add_document(name, text, priority)
    return retriever.select_context(user_text)


def trace_retrieval(
    resume_text: str,
    user_text: str,
    extra_documents: list[tuple[str, str, float]] | None = None,
) -> list[dict]:
    """便捷函数：一步构建检索器并返回检索溯源（调试/测试用）。"""
    retriever = ResumeRetriever()
    if resume_text and resume_text.strip():
        retriever.add_document("简历", resume_text)
    if extra_documents:
        for name, text, priority in extra_documents:
            retriever.add_document(name, text, priority)
    return list(retriever.trace_retrieval(user_text))
