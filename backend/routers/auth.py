"""认证域：注册 / 登录 / 当前身份。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import auth
from ..config import config
from ..schemas import RegisterRequest, LoginRequest, TokenResponse, UserInfo
from . import state
from .deps import get_current_user

router = APIRouter()


@router.post("/api/auth/register", response_model=TokenResponse, status_code=201)
@state.limiter.limit(config.RATE_LIMIT_SESSION)
async def register(req: RegisterRequest, request: Request = None):
    """注册并直接签发 token。

    注意参数名必须是 `request`：slowapi 的限流装饰器靠参数名注入请求对象，
    改名（如 http_request）会让它抛 `No "request" argument`。

    认证关闭时仍可用（行为与开启时一致）：开关只影响"是否强制要求登录"，
    不影响认证功能本身，前端因此无需为两种模式写两套代码。
    """
    user, err = await auth.register_user(
        req.username, req.password,
        role=req.role.value if hasattr(req.role, "value") else str(req.role),
        display_name=req.display_name,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.role, user.username),
        expires_in_hours=config.AUTH_TOKEN_TTL_HOURS,
        user=UserInfo(id=user.id, username=user.username, role=user.role,
                      display_name=user.display_name, is_anonymous=False),
    )


@router.post("/api/auth/login", response_model=TokenResponse)
@state.limiter.limit(config.RATE_LIMIT_SESSION)
async def login(req: LoginRequest, request: Request = None):
    """登录。用户名不存在与密码错误返回同一条消息（防用户名枚举）。"""
    user = await auth.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResponse(
        access_token=auth.create_access_token(user.id, user.role, user.username),
        expires_in_hours=config.AUTH_TOKEN_TTL_HOURS,
        user=UserInfo(id=user.id, username=user.username, role=user.role,
                      display_name=user.display_name, is_anonymous=False),
    )


@router.get("/api/auth/me", response_model=UserInfo)
async def me(user: "auth.UserContext" = Depends(get_current_user)):
    """当前身份。匿名模式（AUTH_ENABLED=false）返回 is_anonymous=true。"""
    return UserInfo(id=user.id, username=user.username, role=user.role,
                    display_name=user.display_name, is_anonymous=user.is_anonymous)
