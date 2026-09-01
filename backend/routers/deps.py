"""路由层共用：上传白名单 + 「资源不存在」断言。

v8.3 说明：本文件此前还承载认证依赖与归属断言（get_current_user /
require_user / assert_session_owner / assert_owner）。认证整体下线后
（CHARTER DC-10），只剩与身份无关的两样东西，故收缩到这一个文件里。
"""
from fastapi import HTTPException

# 允许上传的简历扩展名（三处上传端点共用，避免一边改了另一边漏）
ALLOWED_UPLOAD_EXT = (".pdf", ".docx", ".txt")


def ensure_found(row, what: str = "资源") -> dict:
    """资源不存在一律 404。

    为什么统一 404 而不是 404/403 分列：403 会暴露"这个 id 存在，只是你看不到"，
    可被用来枚举有效 id。单用户本地工具下这个顾虑已不存在，但 404 仍是
    "查无此物"最直白的语义，保留原样。
    """
    if not row:
        raise HTTPException(404, f"{what}不存在")
    return row
