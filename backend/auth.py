"""
认证与访问控制（L2）。

职责边界：
- 本模块负责「访问控制」：密码哈希、JWT 签发/校验、从请求解析当前用户。
- **不负责**内容检查（那是 security.py 的事，它面向面试回答内容，是启发式检查而非安全边界）。
  两个职责同名会制造认知负担，因此刻意分成两个模块。

分层：L2，只允许依赖 L1（config / db）。
鉴权的**组合**发生在 L4（main.py 用 Depends），本模块不感知具体 HTTP 端点。

开关语义（DC-06 承诺的回滚手段）：
    AUTH_ENABLED = False  →  get_current_user 返回匿名 UserContext(id=None)
                          →  所有归属过滤跳过，行为与 v6.x 完全一致
默认关闭，出问题可一键退回，不必改代码。

需求文档：docs/week8_认证与资源归属_需求.md
决策依据：CHARTER.md DC-06
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from . import db
from .config import config

logger = logging.getLogger(__name__)

# 用户名字符集：字母数字下划线连字符。排除空格与中文，
# 避免"两个看起来一样的用户名"（全角/半角、零宽字符）造成的归属歧义。
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

ANONYMOUS_ROLE = "anonymous"


# ===== 数据载体 =====

@dataclass(frozen=True)
class UserContext:
    """当前请求的用户身份。

    id 为 None 表示匿名（AUTH_ENABLED=false，或 token 无效时的降级态）。
    用 is_anonymous 而非直接判空，让调用点的意图可读。
    """

    id: Optional[str]
    username: str = ""
    role: str = ANONYMOUS_ROLE
    display_name: str = ""

    @property
    def is_anonymous(self) -> bool:
        return self.id is None

    @property
    def is_recruiter(self) -> bool:
        return self.role == "recruiter"


def anonymous_user() -> UserContext:
    return UserContext(id=None, role=ANONYMOUS_ROLE)


# ===== 密钥管理 =====

def _read_secret_file() -> str:
    """读取持久化的 JWT 密钥；文件不存在返回空串。"""
    path = config.AUTH_SECRET_FILE
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except OSError as e:
        logger.warning(f"[auth] 读取密钥文件失败，将退回环境变量: {e}")
    return ""


def _generate_and_persist_secret() -> str:
    """生成新密钥并持久化到 data/.auth_secret。

    为什么不每次启动随机生成：那会让所有已签发 token 在重启后失效，
    用户被迫重新登录，且排查时无法区分"token 过期"与"服务重启"。
    """
    import secrets

    secret = secrets.token_urlsafe(48)
    path = config.AUTH_SECRET_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 600 权限：仅属主可读写。Windows 上 chmod 支持有限，故失败只 warn 不阻断。
        with open(path, "w", encoding="utf-8") as f:
            f.write(secret)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        logger.warning(
            f"[auth] 未配置 AUTH_SECRET，已生成并持久化到 {path}（该文件须进 .gitignore）"
        )
    except OSError as e:
        logger.error(
            f"[auth] 密钥持久化失败，重启后所有 token 将失效: {e}"
        )
    return secret


def get_secret() -> str:
    """解析 JWT 签名密钥，优先级：环境变量 → 持久化文件 → 新建并持久化。"""
    if config.AUTH_SECRET:
        return config.AUTH_SECRET
    existing = _read_secret_file()
    if existing:
        return existing
    return _generate_and_persist_secret()


# ===== 密码哈希 =====

def hash_password(raw: str) -> str:
    """bcrypt 哈希。

    bcrypt 自带随机盐，无需自己管理盐值；
    默认 cost（12）刻意"慢"，使离线爆破成本高到不可行。
    """
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    """校验密码。任何异常一律返回 False（不区分"哈希损坏"与"密码错误"）。"""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError, AttributeError):
        return False


# ===== 注册/登录校验规则 =====

def validate_username(username: str) -> Optional[str]:
    """返回错误描述，合法返回 None。"""
    if not username:
        return "用户名不能为空"
    username = username.strip()
    if len(username) < config.AUTH_USERNAME_MIN_LENGTH:
        return f"用户名至少 {config.AUTH_USERNAME_MIN_LENGTH} 个字符"
    if len(username) > config.AUTH_USERNAME_MAX_LENGTH:
        return f"用户名最多 {config.AUTH_USERNAME_MAX_LENGTH} 个字符"
    if not USERNAME_RE.match(username):
        return "用户名只能包含字母、数字、下划线和连字符"
    return None


def validate_password(password: str) -> Optional[str]:
    """返回错误描述，合法返回 None。

    只校验长度，不校验复杂度：
    NIST SP 800-63B 已明确反对强制字符类别组合——它促使用户把规则
    套进可预测的模式（如 Password1!），实际强度反而低于长口令。
    """
    if not password:
        return "密码不能为空"
    if len(password) < config.AUTH_PASSWORD_MIN_LENGTH:
        return f"密码至少 {config.AUTH_PASSWORD_MIN_LENGTH} 位"
    if len(password) > 128:
        return "密码过长（上限 128 位）"
    if any(ord(c) > 127 for c in password):
        return "密码不能包含非 ASCII 字符"
    return None


def validate_role(role: Optional[str]) -> str:
    """非法角色回退 jobseeker，不抛异常（角色不是安全边界，权限由归属决定）。"""
    if role in config.AUTH_ROLES:
        return role
    return "jobseeker"


# ===== JWT =====

def create_access_token(user_id: str, role: str, username: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "username": username,
        "iat": now,
        "exp": now + timedelta(hours=config.AUTH_TOKEN_TTL_HOURS),
    }
    # JWT 是签名而非加密：payload 只是 base64，不可放敏感信息。
    # 这里只放 id/角色/用户名，均非敏感字段。
    return jwt.encode(payload, get_secret(), algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    """校验签名与过期；任何失败返回 None（调用方统一按未登录处理）。"""
    if not token:
        return None
    try:
        return jwt.decode(token, get_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        # 过期/签名错误/结构非法都走同一分支——不让调用方能借此区分攻击面
        return None


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """从 Authorization 头提取 Bearer token。"""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


# ===== 请求 → 用户身份 =====

async def _user_from_credentials(username: str, password: str) -> Optional[UserContext]:
    """校验账号密码。失败原因不区分——防用户名枚举。

    返回 None 表示"用户名或密码错误"，调用方统一返回 401。
    """
    if not username or not password:
        return None
    row = await db.get_user_by_username(username.strip())
    if not row:
        # 用户不存在时也执行一次哈希校验，使响应耗时与"密码错误"接近，
        # 避免通过响应时间枚举已注册用户名（计时攻击）。
        verify_password(password, "$2b$12$" + "0" * 53)
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    try:
        await db.touch_user_login(row["id"])
    except Exception as e:  # 登录时间写失败不应阻断登录
        logger.debug(f"[auth] 更新登录时间失败 user={row['username']}: {e}")
    return UserContext(
        id=row["id"],
        username=row["username"],
        role=row.get("role") or "jobseeker",
        display_name=row.get("display_name") or "",
    )


async def register_user(username: str, password: str,
                        role: Optional[str] = None,
                        display_name: Optional[str] = None) -> tuple[Optional[UserContext], Optional[str]]:
    """注册。返回 (用户, 错误描述)；成功时错误为 None。"""
    err = validate_username(username) or validate_password(password)
    if err:
        return None, err
    username = username.strip()
    if await db.get_user_by_username(username):
        return None, "用户名已被注册"
    user_id = str(uuid.uuid4())
    await db.create_user(
        user_id=user_id,
        username=username,
        password_hash=hash_password(password),
        role=validate_role(role),
        display_name=(display_name or "").strip() or None,
    )
    return (
        UserContext(
            id=user_id,
            username=username,
            role=validate_role(role),
            display_name=(display_name or "").strip(),
        ),
        None,
    )


async def authenticate(username: str, password: str) -> Optional[UserContext]:
    """登录。失败返回 None。"""
    return await _user_from_credentials(username, password)


async def user_from_token(token: Optional[str]) -> Optional[UserContext]:
    """由 token 解析用户；DB 中已不存在（被删）时返回 None。"""
    payload = decode_token(token) if token else None
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    row = await db.get_user_by_id(user_id)
    if not row:
        return None
    return UserContext(
        id=row["id"],
        username=row.get("username", ""),
        role=row.get("role") or "jobseeker",
        display_name=row.get("display_name") or "",
    )


async def resolve_ws_user(token: Optional[str]) -> UserContext:
    """WebSocket 专用：解析连接者身份。

    WS 握手无法用 Depends，且浏览器 WebSocket API 不支持自定义请求头，
    因此 token 只能走 query 参数（由前端拼在 URL 上）。

    注意：匿名模式下返回匿名 UserContext 而非 None —— 让调用方无论开不开认证
    都拿到一个可用对象，避免到处判空。
    """
    if not config.AUTH_ENABLED:
        return anonymous_user()
    user = await user_from_token(token)
    return user if user else anonymous_user()


async def can_access_session(user: UserContext, session_id: str) -> bool:
    """会话访问判定。

    - 认证关闭：一律放行（等同 v6.x）
    - 匿名身份（未登录）：一律拒绝——认证开启后不再允许"知道 id 就能进"
    - 登录身份：owner 匹配才放行
    """
    if not config.AUTH_ENABLED:
        return True
    if user.is_anonymous:
        return False
    owner = await db.get_session_owner(session_id)
    # owner 为 NULL（老库遗留数据）时按"不属于任何人"处理 → 拒绝。
    # 这与需求文档 §2.4 选用的方案一一致：严格、语义清晰，老数据不丢
    # （关掉 AUTH_ENABLED 仍可查看）。
    return owner is not None and owner == user.id


def ownership_filter(user: UserContext) -> Optional[str]:
    """生成归属过滤参数：匿名模式返回 None（不过滤），登录态返回 user.id。"""
    if not config.AUTH_ENABLED or user.is_anonymous:
        return None
    return user.id


# ===== FastAPI 依赖 =====

async def get_current_user(authorization: Optional[str] = None) -> UserContext:
    """HTTP 端点的当前用户依赖。

    main.py 用 `Depends(require_user)` / `Depends(get_optional_user)` 组合，
    本函数只做"从 Authorization 头解析"，不抛 HTTPException —— 抛异常是 L4 的职责，
    L2 保持与框架无关，便于单测。
    """
    if not config.AUTH_ENABLED:
        return anonymous_user()
    user = await user_from_token(extract_bearer_token(authorization))
    return user if user else anonymous_user()
