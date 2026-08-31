"""v2.2 题库管理域：CRUD / 收藏 / 从会话导入。"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import question_bank as qbank

router = APIRouter()


@router.get("/api/question-bank")
async def list_question_bank(
    round_type: Optional[str] = Query(None),
    difficulty: Optional[int] = Query(None),
    favorited: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出题库题目"""
    try:
        result = await qbank.list_bank({
            "round_type": round_type,
            "difficulty": difficulty,
            "favorited": favorited,
            "search": search,
            "source": source,
            "limit": limit,
            "offset": offset,
        })
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


class CreateQuestionRequest(BaseModel):
    question_text: str
    round_type: str = ""
    intent: str = ""
    tags: list[str] = []
    difficulty: int = 3


@router.post("/api/question-bank")
async def create_question_bank(req: CreateQuestionRequest):
    """添加题目"""
    try:
        result = await qbank.create_question(req.model_dump())
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


class UpdateQuestionRequest(BaseModel):
    question_text: Optional[str] = None
    round_type: Optional[str] = None
    intent: Optional[str] = None
    tags: Optional[list[str]] = None
    difficulty: Optional[int] = None
    is_favorited: Optional[bool] = None


@router.put("/api/question-bank/{question_id}")
async def update_question_bank(question_id: int, req: UpdateQuestionRequest):
    """更新题目"""
    try:
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        return await qbank.update_question_item(question_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/question-bank/{question_id}")
async def delete_question_bank(question_id: int):
    """删除题目"""
    try:
        return await qbank.delete_question_item(question_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/question-bank/{question_id}/favorite")
async def favorite_question_bank(question_id: int):
    """切换收藏"""
    try:
        return await qbank.favorite_question(question_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


class ImportQuestionsRequest(BaseModel):
    session_id: str


@router.post("/api/question-bank/import")
async def import_questions_bank(req: ImportQuestionsRequest):
    """从会话导入题目"""
    try:
        return await qbank.import_from_session(req.session_id)
    except Exception as e:
        raise HTTPException(500, str(e))
