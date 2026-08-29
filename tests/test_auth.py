"""
test_auth.py —— 认证层测试（v7.0 D1）

覆盖维度：
1. 密码哈希：正确/错误/损坏哈希都不抛异常
2. 注册/登录：成功、重复用户名、弱密码、错误密码
3. JWT：签发→解析往返、过期、篡改、Bearer 头提取
4. **开关回退（DC-06 的核心承诺）**：AUTH_ENABLED=false 时一切放行且身份为匿名
5. 归属隔离：A 不能访问 B 的会话；老库 owner=NULL 的会话在认证开启后不可访问
6. 防用户名枚举：用户不存在与密码错误的返回一致
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio

from backend import auth
from backend.config import config as cfg
from backend.db import init_db, save_session

# 长度 ≥32 字节，避免 PyJWT 的 InsecureKeyLengthWarning（RFC 7518 要求 HS256 密钥 ≥32B）
TEST_SECRET = "test-only-secret-not-for-production-0123456789abcdef"


@pytest_asyncio.fixture(autouse=True)
async def setup_auth(tmp_path):
    """隔离数据库 + 固定密钥（避免测试写 data/.auth_secret）+ 默认开启认证。"""
    original_db = cfg.DB_PATH
    original_secret = cfg.AUTH_SECRET
    original_enabled = cfg.AUTH_ENABLED
    cfg.DB_PATH = str(tmp_path / f"auth{uuid.uuid4().hex}.db")
    cfg.AUTH_SECRET = TEST_SECRET   # 非空 → get_secret() 不会生成/写密钥文件
    cfg.AUTH_ENABLED = True
    await init_db()
    yield
    cfg.DB_PATH = original_db
    cfg.AUTH_SECRET = original_secret
    cfg.AUTH_ENABLED = original_enabled


# ===== 1. 密码哈希 =====

class TestPasswordHashing:
    def test_hash_is_salted(self):
        """同一个密码两次哈希结果必须不同 —— 证明 bcrypt 自带随机盐。"""
        h1 = auth.hash_password("password123")
        h2 = auth.hash_password("password123")
        assert h1 != h2
        assert auth.verify_password("password123", h1)
        assert auth.verify_password("password123", h2)

    def test_verify_wrong_password(self):
        h = auth.hash_password("password123")
        assert not auth.verify_password("password124", h)

    def test_verify_corrupted_hash_returns_false(self):
        """损坏的哈希返回 False 而不是抛异常 —— 调用方不需要处理异常分支。"""
        assert not auth.verify_password("password123", "not-a-valid-hash")
        assert not auth.verify_password("password123", "")

    def test_utf8_password(self):
        # 中文密码：bcrypt 按字节处理，UTF-8 编解码必须正确往返
        h = auth.hash_password("密码password")
        assert auth.verify_password("密码password", h)
        assert not auth.verify_password("密码passwore", h)


# ===== 2. 输入校验 =====

class TestValidation:
    @pytest.mark.parametrize("username,expect_err", [
        ("ab", "至少"),                 # 过短
        ("a" * 33, "最多"),             # 过长
        ("has space", "只能包含"),       # 含空格
        ("中文名", "只能包含"),          # 含中文
        ("", "不能为空"),
        ("valid_user-1", None),         # 合法
    ])
    def test_validate_username(self, username, expect_err):
        err = auth.validate_username(username)
        if expect_err:
            assert err is not None and expect_err in err
        else:
            assert err is None

    @pytest.mark.parametrize("password,expect_err", [
        ("1234567", "至少"),            # 7 位，低于下限 8
        ("12345678", None),             # 合法（不强制字符类别，见实现注释）
        ("", "不能为空"),
        ("密码12345678", "非 ASCII"),    # 含中文
        ("x" * 129, "过长"),
    ])
    def test_validate_password(self, password, expect_err):
        err = auth.validate_password(password)
        if expect_err:
            assert err is not None and expect_err in err
        else:
            assert err is None

    def test_invalid_role_falls_back_to_jobseeker(self):
        assert auth.validate_role("admin") == "jobseeker"
        assert auth.validate_role(None) == "jobseeker"
        assert auth.validate_role("recruiter") == "recruiter"


# ===== 3. JWT =====

class TestToken:
    def test_roundtrip(self):
        token = auth.create_access_token("u1", "jobseeker", "alice")
        payload = auth.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "u1"
        assert payload["role"] == "jobseeker"
        assert payload["username"] == "alice"

    def test_expired_token_rejected(self):
        now = datetime.now(timezone.utc)
        expired = pyjwt.encode(
            {"sub": "u1", "role": "jobseeker",
             "iat": now - timedelta(hours=10),
             "exp": now - timedelta(hours=1)},
            TEST_SECRET, algorithm="HS256",
        )
        assert auth.decode_token(expired) is None

    def test_tampered_token_rejected(self):
        token = auth.create_access_token("u1", "jobseeker", "alice")
        # 改 payload 保留签名 → 验签必须失败（这正是 JWT 防篡改的意义）
        header, payload, signature = token.split(".")
        forged_payload = pyjwt.encode(
            {"sub": "u1", "role": "recruiter"},
            "wrong-secret-0123456789abcdefghijklmnop", algorithm="HS256",
        ).split(".")[1]
        assert auth.decode_token(f"{header}.{forged_payload}.{signature}") is None

    def test_malformed_token_rejected(self):
        for bad in ("", "not.a.token", "abc", "a.b.c.d"):
            assert auth.decode_token(bad) is None

    @pytest.mark.parametrize("header,expected", [
        ("Bearer abc.def.ghi", "abc.def.ghi"),
        ("bearer abc.def.ghi", "abc.def.ghi"),   # scheme 大小写不敏感
        ("Basic abc", None),
        ("abc", None),                            # 缺 scheme
        ("", None),
        (None, None),
    ])
    def test_extract_bearer(self, header, expected):
        assert auth.extract_bearer_token(header) == expected


# ===== 4. 注册 / 登录 =====

class TestRegisterAndLogin:
    @pytest.mark.asyncio
    async def test_register_then_login(self):
        user, err = await auth.register_user("alice", "password123")
        assert err is None and user is not None
        assert user.role == "jobseeker"
        assert not user.is_anonymous

        logged = await auth.authenticate("alice", "password123")
        assert logged is not None and logged.id == user.id

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self):
        await auth.register_user("alice", "password123")
        user, err = await auth.register_user("alice", "password456")
        assert user is None and "已被注册" in err

    @pytest.mark.asyncio
    async def test_register_weak_password_rejected(self):
        user, err = await auth.register_user("bob", "123")
        assert user is None and err is not None

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        await auth.register_user("alice", "password123")
        assert await auth.authenticate("alice", "wrong") is None

    @pytest.mark.asyncio
    async def test_login_unknown_user_matches_wrong_password_result(self):
        """防用户名枚举：不存在的用户与密码错误返回同一个值（None）。"""
        await auth.register_user("alice", "password123")
        unknown = await auth.authenticate("nobody", "password123")
        wrong_pwd = await auth.authenticate("alice", "wrong")
        assert unknown is None and wrong_pwd is None

    @pytest.mark.asyncio
    async def test_token_of_deleted_user_resolves_to_none(self):
        user, _ = await auth.register_user("alice", "password123")
        token = auth.create_access_token(user.id, user.role, user.username)
        assert await auth.user_from_token(token) is not None
        # 用户被删后，token 仍然有效签名但查无此人 → 必须拒绝
        from backend.db import get_db
        db = await get_db()
        try:
            await db.execute("DELETE FROM users WHERE id = ?", (user.id,))
            await db.commit()
        finally:
            await db.close()
        assert await auth.user_from_token(token) is None


# ===== 5. 开关回退（DC-06 的核心承诺）=====

class TestAuthDisabledFallback:
    @pytest.mark.asyncio
    async def test_resolve_ws_user_returns_anonymous_when_disabled(self):
        cfg.AUTH_ENABLED = False
        user = await auth.resolve_ws_user(None)
        assert user.is_anonymous
        assert user.id is None

    @pytest.mark.asyncio
    async def test_can_access_session_always_true_when_disabled(self):
        """认证关闭时任何会话都可访问 —— 这是"行为与 v6.x 完全一致"的底线。"""
        cfg.AUTH_ENABLED = False
        await save_session("s1", owner_id="someone-else")
        anon = auth.anonymous_user()
        assert await auth.can_access_session(anon, "s1")
        assert await auth.can_access_session(anon, "does-not-exist")

    @pytest.mark.asyncio
    async def test_ownership_filter_returns_none_when_disabled(self):
        cfg.AUTH_ENABLED = False
        assert auth.ownership_filter(auth.anonymous_user()) is None

    @pytest.mark.asyncio
    async def test_get_current_user_anonymous_when_disabled(self):
        cfg.AUTH_ENABLED = False
        user = await auth.get_current_user("Bearer valid.token.here")
        assert user.is_anonymous


# ===== 6. 归属隔离 =====

class TestOwnership:
    @pytest.mark.asyncio
    async def test_owner_can_access_own_session(self):
        await save_session("s1", owner_id="u1")
        user = auth.UserContext(id="u1", username="alice", role="jobseeker")
        assert await auth.can_access_session(user, "s1")

    @pytest.mark.asyncio
    async def test_other_user_cannot_access(self):
        await save_session("s1", owner_id="u1")
        other = auth.UserContext(id="u2", username="bob", role="jobseeker")
        assert not await auth.can_access_session(other, "s1")

    @pytest.mark.asyncio
    async def test_anonymous_cannot_access_when_enabled(self):
        """认证开启后，"知道 session_id 就能进"这条老路径必须被堵死。"""
        await save_session("s1", owner_id="u1")
        assert not await auth.can_access_session(auth.anonymous_user(), "s1")

    @pytest.mark.asyncio
    async def test_legacy_session_without_owner_is_inaccessible(self):
        """老库遗留会话（owner=NULL）：认证开启后不可访问，但数据未丢。

        对应需求文档 §2.4 方案一：严格、语义清晰。
        关掉 AUTH_ENABLED（上一个 TestCase 已验证）仍可查看，故不是数据丢失。
        """
        await save_session("legacy1")  # 不传 owner_id → NULL
        user = auth.UserContext(id="u1", username="alice", role="jobseeker")
        assert not await auth.can_access_session(user, "legacy1")

    @pytest.mark.asyncio
    async def test_ownership_filter_matches_owner(self):
        user = auth.UserContext(id="u1", username="alice", role="jobseeker")
        assert auth.ownership_filter(user) == "u1"
        assert auth.ownership_filter(auth.anonymous_user()) is None

    @pytest.mark.asyncio
    async def test_ws_user_resolution_with_valid_token(self):
        user, _ = await auth.register_user("alice", "password123")
        token = auth.create_access_token(user.id, user.role, user.username)
        resolved = await auth.resolve_ws_user(token)
        assert not resolved.is_anonymous
        assert resolved.id == user.id

        bad = await auth.resolve_ws_user("garbage")
        assert bad.is_anonymous
