"""
分享访问与脱敏（L2）。

职责边界：
- 本模块负责「分享令牌的签发与校验」+「面向外部查看者的 PII 脱敏」。
- 不放进 auth.py，因为 auth.py 管的是访问控制（你是谁），本模块管的是内容处理
  （能给看什么）。虽然都与"谁能看"有关，但一个管身份、一个管内容，
  混在一起会让 auth.py 的职责发散。

分层：L2，只允许依赖 L1（config / db）。

需求文档：docs/week8_报告分享与招聘端只读_需求.md
"""

from __future__ import annotations

import hashlib
import logging
import json as _json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import db
from .config import config
from .dimension_weights import DIM_NAMES

logger = logging.getLogger(__name__)

# 分享范围：目前只支持"只读报告"。留成常量而非裸字符串，
# 便于将来加 scope 时有一个明确的登记处。
SCOPE_REPORT_READ = "report_read"
VALID_SCOPES = (SCOPE_REPORT_READ,)

# 对外统一措辞：把"不存在 / 已撤销 / 已过期"合并成一种表现，
# 避免攻击者用响应差异枚举有效令牌。
_NOT_FOUND_MSG = "分享链接无效或已失效"


class ShareAccessError(Exception):
    """分享访问被拒。message 是对外安全的描述（不泄露资源是否存在）。"""

    def __init__(self, message: str = _NOT_FOUND_MSG, status_code: int = 404):
        super().__init__(message)
        self.status_code = status_code


# ===== 令牌 =====

