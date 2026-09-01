"""v7.0 资产域：简历库 / 岗位库（可复用输入资产）。

这两个实体的意义在"跨会话复用"：同一份简历想练第二场不用重新上传、重新解析
（解析要调 LLM）。岗位同理——JD 不必每次粘贴。
"""
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ..config import config
from ..db import (
    save_resume, get_resume, list_resumes, update_resume, delete_resume,
    save_position, get_position, list_positions, update_position, delete_position,
)
from ..resume_parser import parse_resume
from ..schemas import (
    ResumeCreateRequest, ResumeUpdateRequest,
    PositionCreateRequest, PositionUpdateRequest,
)
from . import state
from .deps import ensure_found, ALLOWED_UPLOAD_EXT

router = APIRouter()


@router.get("/api/resumes")
async def api_list_resumes():
    """列表不含 raw_text（可能上万字符，N 条会把响应撑到几 MB）。"""
    return {"resumes": await list_resumes()}


@router.post("/api/resumes/upload", status_code=201)
@state.limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload_resume_to_library(file: UploadFile = File(...),
                                  request: Request = None):
    """上传简历并写入简历库。

    为什么不复用 /api/sessions/upload：那个接口为兼容既有前端把文本截断到 5000 字。
    截断用于"临时上传后立刻开练"尚可，用于**入库**则不可接受 —— 截断是静默的，
    用户下次选用这份简历时看不到任何异常，但 LLM 看到的简历是不完整的，
    出题质量随之下降且无从归因。
    """
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大，上限 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    if not file.filename:
        raise HTTPException(400, "缺少文件名")
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 {ALLOWED_UPLOAD_EXT}")

    raw_text = parse_resume(content, filename=file.filename)
    if not raw_text or not raw_text.strip():
        raise HTTPException(400, "未能从文件中提取到文本，请确认文件内容")
    resume_id = uuid.uuid4().hex[:12]
    title = file.filename.rsplit(".", 1)[0] or "未命名简历"
    await save_resume(resume_id, title=title, raw_text=raw_text,
                      filename=file.filename)
    row = await get_resume(resume_id)
    row.pop("raw_text", None)   # 回执不需要回传全文
    return {"resume": row}


@router.post("/api/resumes", status_code=201)
async def api_create_resume(req: ResumeCreateRequest):
    resume_id = uuid.uuid4().hex[:12]
    await save_resume(
        resume_id, title=req.title.strip() or "未命名简历", raw_text=req.raw_text,
        filename=req.filename, parsed_json=req.parsed_json,
    )
    row = await get_resume(resume_id)
    row.pop("raw_text", None)
    return {"resume": row}


@router.get("/api/resumes/{resume_id}")
async def api_get_resume(resume_id: str):
    return {"resume": ensure_found(await get_resume(resume_id), "简历")}


@router.patch("/api/resumes/{resume_id}")
async def api_update_resume(resume_id: str, req: ResumeUpdateRequest):
    ensure_found(await get_resume(resume_id), "简历")
    await update_resume(resume_id, title=req.title, parsed_json=req.parsed_json)
    row = await get_resume(resume_id)
    row.pop("raw_text", None)
    return {"resume": row}


@router.delete("/api/resumes/{resume_id}")
async def api_delete_resume(resume_id: str):
    ensure_found(await get_resume(resume_id), "简历")
    await delete_resume(resume_id)
    return {"ok": True}


@router.get("/api/positions")
async def api_list_positions():
    return {"positions": await list_positions()}


@router.post("/api/positions", status_code=201)
async def api_create_position(req: PositionCreateRequest):
    position_id = uuid.uuid4().hex[:12]
    await save_position(
        position_id, title=req.title.strip() or "未命名岗位", jd_text=req.jd_text,
        department=req.department,
    )
    return {"position": await get_position(position_id)}


@router.get("/api/positions/{position_id}")
async def api_get_position(position_id: str):
    return {"position": ensure_found(await get_position(position_id), "岗位")}


@router.patch("/api/positions/{position_id}")
async def api_update_position(position_id: str, req: PositionUpdateRequest):
    ensure_found(await get_position(position_id), "岗位")
    await update_position(position_id, title=req.title, jd_text=req.jd_text,
                          department=req.department)
    return {"position": await get_position(position_id)}


@router.delete("/api/positions/{position_id}")
async def api_delete_position(position_id: str):
    ensure_found(await get_position(position_id), "岗位")
    await delete_position(position_id)
    return {"ok": True}
