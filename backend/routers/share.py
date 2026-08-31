"""v7.0/v7.0.1 分享域：报告分享链接 + 招聘者收件箱 + 免登录只读 + 分享页 HTML。

权限口径：
  POST   /api/sessions/{id}/share    需登录 + 会话归属（只有本人能分享自己的报告）
  GET    /api/sessions/{id}/shares   需登录 + 会话归属
  DELETE /api/shares/{token}         需登录 + 创建者匹配
  GET    /api/shared/{token}         **免登录** —— 拿链接的是外部 HR，不该被要求注册
免登录读取的安全性由"高熵随机 token + 只存摘要 + 可撤销 + 可过期"保证，
而不是靠"知道链接的人是谁"。
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Response

from ..config import config
from ..db import get_session, get_report
from ..schemas import ShareCreateRequest
from .. import share_access
from .deps import require_user, assert_session_owner

router = APIRouter()


@router.post("/api/sessions/{session_id}/share", status_code=201)
async def create_share(session_id: str, req: ShareCreateRequest,
                       user: "auth.UserContext" = Depends(require_user)):
    await assert_session_owner(session_id, user)
    # 先判会话存在（404，与归属同一口径），再判报告存在（400，属用法错误）。
    # 顺序不能反，否则"会话不存在"会被报成 400，泄露了与越权场景不同的响应特征。
    if not await get_session(session_id):
        raise HTTPException(404, "会话不存在或无权访问")
    if not await get_report(session_id):
        raise HTTPException(400, "该会话还没有生成报告，无法分享")
    try:
        link = await share_access.create_share_link(
            session_id, created_by=user.id, include_detail=req.include_detail,
            expires_days=req.expires_days, shared_with=req.shared_with)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    # 明文 token 只在这一次响应中出现，之后无法再从库中还原
    return {"share": link, "url": f"/share/{link['token']}"}


@router.get("/api/sessions/{session_id}/shares")
async def list_shares(session_id: str,
                      user: "auth.UserContext" = Depends(require_user)):
    await assert_session_owner(session_id, user)
    return {"shares": await share_access.list_share_links(session_id)}


@router.delete("/api/shares/{token}")
async def revoke_share(token: str,
                       user: "auth.UserContext" = Depends(require_user)):
    try:
        await share_access.revoke_share_link(token, user.id)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    return {"ok": True}


@router.get("/api/shared/{token}")
async def read_shared_report(token: str):
    """免登录只读。任何不合法情况统一 404 —— 不区分"不存在/已撤销/已过期"。

    统一措辞是有意的：若三者的响应不同，攻击者就能用响应差异枚举有效令牌。
    """
    try:
        payload = await share_access.resolve_shared_report(token)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    return payload


# ===== v7.0.1: 招聘者收件箱（登录态下的受控读取）=====
#
# 与免登录的 /api/shared/{token} 是两条独立通道：收件箱按登录身份
# （shared_with=当前招聘者用户名）过滤，报告数据直接随接口返回，
# 不经过"凭明文 token"的免登录端点——两条通道互不放大对方的风险面。

@router.get("/api/recruiter/inbox")
async def recruiter_inbox(user: "auth.UserContext" = Depends(require_user)):
    """招聘者的"收到的报告"列表（摘要层）。仅 recruiter 角色可用。"""
    if config.AUTH_ENABLED and user.role != "recruiter":
        raise HTTPException(403, "仅招聘者账户可访问收件箱")
    return {"reports": await share_access.recruiter_inbox(user.username)}


@router.get("/api/recruiter/reports/{token_hash}")
async def recruiter_open_report(token_hash: str,
                                user: "auth.UserContext" = Depends(require_user)):
    """招聘者打开收件箱中的一份报告（完整脱敏载荷）。仅发件指定的本人可见。"""
    if config.AUTH_ENABLED and user.role != "recruiter":
        raise HTTPException(403, "仅招聘者账户可访问收件箱")
    try:
        payload = await share_access.open_inbox_report(token_hash, user.username)
    except share_access.ShareAccessError as e:
        raise HTTPException(e.status_code, str(e))
    return payload


# ===== v7.0: 招聘端分享页（独立入口）=====
# 必须注册在静态挂载之前：/share/{token} 是业务路由，不是静态文件，
# 若被 StaticFiles 先接管就会 404。（main.py 的 include_router 先于静态挂载执行）

@router.get("/share/{token}")
async def share_page(token: str):
    """返回分享页 HTML。

    页面本身不含任何报告数据 —— 数据由前端拿 token 再去请求 /api/shared/{token}。
    这样"页面"与"数据"的权限口径可以各自独立演进：
    页面谁都能拿，数据过不过得了关由接口决定。
    """
    dist_html = os.path.join("frontend", "dist", "share.html")
    src_html = os.path.join("frontend", "share.html")
    path = dist_html if os.path.isfile(dist_html) else src_html
    try:
        with open(path, "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/html; charset=utf-8")
    except OSError:
        raise HTTPException(500, "分享页模板缺失")