def generate_token() -> str:
    """生成 URL 安全的随机令牌。

    库里只存摘要（hash_token）：这样即使数据库被读走，攻击者也无法拿摘要去访问
    分享页（摘要不可逆）——把"库泄露"和"分享链接泄露"两个风险解耦。
    """
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    """令牌摘要。

    用 SHA-256 而非 bcrypt：这里是随机高熵串，不存在口令那种"弱输入可枚举"的
    问题，不需要慢哈希（慢哈希会拖慢每一次分享页访问）。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_iso(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    # 兼容无时区的历史数据：按 UTC 解释，避免与 _now() 比较时抛异常
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _expires_at(days: Optional[int]) -> Optional[str]:
    """有效期 → ISO 字符串。

    语义：None / 0 → 永久有效（expires_at 为 NULL）；负数 → 已过期（时间点在过去）。
    负数不是非法输入：它让"过期"这条分支无需等待真实时间流逝就能被测到。
    """
    if days is None or days == 0:
        return None
    return _to_iso(_now() + timedelta(days=days))


# ===== 签发 / 管理 =====

async def create_share_link(session_id: str, created_by: Optional[str] = None,
                            include_detail: bool = False,
                            expires_days: Optional[int] = 30,
                            shared_with: Optional[str] = None,
                            scope: str = SCOPE_REPORT_READ) -> dict:
    """签发一条分享链接。

    返回值里的 `token` 是明文 —— 这是**唯一一次**能拿到明文的机会（库里只存摘要），
    调用方必须当次回给前端。

    shared_with（v7.0.1）：可选，指定收件招聘者的用户名。指定后该报告出现在
    对方的收件箱里；不指定则仍是无主链接（凭链接即可看，不进任何收件箱）。
    """
    if scope not in VALID_SCOPES:
        raise ShareAccessError("不支持的分享范围", 400)

    if shared_with:
        shared_with = shared_with.strip()
        target = await db.get_user_by_username(shared_with)
        # 校验三点：存在 / 是招聘者。错误信息刻意不区分"不存在"与"不是招聘者"
        # ——两者都回同一句，避免用分享接口探测哪些用户名已注册。
        if (not target or target.get("role") != "recruiter"):
            raise ShareAccessError("招聘者用户名不存在", 400)

    token = generate_token()
    row = {
        "token": hash_token(token),
        "session_id": session_id,
        "created_by": created_by,
        "scope": scope,
        "include_detail": 1 if include_detail else 0,
        "shared_with": shared_with or None,
        "expires_at": _expires_at(expires_days),
        "revoked": 0,
        "access_count": 0,
        "last_access_at": None,
        "created_at": _to_iso(_now()),
    }
    await db.save_share_link(row)
    return {**row, "token": token}      # 明文只出现在这一次回执里


# ===== 招聘者收件箱（v7.0.1）=====

async def recruiter_inbox(recruiter_username: str) -> list[dict]:
    """招聘者登录后看到的"收到的报告"列表（摘要层）。

    每条带 token 摘要（token_hash）——不是明文。招聘者打开报告走
    /api/recruiter/reports/{token_hash}（需登录+归属校验），不经过
    免登录的 /api/shared/{token}：收件箱是"登录态下的受控读取"，
    与"凭明文链接的免登录读取"是两条独立通道，互不放大对方的风险面。
    """
    rows = await db.list_inbox_shares(recruiter_username)
    out = []
    for r in rows:
        report_row = await db.get_report(r["session_id"])
        if not report_row:
            continue          # 报告还没生成（理论上分享时已校验，防御脏数据）
        try:
            data = _json.loads(report_row["report_json"]) if isinstance(
                report_row.get("report_json"), str) else (report_row.get("report_json") or {})
        except (ValueError, TypeError):
            continue
        session = await db.get_session(r["session_id"]) or {}
        out.append({
            "token_hash": r["token"],
            "session_id": r["session_id"],
            "shared_at": r.get("created_at"),
            "include_detail": bool(r.get("include_detail")),
            "access_count": r.get("access_count") or 0,
            "overall_score": data.get("overall_avg") or 0,
            "completed_at": report_row.get("created_at") or session.get("updated_at"),
        })
    return out


async def open_inbox_report(token_hash: str, recruiter_username: str) -> dict:
    """招聘者从收件箱打开一份报告（完整脱敏载荷）。

    与 resolve_shared_report 的区别：走登录态+归属校验（shared_with=我），
    不做"过期即拒"——收件箱里的报告是"发给我的"，过期只应限制免登录链接，
    不应把已投递的报告从收件箱里抽走（类比：邮件链接过期了，邮件还在收件箱）。
    """
    row = await db.get_inbox_share(token_hash, recruiter_username)
    if not row:
        raise ShareAccessError()

    try:
        payload = await build_shared_payload(
            row["session_id"], include_detail=bool(row.get("include_detail")))
    except ShareAccessError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"[share] 收件箱报告读取失败 session={row.get('session_id')}: {e}")
        raise ShareAccessError("报告内容不可用")

    payload["token_hash"] = token_hash
    payload["shared_at"] = row.get("created_at")
    payload["access_count"] = row.get("access_count") or 0
    return payload


async def get_share_link(token: str) -> Optional[dict]:
    """按明文令牌查记录（内部转换为摘要后查询）。"""
    if not token:
        return None
    return await db.get_share_link(hash_token(token))


async def list_share_links(session_id: str) -> list[dict]:
    """某会话的分享链接列表 —— 剔除 token 字段，别把凭据吐给前端。"""
    return [dict(r) | {"token": None} for r in await db.list_share_links(session_id)]


def _as_token_hash(token: str) -> str:
    """把"明文或摘要"统一成摘要。

    为什么接受两种输入：列表接口不能吐明文 token（凭据不进列表），但撤销
    又需要定位到具体那一条。撤销只要求"能指向这条链接"——持有明文固然能，
    持有摘要也能（摘要就是库里的主键）。所以这里对两种输入都放行。
    """
    # SHA-256 十六进制摘要固定 64 位，以此区分明文与摘要
    return token if len(token) == 64 else hash_token(token)


async def revoke_share_link(token: str, actor_id: Optional[str]) -> None:
    """撤销。只能撤销自己创建的；认证关闭时 actor_id 为 None，跳过归属校验。"""
    row = await db.get_share_link(_as_token_hash(token))
    if not row:
        raise ShareAccessError()
    if config.AUTH_ENABLED and actor_id and row.get("created_by") != actor_id:
        # 与会话归属同一口径：越权一律表现为"不存在"，不泄露链接存在性
        raise ShareAccessError()
    await db.revoke_share_link(_as_token_hash(token))


# ===== 访问 =====

async def resolve_shared_report(token: str) -> dict:
    """凭令牌取脱敏后的报告；任何不合法情况统一 ShareAccessError(404)。"""
    row = await get_share_link(token)
    if not row or row.get("revoked"):
        raise ShareAccessError()

    expires = _parse_iso(row.get("expires_at"))
    if expires and _now() > expires:
        raise ShareAccessError()

    try:
        payload = await build_shared_payload(
            row["session_id"], include_detail=bool(row.get("include_detail")))
    except ShareAccessError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"[share] 构建分享报告失败 session={row.get('session_id')}: {e}")
        raise ShareAccessError("报告内容不可用")

    # 访问计数是附加价值，不是读取前提：写失败不影响本次访问
    try:
        await db.touch_share_link(hash_token(token))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[share] 访问计数写入失败: {e}")

    payload["shared_at"] = _to_iso(_now())
    payload["expires_at"] = row.get("expires_at")
    payload["scope"] = row.get("scope")
    payload["access_count"] = (row.get("access_count") or 0) + 1
    return payload


async def build_shared_payload(session_id: str, include_detail: bool = False) -> dict:
    """构造对外可见的报告载荷。

    默认（include_detail=False）只给"结论层"：总分、五维均分、各轮概况、强项弱项。
    完整问答默认不给 —— 逐字答案是夹带手机号/薪资/内部项目名风险最高的部分，
    且候选人通常只想证明"我练过、水平如何"，而不是把每句话公开。
    """
    # db.get_report 返回的是**数据库行**（report_json 为 JSON 文本），不是报告对象本身。
    report_row = await db.get_report(session_id)
    if not report_row:
        raise ShareAccessError()

    raw = report_row.get("report_json")
    if isinstance(raw, str):
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError):
            raise ShareAccessError("报告内容不可用")
    else:
        data = raw or {}

    session = await db.get_session(session_id) or {}

    payload = {
        "session_id": session_id,
        "completed_at": report_row.get("created_at") or session.get("updated_at"),
        "overall_score": data.get("overall_avg") or 0,
        "dimensions": _dimension_block(data.get("dimension_averages") or {}),
        "rounds": _round_outline(data.get("rounds") or []),
        "strengths": [redact_pii(str(x)) for x in (data.get("strengths") or [])],
        "weaknesses": [redact_pii(str(x)) for x in (data.get("weaknesses") or [])],
        "suggestions": redact_pii(str(data.get("suggestions") or ""))[:2000],
        # 一律用匿名称谓，不显示真实姓名：分享页的读者是外部 HR，
        # "看到分数"和"看到是谁"是两回事，后者没必要给。
        "candidate_name": "候选人",
        "include_detail": include_detail,
        "disclaimer": "本报告为 AI 模拟诊断结果，由候选人主动分享，不构成录用建议。",
    }

    if include_detail:
        payload["qa_details"] = _qa_details(data.get("qa_breakdown") or [])

    return payload


def _dimension_block(dim_avgs: dict) -> list[dict]:
    """维度 → 对外结构（中文名 + 分数），不暴露内部 key。"""
    return [
        {"key": k, "label": DIM_NAMES.get(k, k), "score": v}
        for k, v in (dim_avgs or {}).items()
    ]


def _round_outline(rounds) -> list[dict]:
    """轮次概况：名称/题数/均分，不夹带具体问答。"""
    out = []
    for r in rounds if isinstance(rounds, list) else []:
        if not isinstance(r, dict):
            continue
        out.append({
            "name": redact_pii(str(r.get("round_name") or r.get("name") or "")),
            "questions_count": r.get("questions_count"),
            "answers_count": r.get("answers_count"),
            "avg_score": r.get("avg_score"),
        })
    return out


def _qa_details(qa_breakdown) -> list[dict]:
    """逐题明细（仅在 include_detail 时给出）。

    只输出"场面信息 + 结论"，不输出改后答案（rewritten_answer）—— 那是我们给
    候选人的学习材料，不是给外部审阅者的内容。
    """
    out = []
    for q in qa_breakdown if isinstance(qa_breakdown, list) else []:
        if not isinstance(q, dict):
            continue
        out.append({
            "index": q.get("index"),
            "round_name": redact_pii(str(q.get("round_name") or "")),
            "question": redact_pii(str(q.get("question") or "")),
            "score": q.get("overall_score"),
            "overall_comment": redact_pii(str(q.get("overall_comment") or "")),
            "weakest_dimension_name": q.get("weakest_dimension_name") or "",
            "risk_points": [redact_pii(str(x)) for x in (q.get("risk_points") or [])],
            "real_interview_impact": redact_pii(str(q.get("real_interview_impact") or "")),
            "assisted": bool(q.get("assisted")),   # 诚实标注：这题是否借助引导完成
            # v7.0.2: 追问回避 —— 面试官追问过但候选人跳过，分享给招聘者时同样如实披露
            "follow_up_skipped": bool(q.get("follow_up_skipped")),
        })
    return out


# ===== PII 脱敏 =====

def redact_pii(text: Optional[str]) -> str:
    """脱敏面向外部查看者的文本。

    为什么在**输出侧**脱敏而不是入库时脱敏：原始回答要保留给候选人自己复盘，
    脱敏是不可逆的，只能在给外人看的那一刻做。
    """
    if not text:
        return ""
    s = str(text)
    # 顺序有讲究：长身份证要在短数字串之前处理，否则会被手机号规则先吃掉前 11 位
    s = re.sub(r"\b\d{17}[\dXx]\b", "[身份证已脱敏]", s)
    s = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已脱敏]", s)
    s = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[邮箱已脱敏]", s)
    # QQ / 微信号一类：显式标注前缀的长数字串
    s = re.sub(r"(?i)(qq|wechat|微信|weixin)\s*[:：]?\s*\d{5,}", r"\1[账号已脱敏]", s)
    return s
