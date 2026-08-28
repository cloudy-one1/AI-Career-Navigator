"""
简历轻量检索与证据包 (v5.0)

对标 agent-interview-coach 的 interview_corpus.py 思路：
本地关键词 + 优先级加权检索（无向量库），严格上下文预算，输出【本轮证据包】，
供诊断引擎与追问引擎在生成时"只能依据证据或候选人亲述"，杜绝编造经历。

分层契约：本模块属 L2 领域层，仅依赖 L1（config/logger），被 L3 业务层调用。
不引入任何第三方检索依赖（本地优先、零托管依赖）。

v6.3 注入去重（借鉴 HakiMeet 的 _injected_cache，并修正其缺陷）：
select_context_tracked() 在返回证据包的同时给出本轮入选块的稳定指纹，
上游（L3 InterviewSession）持会话级集合，下一轮检索时传入 exclude_hashes 过滤，
避免长会话中同一段简历证据被反复拼进 prompt。
指纹用 blake2b 而非内置 hash()——后者受 PYTHONHASHSEED 随机化影响，
进程重启即失效，无法跨会话保持一致（HakiMeet 即踩此坑）。
"""

import hashlib
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

    @property
    def fingerprint(self) -> str:
        """块内容稳定指纹（跨进程一致），供上游做注入去重。"""
        return content_hash(self.text)

    def to_block(self) -> str:
        terms = "、".join(self.matched_terms) if self.matched_terms else "无"
        return f"[证据 {self.source}·#{self.chunk_id}｜命中:{terms}]\n{self.text.strip()}"


def content_hash(text: str) -> str:
    """文本内容的稳定摘要（blake2b，8 字节十六进制）。

    为什么不用内置 hash()：内置 hash 对 str 带 PYTHONHASHSEED 随机化，
    同一文本在不同进程/重启后得到不同值，无法作为持久化的去重键。
    """
    return hashlib.blake2b((text or "").strip().encode("utf-8"),
                           digest_size=8).hexdigest()


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

    def _select(self, user_text: str, source_name: str | None,
                exclude_hashes: set[str] | None) -> list[EvidenceChunk]:
        """检索 + 预算筛选，返回入选块。

        顺序很关键：**先按 exclude_hashes 过滤，再走字符预算**。
        若先截断再过滤，被过滤掉的名额会白白占用预算，导致本可入选的新证据被挤掉。
        """
        if not self.chunks:
            return []
        terms = extract_terms(user_text or "")
        ranked = self._score_chunks(terms)

        # 预算：单源限制 + 总块数限制
        per_source: dict[str, int] = {}
        picked: list[EvidenceChunk] = []
        total_chars = 0
        for chunk in ranked:
            if len(picked) >= MAX_CONTEXT_CHUNKS:
                break
            if exclude_hashes and chunk.fingerprint in exclude_hashes:
                continue
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
        return picked

    def select_context_tracked(
        self, user_text: str, source_name: str | None = None,
        exclude_hashes: set[str] | None = None,
        allow_reuse_when_exhausted: bool = True,
    ) -> tuple[str, list[str]]:
        """与 select_context 相同，但额外返回本轮入选块的指纹列表。

        上游据此把已注入内容记入会话级缓存，下一轮通过 exclude_hashes 排除。

        allow_reuse_when_exhausted（默认开）：去重后若无任何新块，回退为
        **不过滤重检一次**。这不是可选项而是必需项——简历块总数有限，
        长会话后期所有块都会被注入过，若不做回退，证据包会恒为空，
        诊断侧将失去依据，去重反而造成能力退化。
        """
        picked = self._select(user_text, source_name, exclude_hashes)
        reused = False
        if not picked and exclude_hashes and allow_reuse_when_exhausted:
            picked = self._select(user_text, source_name, None)
            reused = bool(picked)
        if not picked:
            return _NO_EVIDENCE_MESSAGE, []
        if reused:
            logger.debug("[resume_retriever] 去重后无新证据，本轮回退复用已注入块")
        blocks = "\n\n".join(c.to_block() for c in picked)
        return (
            "【本轮证据包】以下片段来自候选人简历/材料（仅作追问依据）：\n\n"
            f"{blocks}\n\n"
            "证据使用硬规则：只能依据上述证据或候选人本轮亲述来评价/追问；"
            "证据未覆盖之处必须用澄清式追问核实，不得编造候选人经历。"
        ), [c.fingerprint for c in picked]

    def select_context(self, user_text: str, source_name: str | None = None,
                       exclude_hashes: set[str] | None = None) -> str:
        """按用户当前回答检索简历，组装【本轮证据包】。

        预算硬限：最多 MAX_CONTEXT_CHUNKS 块、单源 MAX_CHUNKS_PER_SOURCE、
        总字符 MAX_CONTEXT_CHARS。无匹配时返回提示语（诊断引擎据此转向澄清追问）。

        exclude_hashes（v6.3）：排除指纹命中的块，用于跨轮注入去重。
        只需证据包文本时用它；需要拿到指纹时改用 select_context_tracked()。
        """
        text, _ = self.select_context_tracked(user_text, source_name, exclude_hashes)
        return text

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
    exclude_hashes: set[str] | None = None,
) -> str:
    """便捷函数：一步构建检索器并返回【本轮证据包】。

    Args:
        resume_text: 简历全文（resume_parser 输出）。
        user_text: 候选人当前回答/提问。
        extra_documents: 可选附加材料 [(来源名, 文本, 优先级), ...]。
        exclude_hashes: v6.3，排除指纹命中的块（跨轮注入去重）。
    """
    retriever = ResumeRetriever()
    if resume_text and resume_text.strip():
        retriever.add_document("简历", resume_text)
    if extra_documents:
        for name, text, priority in extra_documents:
            retriever.add_document(name, text, priority)
    return retriever.select_context(user_text, exclude_hashes=exclude_hashes)


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
