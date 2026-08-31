"""路由依赖与归属断言（认证/归属在 L4 的组合点）。

auth.py（L2）本身不感知 HTTP——FastAPI 依赖注入、401/404 语义都在这一层组装。
"""
from fastapi import Depends, HTTPException, Request

from .. import auth
from ..config import config

# 允许上传的简历扩展名（三处上传端点共用，避免一边改了另一边漏）
ALLOWED_UPLOAD_EXT = (".pdf", ".docx", ".txt")


async def get_current_user(http_request: Request) -> "auth.UserContext":
    """解析当前用户。AUTH_ENABLED=false 时恒返回匿名（行为等同 v6.x）。"""
    return await auth.get_current_user(http_request.headers.get("authorization"))


async def require_user(user: "auth.UserContext" = Depends(get_current_user)) -> "auth.UserContext":
    """要求登录。认证关闭时不拦截（保持开关语义一致）。"""
    if config.AUTH_ENABLED and user.is_anonymous:
        raise HTTPException(status_code=401, detail="需要登录后操作")
    return user


async def assert_session_owner(session_id: str, user: "auth.UserContext") -> None:
    """会话归属断言。

    **一律返回 404 而非 403**：403 会暴露"这个 session_id 存在，只是你没权限"，
    攻击者可据此枚举有效会话 id。404 让"不存在"与"无权访问"无法区分。
    """
    if not config.AUTH_ENABLED:
        return
    if not await auth.can_access_session(user, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")


def assert_owner(row, user: "auth.UserContext") -> None:
    """库资源归属断言：他人的资源一律 404（不泄露存在性），老数据 owner=NULL 时同样拒绝。"""
    if not row:
        raise HTTPException(404, "资源不存在或无权访问")
    if config.AUTH_ENABLED and not user.is_anonymous and row.get("owner_id") != user.id:
        raise HTTPException(404, "资源不存在或无权访问")
