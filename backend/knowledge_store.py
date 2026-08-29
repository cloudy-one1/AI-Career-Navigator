"""
命名空间知识库（v6.0，L2 领域层）。

对标 career-copilot 的 SimpleRagService（极简 RAG）：
- 命名空间隔离：rag:interview / rag:career / rag:resume，互不串库；
- 检索复用 resume_retriever 的分块 + 关键词加权评分（本地、零第三方检索依赖）；
- augment_prompt 把检索结果以【参考知识库相关内容】块注入 System Prompt
  （对标其 augmentCall：只做 Prompt 增强，不在此发起 LLM 调用）。

与 resume_retriever 的分工：
- ResumeRetriever：单会话、单用途（简历证据包，输出格式固定为【本轮证据包】）；
- KnowledgeStore：跨用途、多命名空间的通用知识注入（Prompt 拼接）。

分层契约：本模块属 L2，仅依赖同层 resume_retriever；被 L3/L4 调用。
（对标项在原项目中用 Redis+向量，本项目按"零托管依赖"宪章约束降为关键词检索，
  适合知识条目 < 数千条的原型规模；规模上来后再考虑向量索引。）
"""

import logging

from .resume_retriever import (MAX_CONTEXT_CHARS, ResumeRetriever, content_hash,
                               extract_terms)

logger = logging.getLogger(__name__)

# 命名空间常量（对标 rag:interview / rag:career / rag:resume）
NAMESPACE_INTERVIEW = "rag:interview"
NAMESPACE_CAREER = "rag:career"
NAMESPACE_RESUME = "rag:resume"
DEFAULT_NAMESPACES = (NAMESPACE_INTERVIEW, NAMESPACE_CAREER, NAMESPACE_RESUME)


