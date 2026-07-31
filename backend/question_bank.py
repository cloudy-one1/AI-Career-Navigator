"""
题库管理 API 逻辑 v2.2。
提供题目 CRUD、收藏、导入等功能。
"""

import logging
from typing import Optional

from . import db

logger = logging.getLogger(__name__)

# 6 阶段名称列表
ROUND_TYPES = ["破冰环节", "技术广度", "技术深度", "项目拷问", "行为面试", "反问收尾"]


async def list_bank(params: dict) -> dict:
    """列出题库题目"""
    round_type = params.get("round_type")
    difficulty = params.get("difficulty")
    if difficulty is not None:
        try:
            difficulty = int(difficulty)
        except (ValueError, TypeError):
            difficulty = None

    favorited = params.get("favorited")
    if favorited is not None:
        favorited = favorited in ("1", "true", "True", True)

    search = params.get("search")
    source = params.get("source")
    try:
        limit = min(int(params.get("limit", 100)), 500)
    except (ValueError, TypeError):
        limit = 100
    try:
        offset = max(int(params.get("offset", 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    questions = await db.list_questions(
        round_type=round_type,
        difficulty=difficulty,
        favorited=favorited,
        search=search,
        source=source,
        limit=limit,
        offset=offset,
    )
    return {
        "questions": questions,
        "total": len(questions),
        "round_types": ROUND_TYPES,
    }


async def create_question(data: dict) -> dict:
    """创建新题目"""
    question_text = (data.get("question_text") or "").strip()
    if not question_text:
        raise ValueError("question_text 不能为空")

    round_type = data.get("round_type", "")
    if round_type and round_type not in ROUND_TYPES:
        raise ValueError(f"无效的 round_type，可选：{ROUND_TYPES}")

    difficulty = data.get("difficulty", 3)
    try:
        difficulty = max(1, min(5, int(difficulty)))
    except (ValueError, TypeError):
        difficulty = 3

    qid = await db.add_question(
        question_text=question_text,
        round_type=round_type,
        intent=data.get("intent", ""),
        tags=data.get("tags", []),
        difficulty=difficulty,
        source="manual",
    )
    return {"id": qid, "message": "创建成功"}


async def update_question_item(question_id: int, data: dict) -> dict:
    """更新题目"""
    if not await _exists(question_id):
        raise ValueError(f"题目 {question_id} 不存在")

    update_data = {}
    for key in ["question_text", "round_type", "intent", "tags", "difficulty", "is_favorited"]:
        if key in data:
            update_data[key] = data[key]

    if "round_type" in update_data and update_data["round_type"] not in ROUND_TYPES:
        raise ValueError(f"无效的 round_type，可选：{ROUND_TYPES}")

    if "difficulty" in update_data:
        try:
            update_data["difficulty"] = max(1, min(5, int(update_data["difficulty"])))
        except (ValueError, TypeError):
            raise ValueError("difficulty 必须是 1-5 的整数")

    await db.update_question(question_id, **update_data)
    return {"message": "更新成功"}


async def delete_question_item(question_id: int) -> dict:
    """删除题目"""
    if not await _exists(question_id):
        raise ValueError(f"题目 {question_id} 不存在")

    await db.delete_question(question_id)
    return {"message": "删除成功"}


async def favorite_question(question_id: int) -> dict:
    """切换收藏"""
    result = await db.toggle_favorite(question_id)
    if result is None:
        raise ValueError(f"题目 {question_id} 不存在")
    return {"question_id": question_id, "is_favorited": result}


async def import_from_session(session_id: str) -> dict:
    """从会话导入题目"""
    count = await db.import_questions_from_session(session_id)
    return {"imported_count": count, "message": f"从 {session_id} 导入了 {count} 道题目"}


async def _exists(question_id: int) -> bool:
    """检查题目是否存在"""
    questions = await db.list_questions(limit=1, offset=question_id - 1)
    for q in questions:
        if q.get("id") == question_id:
            return True
    return False
