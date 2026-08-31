"""报告域：综合报告读取 + 复盘 Markdown 导出 + HTML 导出（浏览器打印即得 PDF）。"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from typing import Optional

from ..config import config
from ..db import get_report
from ..interview_engine.report import generate_review_markdown
from .. import auth
from .deps import require_user, get_current_user, assert_session_owner

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/reports/{session_id}")
async def api_get_report(session_id: str,
                         user: "auth.UserContext" = Depends(require_user)):
    """报告含完整的简历事实与逐题诊断，是隐私敏感度最高的端点，必须校验归属。"""
    await assert_session_owner(session_id, user)
    report = await get_report(session_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    return {"report": dict(report)}


@router.get("/api/reports/{session_id}/review")
async def export_review(session_id: str):
    """导出复盘 Markdown 文件"""
    try:
        report = await get_report(session_id)
        if not report:
            raise HTTPException(404, "报告不存在")
        # v3.3: get_report 返回含 report_json 字符串的行，需解析后再交给导出函数
        # （此前直接传行对象，导出的复盘内容全为空）
        report = json.loads(report["report_json"]) if isinstance(report.get("report_json"), str) else report
        md = generate_review_markdown(report)
        return Response(content=md, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=review_{session_id}.md"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成复盘文件失败: {e}")
        raise HTTPException(500, str(e))


# ===== v6.1: 复盘报告 HTML 导出（借鉴 offerMaster report_pdf.py 的 MD→HTML 模板渲染） =====
# 用浏览器打印（Ctrl+P → 另存为 PDF）替代 weasyprint 服务端出 PDF：
# weasyprint 依赖 GTK/Pango，Windows 部署成本高；HTML 模板 + 打印样式零重量级依赖。
# v7.3: 模板换「纸墨印章」皮肤——与主应用报告页/分享页同一张脸
#（米纸底 #F4F2ED / 印章红 #C44F3A / 黄铜 #A08945 / 衬线标题），截图打印都代表产品形象。

_REPORT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: "Noto Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif;
         max-width: 820px; margin: 24px auto; padding: 0 20px 48px; color: #1F2320;
         line-height: 1.75; background: #F4F2ED; }}
  /* 品牌行：印章 + 报告眉标（与 SPA 报告页同构） */
  .doc-brand {{ display: flex; align-items: center; gap: 10px; padding: 20px 0 12px;
               font-family: "Noto Serif SC", "Songti SC", serif; }}
  .doc-seal {{ width: 34px; height: 34px; border-radius: 50%; background: #C44F3A; color: #fff;
              display: inline-flex; align-items: center; justify-content: center;
              font-weight: 900; font-size: 15px; transform: rotate(-6deg); flex-shrink: 0; }}
  .doc-brand-name {{ font-weight: 900; font-size: 16px; letter-spacing: 0.02em; }}
  .doc-brand-sub {{ color: #667066; font-size: 12px; margin-left: auto; letter-spacing: 0.1em; }}
  h1 {{ font-family: "Noto Serif SC", "Songti SC", serif; font-weight: 900;
       border-bottom: 2.5px solid #C44F3A; padding-bottom: 10px; margin: 6px 0 18px; }}
  h2 {{ font-family: "Noto Serif SC", "Songti SC", serif; font-weight: 700;
       border-bottom: 1px solid #DAD6CC; padding-bottom: 5px; margin-top: 30px; }}
  h3, h4 {{ font-weight: 700; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; background: #FCFAF6;
          border: 1px solid #DAD6CC; border-radius: 8px; overflow: hidden; }}
  th, td {{ border-bottom: 1px solid #E7E4DC; padding: 7px 12px; text-align: left; font-size: 14px; }}
  th {{ background: #EFECE4; font-weight: 600; }}
  tr:last-child td {{ border-bottom: none; }}
  blockquote {{ border-left: 3px solid #A08945; margin: 8px 0; padding: 6px 14px;
               color: #4A524B; background: rgba(160, 137, 69, 0.07); border-radius: 0 8px 8px 0;
               font-size: 14px; }}
  strong {{ color: #9B3025; }}
  code {{ background: #EFECE4; padding: 1px 5px; border-radius: 4px;
         font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 13px; }}
  pre {{ background: #EFECE4; padding: 12px; border-radius: 8px; overflow-x: auto;
        border: 1px solid #DAD6CC; }}
  hr {{ border: none; border-top: 1px dashed #DAD6CC; margin: 24px 0; }}
  .print-btn {{ position: fixed; right: 22px; bottom: 22px; padding: 9px 18px; cursor: pointer;
               background: #C44F3A; color: #fff; border: none; border-radius: 999px;
               font-size: 14px; font-weight: 600; box-shadow: 0 6px 20px rgba(196, 79, 58, 0.3); }}
  .print-btn:hover {{ background: #A83E2E; }}
  @media print {{
    body {{ margin: 0; max-width: none; background: #fff; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="doc-brand">
  <span class="doc-seal">面</span>
  <span class="doc-brand-name">AI 求职陪跑 · 复盘报告</span>
  <span class="doc-brand-sub">INTERVIEW REVIEW</span>
</div>
<button class="print-btn no-print" onclick="window.print()">🖨 打印 / 另存为 PDF</button>
{body}
</body>
</html>"""


@router.get("/api/reports/{session_id}/export.html")
async def export_report_html(session_id: str,
                             token: Optional[str] = None,
                             user: "auth.UserContext" = Depends(get_current_user)):
    """导出复盘报告 HTML（Markdown 渲染 + 打印样式，浏览器打印即得 PDF）

    v7.3: 本端点经 `window.open` 顶层导航打开，浏览器不会携带 Authorization 头
    （与 WebSocket 同类限制）——token 支持 query 参数兜底，安全权衡与
    auth.resolve_ws_user 一致（v7.0 遗漏此路径，认证开启时本页必定 401）。
    """
    if config.AUTH_ENABLED and user.is_anonymous and token:
        user = await auth.user_from_token(token) or user
    if config.AUTH_ENABLED and user.is_anonymous:
        raise HTTPException(status_code=401, detail="需要登录后操作")
    await assert_session_owner(session_id, user)
    try:
        try:
            import markdown as _md
        except ImportError:
            raise HTTPException(500, "缺少 markdown 依赖，请执行 pip install -r requirements.txt")
        report = await get_report(session_id)
        if not report:
            raise HTTPException(404, "报告不存在")
        report = json.loads(report["report_json"]) if isinstance(report.get("report_json"), str) else report
        body = _md.markdown(
            generate_review_markdown(report),
            extensions=["tables", "fenced_code"],
        )
        html = _REPORT_HTML_TEMPLATE.format(title=f"面试复盘报告 · {session_id}", body=body)
        return Response(content=html, media_type="text/html; charset=utf-8")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成复盘 HTML 失败: {e}")
        raise HTTPException(500, str(e))