class KnowledgeStore:
    """多命名空间本地知识库。

    用法：
        store = get_knowledge_store()
        store.add_document(NAMESPACE_CAREER, "行业报告", text)
        hits = store.retrieve(NAMESPACE_CAREER, "候选人问题", top_k=3)
        prompt = store.augment_prompt(system_prompt, NAMESPACE_CAREER, user_query)
    """

    def __init__(self) -> None:
        self._retrievers: dict[str, ResumeRetriever] = {}

    # ── 命名空间管理 ──

    def _normalize_ns(self, namespace: str) -> str:
        """规范命名空间：允许简写 "career" → "rag:career"。"""
        ns = (namespace or NAMESPACE_RESUME).strip()
        if not ns.startswith("rag:"):
            ns = f"rag:{ns}"
        return ns

    def _retriever(self, namespace: str) -> ResumeRetriever:
        ns = self._normalize_ns(namespace)
        if ns not in self._retrievers:
            self._retrievers[ns] = ResumeRetriever()
        return self._retrievers[ns]

    def namespaces(self) -> list[str]:
        """返回当前已有内容的命名空间列表。"""
        return sorted(self._retrievers.keys())

    def clear(self, namespace: str | None = None) -> None:
        """清空指定命名空间；None 则清空全部。"""
        if namespace is None:
            self._retrievers.clear()
        else:
            self._retrievers.pop(self._normalize_ns(namespace), None)

    # ── 构建 ──

    def add_document(self, namespace: str, source: str, text: str,
                     priority: float | None = None) -> int:
        """向命名空间写入一份文档（自动分块），返回新增块数。"""
        r = self._retriever(namespace)
        before = len(r.chunks)
        r.add_document(source, text, priority)
        added = len(r.chunks) - before
        if added:
            logger.debug("[knowledge_store] %s <- %s 新增 %d 块",
                         self._normalize_ns(namespace), source, added)
        return added

    # ── 检索 ──

    def retrieve(self, namespace: str, query: str, top_k: int = 3,
                 exclude_hashes: set[str] | None = None) -> list[dict]:
        """在命名空间内检索与 query 相关的块，返回按得分降序的命中列表。

        预算硬限沿用 resume_retriever 的 MAX_CONTEXT_CHARS，防止 token 膨胀。

        exclude_hashes（v6.3 注入去重）：跳过指纹命中的块。过滤发生在**字符预算之前**，
        否则被过滤的名额会白占预算，把本可入选的新块挤掉。
        """
        r = self._retriever(namespace)
        if not r.chunks or top_k <= 0:
            return []
        terms = extract_terms(query or "")
        # v6.4: 同层复用双通道评分（关键词命中 + bigram 语义近似），见 resume_retriever
        ranked = r._score_chunks(terms, query_text=query or None)
        results: list[dict] = []
        total_chars = 0
        for c in ranked:
            if len(results) >= top_k:
                break
            fingerprint = c.fingerprint
            if exclude_hashes and fingerprint in exclude_hashes:
                continue
            if total_chars + len(c.text) > MAX_CONTEXT_CHARS:
                continue
            results.append({
                "namespace": self._normalize_ns(namespace),
                "source": c.source,
                "chunk_id": c.chunk_id,
                "matched_terms": list(c.matched_terms),
                "score": round(c.score, 1),
                "text": c.text,
                "content_hash": fingerprint,
            })
            total_chars += len(c.text)
        return results

    def has_content(self, namespace: str) -> bool:
        """命名空间是否已有可检索内容。"""
        return bool(self._retriever(namespace).chunks)

    def stats(self, namespace: str | None = None) -> dict:
        """命名空间统计（块数/来源数），None 则返回全部。"""
        targets = (
            {self._normalize_ns(namespace): self._retriever(namespace)}
            if namespace is not None
            else {ns: r for ns, r in self._retrievers.items() if r.chunks}
        )
        return {
            ns: {"chunks": len(r.chunks), "sources": len({c.source for c in r.chunks})}
            for ns, r in targets.items()
        }

    # ── Prompt 增强（对标 augmentCall）──

    def augment_prompt_tracked(self, system_prompt: str, namespace: str, query: str,
                               top_k: int = 3, exclude_hashes: set[str] | None = None,
                               header: str = "【参考知识库相关内容】") -> tuple[str, list[str]]:
        """可追踪版本：与 augment_prompt 行为一致，额外返回本轮实际注入块的指纹。

        上游（L3）持会话级集合累积这些指纹，下一轮通过 exclude_hashes 传入，
        即可避免长会话中同一段知识被反复拼进 prompt。

        注意：retrieve 内部已按 MAX_CONTEXT_CHARS 截断，**未入选的块不计入返回的指纹**，
        它们的指纹不会进缓存，下一轮仍有入选机会（不会因"被预算挤掉"而永久丢失）。

        Returns:
            (增强后的系统提示词, 本轮实际注入的内容指纹列表)
        """
        if not system_prompt:
            return system_prompt, []
        hits = self.retrieve(namespace, query, top_k=top_k, exclude_hashes=exclude_hashes)
        if not hits:
            return system_prompt, []
        ns = self._normalize_ns(namespace)
        blocks = "\n\n".join(
            f"[{h['source']}·#{h['chunk_id']}｜命中:{'、'.join(h['matched_terms']) or '无'}]\n"
            f"{h['text'].strip()}"
            for h in hits
        )
        logger.debug("[knowledge_store] augment_prompt ns=%s 注入 %d 块", ns, len(hits))
        return (
            f"{system_prompt}\n\n{header}（命名空间={ns}）\n"
            "以下内容来自本地知识库，仅供引用参考：据此回答可以，"
            "但严禁据此编造候选人的经历、项目细节或数据。\n\n"
            f"{blocks}"
        ), [h["content_hash"] for h in hits]

    def augment_prompt(self, system_prompt: str, namespace: str, query: str,
                       top_k: int = 3, exclude_hashes: set[str] | None = None,
                       header: str = "【参考知识库相关内容】") -> str:
        """把检索到的知识块拼进 System Prompt；无命中时原样返回（零副作用）。

        注入块附带"仅供参考、严禁编造"的使用约束，与简历证据包的
        反幻觉硬规则保持同一口径。

        exclude_hashes（v6.3）：排除指纹命中的块，用于跨轮注入去重。
        需要拿到本轮注入指纹时改用 augment_prompt_tracked()。
        """
        prompt, _ = self.augment_prompt_tracked(
            system_prompt, namespace, query, top_k, exclude_hashes, header
        )
        return prompt


# 模块级单例（对标 SimpleRagService 的依赖注入单例）
knowledge_store = KnowledgeStore()


def get_knowledge_store() -> KnowledgeStore:
    """获取全局知识库单例。"""
    return knowledge_store
