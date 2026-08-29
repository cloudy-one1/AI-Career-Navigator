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
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .config import config

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

# 单个词条命中的分值（v6.4 抽为常量：语义通道的加成量级以它为基准）
_TERM_HIT_WEIGHT = 8.0

# ── 语义近似通道（v6.4，借鉴 MockFlow 的零依赖混合召回）──
# 中文无分词按字符 bigram、英文按词计数，用余弦相似度近似"语义相似"。
# 零第三方依赖（对标项目用同一手法替代 Embedding），同义/改写召回短板由它补。
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_+-]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def bigram_tokens(text: str) -> Counter:
    """把文本拆成 token 集合（计数）：英文取 2+ 字符词，中文取相邻字符 bigram。"""
    low = (text or "").lower()
    tokens: list[str] = _ASCII_TOKEN_RE.findall(low)
    for run in _CJK_RUN_RE.findall(low):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return Counter(tokens)


def bigram_cosine(left: str, right: str) -> float:
    """两段文本的字符 bigram 余弦相似度（[0,1]）；任一侧为空返回 0。"""
    lt, rt = bigram_tokens(left), bigram_tokens(right)
    if not lt or not rt:
        return 0.0
    common = set(lt) & set(rt)
    if not common:
        return 0.0
    dot = sum(lt[t] * rt[t] for t in common)
    norm_l = math.sqrt(sum(v * v for v in lt.values()))
    norm_r = math.sqrt(sum(v * v for v in rt.values()))
    return dot / (norm_l * norm_r)


@dataclass
class EvidenceChunk:
    """单块候选证据。"""

    chunk_id: int
    text: str
    source: str = "简历"
    priority: float = DEFAULT_PRIORITY
    matched_terms: list[str] = field(default_factory=list)
    # v6.4: 语义近似通道（查询与块头的字符 bigram 余弦相似度及其分数加成）
    semantic_sim: float = 0.0
    semantic_bonus: float = 0.0

    @property
    def score(self) -> float:
        return self.priority + len(self.matched_terms) * _TERM_HIT_WEIGHT + self.semantic_bonus

    @property
    def fingerprint(self) -> str:
        """块内容稳定指纹（跨进程一致），供上游做注入去重。"""
        return content_hash(self.text)

    def to_block(self) -> str:
        if self.matched_terms:
            terms = "、".join(self.matched_terms)
        elif self.semantic_sim >= 0.01:
            # v6.4: 纯语义近似入选的块，标注依据来源（可解释性——为什么这条被选进证据包）
            terms = f"bigram 相似度 {self.semantic_sim:.2f}"
        else:
            terms = "无"
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

    def _score_chunks(self, terms: list[str],
                      query_text: str | None = None) -> list[EvidenceChunk]:
        """双通道评分（v6.4，借鉴 MockFlow 的零依赖混合召回）。

        通道一（稀疏，原有）：query 提取的关键词在块头命中；
        通道二（近似，新增）：查询全文与块头的字符 bigram 余弦相似度，
        补同义/改写召回（词命中为 0 但字面高度重叠的改写表述）。

        入选资格：命中词条即入选；零命中的块须通过"绝对下限 + 相对最高相似度"
        双闸（sim >= MIN_SIM 且 sim >= TOP_RATIO × 全场最高 sim）才入选——
        余弦相似度会被文本长度稀释，固定阈值不可用（见 config 注释）。
        近似通道只改"排序与补召回"，不放松"无关块不得进入证据包"的红线。
        query_text 为 None 时退化为纯词条通道（行为与 v6.3 完全一致）。
        """
        term_set = set(terms)
        for chunk in self.chunks:
            head = chunk.text[:SEARCH_HEAD_CHARS].lower()
            chunk.matched_terms = [t for t in term_set if t in head]
            chunk.semantic_bonus = 0.0
            chunk.semantic_sim = 0.0
            if query_text:
                sim = bigram_cosine(query_text, head)
                chunk.semantic_sim = round(sim, 4)
                if sim > 0:
                    chunk.semantic_bonus = round(
                        config.RETRIEVAL_SEMANTIC_WEIGHT * sim * _TERM_HIT_WEIGHT, 4)
        # 零词命中块的语义入选门槛（双闸取严）
        semantic_gate = 0.0
        if query_text is not None and self.chunks:
            top_sim = max(c.semantic_sim for c in self.chunks)
            if top_sim > 0:
                semantic_gate = max(config.RETRIEVAL_SEMANTIC_MIN_SIM,
                                    config.RETRIEVAL_SEMANTIC_TOP_RATIO * top_sim)
        # 仅保留命中关键词（或语义近似达标）的块，避免把无关块当证据塞进上下文
        hits = [
            c for c in self.chunks
            if c.matched_terms
            or (semantic_gate > 0 and c.semantic_sim >= semantic_gate)
        ]
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
        ranked = self._score_chunks(terms, query_text=user_text or None)

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
        ranked = self._score_chunks(terms, query_text=user_text or None)
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
                "semantic_sim": chunk.semantic_sim,
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
