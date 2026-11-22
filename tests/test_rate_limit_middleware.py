"""限流中间件回归（v8.24）——证明 SlowAPIMiddleware 在位是 default_limits 生效的前提。

历史事故：main.py 此前只挂 limiter 与异常处理器、从不挂 SlowAPIMiddleware。
slowapi 的 default_limits 只在中间件（或显式装饰器）路径下执行，于是
RATE_LIMIT_GLOBAL 对未显式装饰的 46 条路由从未生效——"全局限流"长期是
装饰品，而每份文档都在声称存在全局限流。

与 test_layering_gate 同款的反向证伪纪律：先证明"缺中间件时配置空转"，
再证明"中间件在位时 429 会回来"。两个用例都配 429 文案口径（实际命中限额）。
"""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from limits import parse_many
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.wrappers import Limit

from backend.main import _rate_limit_exceeded_json


def _make_exc(limit_str: str) -> RateLimitExceeded:
    """构造带真实 Limit 对象的 RateLimitExceeded（slowapi 异常要求 wrapper 而非字符串）。"""
    limit = Limit(parse_many(limit_str)[0], key_func=get_remote_address, scope=None,
                  per_method=False, methods=None, error_message=None,
                  exempt_when=None, cost=1, override_defaults=False)
    return RateLimitExceeded(limit)


def _build_app(with_middleware: bool) -> FastAPI:
    """独立小应用：不触碰全局 state.limiter，避免污染其余测试的水位。"""
    app = FastAPI()
    app.state.limiter = Limiter(key_func=get_remote_address, default_limits=["3/minute"])

    @app.get("/ping")
    async def ping(request: Request):
        return {"ok": True}

    if with_middleware:
        app.add_middleware(SlowAPIMiddleware)
    return app


def test_default_limits_enforce_with_middleware():
    """中间件在位：第 4 次请求必须撞上 3/minute 的默认限额。"""
    client = TestClient(_build_app(True))
    codes = [client.get("/ping").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_default_limits_dead_without_middleware():
    """坏样本：不挂中间件时同样配置永远 200——缺中间件 = default_limits 空转。"""
    client = TestClient(_build_app(False))
    codes = [client.get("/ping").status_code for _ in range(5)]
    assert codes == [200] * 5


def test_429_message_carries_actual_limit():
    """429 文案必须带实际命中限额，而不是全局配置值（v8.24 前的复制粘贴错误）。"""
    exc = _make_exc("10 per 1 minute")
    resp = _rate_limit_exceeded_json(None, exc)
    assert resp.status_code == 429
    assert "10 per 1 minute" in resp.body.decode("utf-8")
