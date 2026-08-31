"""档案域：求职档案（Profile）读取——首屏「能力档案」的数据源（v8.0 引入，v8.1 定名）。

档案是产品闭环的核心：把散在 resumes / positions / reports / weakness_memory /
market.db 的画像投影成一组统一状态，并给出「下一步该做什么」。

不登录也能用（owner_id=None → 匿名档案），与产品"不登录也能正常使用"的既有
约定一致；任一段聚合失败只降级该段，接口不 500——档案是首屏，白屏代价太大。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import config
from .. import auth, profile_service
from ..schemas import ProfileResponse
from . import state
from .deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/profile", response_model=ProfileResponse)
@state.limiter.limit(config.RATE_LIMIT_GLOBAL)
# request 参数不是摆设：slowapi 的限流装饰器要求被装饰函数签名里必须有
# request（或 websocket），否则注册路由时直接抛错。
async def get_profile(request: Request = None,
                      user: "auth.UserContext" = Depends(get_current_user)):
    """求职档案：当前简历 / 目标岗位 / 能力水平 / 待提升项 + 下一步建议。

    结果带 60 秒进程内缓存（切 tab 是主要调用场景）；用户上传简历或岗位后
    由对应路由调 profile_service.invalidate_profile_cache() 主动失效。
    """
    try:
        owner_id = None if user.is_anonymous else user.id
        profile = await profile_service.get_profile(owner_id=owner_id)
        return ProfileResponse(**profile)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"求职档案聚合失败: {type(e).__name__}: {e}")
        raise HTTPException(500, "档案服务暂时不可用，请稍后重试")


@router.post("/api/profile/refresh")
async def refresh_profile(user: "auth.UserContext" = Depends(get_current_user)):
    """档案缓存失效（面试出报告后由前端调用）。

    为什么需要它：档案带 60 秒 TTL 缓存，若不主动失效，用户完成一场模拟面试后
    要等最多一分钟才在能力档案看到变化——而"演完成档就更新"正是闭环最需要被
    看见的那一刻。失效失败不影响主流程（最坏情况是继续用一会儿旧缓存）。
    """
    try:
        owner_id = None if user.is_anonymous else user.id
        profile_service.invalidate_profile_cache(owner_id)
        return {"status": "ok"}
    except Exception as e:
        logger.warning(f"档案缓存失效失败，按继续使用旧缓存处理: {e}")
        return {"status": "ok"}
