"""知识库域（v8.17）：命名空间知识库的入库与统计。

knowledge_store 自 v6.0 就有完整的检索与 Prompt 增强能力，但一直没有生产入口
（LIMITATIONS 登记"未接入业务流"）。本路由补上入库侧；注入侧由
question_gen（rag:interview）与 career_planner（rag:career）在 v8.17 一并接通。

重要口径：知识库是**进程内存态**（零托管依赖宪章下的关键词检索，对标
SimpleRagService），进程重启即清空——本路由不做持久化，文档需要每次运行后
重新录入。规模上限与适用场景见 knowledge_store 模块头注释。
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import config
from ..knowledge_store import DEFAULT_NAMESPACES, get_knowledge_store
from . import state

logger = logging.getLogger(__name__)
router = APIRouter()

# 单文档上限：知识条目是"参考背景"而非全量语料，超长文档应拆分后分条录入
#（retrieve 内部有 MAX_CONTEXT_CHARS 预算，超长源会整体挤占预算）
MAX_KNOWLEDGE_CHARS = 50_000


class KnowledgeAddRequest(BaseModel):
    namespace: str = Field(..., description="命名空间：interview / career / resume（允许 rag: 前缀全写）")
    source: str = Field(..., min_length=1, max_length=120, description="来源标签（显示在注入块头部）")
    text: str = Field(..., min_length=1, description="文档正文（自动分块）")


@router.post("/api/knowledge")
@state.limiter.limit(config.RATE_LIMIT_SESSION)
async def add_knowledge(req: KnowledgeAddRequest, request: Request = None):
    """向命名空间录入一份文档（自动分块）。

    命名空间与用途：
      interview — 面试出题参考（行业/公司/技术背景，generate_round_questions 注入）
      career    — 职业规划参考（行业路径/岗位序列，plan_career 注入）
      resume    — 预留（简历证据当前走 ResumeRetriever 一线）
    """
    ns = req.namespace.strip()
    if f"rag:{ns}" not in DEFAULT_NAMESPACES and ns not in DEFAULT_NAMESPACES:
        raise HTTPException(400, f"未知命名空间: {req.namespace!r}。可用: interview / career / resume")

    text = req.text.strip()
    if not text:
        raise HTTPException(400, "文档内容为空")
    truncated = len(text) > MAX_KNOWLEDGE_CHARS
    if truncated:
        text = text[:MAX_KNOWLEDGE_CHARS]
        logger.warning(f"知识文档超长，截断到 {MAX_KNOWLEDGE_CHARS} 字符（source={req.source!r}）")

    store = get_knowledge_store()
    ns_normalized = ns if ns.startswith("rag:") else f"rag:{ns}"
    # v8.19: 分块+索引是纯 CPU 操作，丢线程执行——与 WS 面试主循环同处一个
    # 事件循环，50k 字符同步处理会短暂卡住所有在途面试
    added = await asyncio.to_thread(store.add_document, ns_normalized, req.source.strip(), text)
    logger.info(f"知识库录入: {ns_normalized} <- {req.source!r} 新增 {added} 块")
    return {
        "namespace": ns_normalized,
        "source": req.source.strip(),
        "chunks_added": added,
        "truncated": truncated,
        "stats": store.stats(ns_normalized),
    }


@router.get("/api/knowledge")
async def knowledge_stats():
    """各命名空间的块数 / 来源数（空命名空间不列出）。"""
    return {"namespaces": get_knowledge_store().stats()}
