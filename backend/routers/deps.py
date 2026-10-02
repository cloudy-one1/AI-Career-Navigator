"""路由层共用：上传白名单 + 「资源不存在」断言 + 内部异常统一出口。

本文件此前还承载认证依赖与归属断言（get_current_user /
require_user / assert_session_owner / assert_owner）。认证整体下线后，
只剩与身份无关的几样东西，故收缩到这一个文件里。
"""
import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# 允许上传的简历扩展名（三处上传端点共用，避免一边改了另一边漏）
ALLOWED_UPLOAD_EXT = (".pdf", ".docx", ".txt")

# 内部异常的固定回执文案（v8.19: 此前各路由 HTTPException(500, str(e)) 把
# 内部路径/库错误细节直接返回客户端，diagnostics.py 一处就有 8 个）
_INTERNAL_MSG = "服务器内部错误，请稍后重试"


def internal_error(e: Exception, action: str) -> HTTPException:
    """内部异常的统一出口：细节进日志留痕，客户端只拿固定文案。

    analytics.py / profile.py 早已是"泛化消息 + 日志留痕"的正确范本，
    本函数把它收敛为全路由层共用入口。
    """
    logger.error(f"{action}失败: {type(e).__name__}: {e}", exc_info=True)
    return HTTPException(500, _INTERNAL_MSG)


def ensure_found(row, what: str = "资源") -> dict:
    """资源不存在一律 404。

    为什么统一 404 而不是 404/403 分列：403 会暴露"这个 id 存在，只是你看不到"，
    可被用来枚举有效 id。单用户本地工具下这个顾虑已不存在，但 404 仍是
    "查无此物"最直白的语义，保留原样。
    """
    if not row:
        raise HTTPException(404, f"{what}不存在")
    return row
