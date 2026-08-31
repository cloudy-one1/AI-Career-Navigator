"""
[v8.1] 档案接口层测试：GET /api/profile、POST /api/profile/refresh。

服务层（profile_service）的纯函数由 test_profile_service.py 覆盖，这里只钉住
**接口层**才存在的三条承诺：

1. **新增字段在响应里结构稳定**：journey / level.history / target.skill_gap。
   前端按这些字段渲染（侧栏三态、成长曲线、技能缺口），缺一个就是白屏或
   undefined.length 崩溃——服务层有默认值不等于接口层一定带得出来。
2. **未登录可用且不报错**：产品约定"不登录也能正常使用"，首屏尤其不能 401。
3. **refresh 能穿透缓存**：完成一场面试 / 上传简历后，档案必须立即反映最新
   数据，而不是等 TTL 自然过期（"演完成档就更新"是 P0 的核心体验）。
"""
import uuid

import pytest
import pytest_asyncio

import backend.db as db_mod
from backend import profile_service
from backend.config import config


@pytest_asyncio.fixture(autouse=True)
async def fresh_db(tmp_path):
    original_db = config.DB_PATH
    original_market = config.MARKET_DB_PATH
    config.DB_PATH = str(tmp_path / f"p{uuid.uuid4().hex}.db")
    config.MARKET_DB_PATH = str(tmp_path / f"m{uuid.uuid4().hex}.db")
    db_mod._db = None
    await db_mod.init_db()
    profile_service.invalidate_profile_cache()
    yield
    config.DB_PATH = original_db
    config.MARKET_DB_PATH = original_market
    db_mod._db = None
    profile_service.invalidate_profile_cache()


def test_profile_response_carries_all_new_fields(client):
    """空档案也要带齐 v8.1 的三个新字段——前端按它们渲染，缺一个就崩。"""
    res = client.get("/api/profile")
    assert res.status_code == 200
    data = res.json()

    assert set(["identity", "target", "level", "gaps", "journey", "next_action"]) <= set(data)

    journey = data["journey"]
    assert journey["total"] == 5
    assert len(journey["steps"]) == 5
    assert journey["completed"] == 0
    # 每一步的 state 必须是三态之一，不能出现前端无法映射的值
    assert {s["state"] for s in journey["steps"]} <= {"done", "current", "todo"}

    assert data["level"]["history"] == []
    assert data["target"]["skill_gap"] == {"matched": [], "missing": [], "market_total": 0}
    # 空档案的下一步必须是"建立档案基线"——首屏不能给出无意义的建议
    assert data["next_action"]["target_tab"] == "resume-library"


def test_profile_works_without_login(client):
    """未登录可用：首屏是默认落地页，401 会让整个产品打不开。"""
    res = client.get("/api/profile")
    assert res.status_code == 200
    assert res.json()["degraded"] == []


def test_refresh_penetrates_cache(client):
    """上传简历后调 refresh，档案必须立刻反映——否则用户要等 60 秒才看到变化。"""
    # 1) 先取一次，把空档案写进缓存
    first = client.get("/api/profile").json()
    assert first["identity"]["has_resume"] is False

    # 2) 直接落库一份简历（走数据层，绕开接口）
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        db_mod.save_resume("r-api-1", "测试简历", "张三 Python 后端工程师 " * 5))
    # 缓存未失效：仍然看不到新简历（这正是 TTL 的预期行为）
    assert client.get("/api/profile").json()["identity"]["has_resume"] is False

    # 3) 主动失效后立即可见
    assert client.post("/api/profile/refresh").status_code == 200
    assert client.get("/api/profile").json()["identity"]["has_resume"] is True


def test_journey_step_completes_after_resume(client):
    """落一份简历 → 第②步「简历准备」转为已完成，第①步成为 current。"""
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        db_mod.save_resume("r-api-2", "测试简历", "张三 Python 后端工程师 " * 5))
    client.post("/api/profile/refresh")

    journey = client.get("/api/profile").json()["journey"]
    states = {s["key"]: s["state"] for s in journey["steps"]}
    assert states["resume"] == "done"
    assert states["positioning"] == "current"
    assert journey["completed"] == 1
