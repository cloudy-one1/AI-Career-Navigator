"""
求职档案（Job-Seeking Profile）聚合服务（v8.0，L3 业务逻辑）。

产品定位：档案是整个「求职陪跑」闭环的领域核心。三个能力模块从"并列功能"
降级为"档案的读写者"：
    市场数据 → 写入「目标岗位」（目标岗位 + 市场基准）
    模拟面试 → 写入「能力水平」（五维能力信号）
    职业规划 → 消费「待提升项」（长期薄弱点作为路径起点）

v8.1 术语纪律：对外的四段状态名为 当前简历 / 目标岗位 / 能力水平 / 待提升项，
禁用"我是谁""我还差什么""加练"一类口语化与游戏化表达。

四组状态：
    我是谁 identity  → 简历解析出的技能 / 亮点
    我要去哪 target  → 目标岗位 + 该岗位的市场基准（薪资带 / 热门技能）
    我现在什么水平 level → 五维能力分 + 相对上一场的变化
    待提升项 gaps     → 长期薄弱点（EMA）+ 未达标的维度，排序后的行动项

设计决策（为什么不照抄常见做法）：
1. **档案是"投影"而非"新真相源"**：不新增宽表冗余存储画像，每次请求从
   resumes / positions / sessions / reports / weakness_memory / market.db 聚合。
   理由：画像的每一段都已有权威数据源，再存一份必然腐化（双写一致性问题）。
   代价：聚合有 IO 成本 → 用 60 秒进程内 TTL 缓存抵消（切 tab 是主要调用场景）。
2. **跨库只能在服务层聚合**：interview.db 与 market.db 是两个独立库，SQLite
   无法跨库 JOIN。市场基准在此查询后于内存拼接（与 gap_analyzer 既有做法一致）。
3. **降级优先于报错**：任一数据源缺失/异常只把该段降级为空并记录 warning，
   整接口绝不 500——档案是首屏，宁可少一段数据也不能白屏。
4. **NBA 用规则表而非 LLM**：确定性、零延迟、可单测、可解释（能告诉用户
   "为什么是这一步"）。LLM 只用在它擅长的规划生成上。

已知局限（P0 阶段，需登记进 CHARTER.md）：
- weakness_memory 以 dimension 为主键、**全局无 owner 维度**（v6.3 早于 v7.0
  认证），故「待提升项」本阶段沿用其全局性；P2 再按 _ensure_owner_columns
  的 PRAGMA+ALTER 范式补 owner_id。

分层：L3（只依赖 L1 的 db 与 L2 的 weakness_memory / market.store；
已在 .importlinter 的 L3 层登记）。
"""

import asyncio
import json
import logging
import time
from datetime import datetime

from . import weakness_memory
from .db import (
    get_position,
    get_resume,
    list_journey_marks,
    list_positions,
    list_recent_reports,
    list_resumes,
    list_sessions,
)
from .dimension_weights import DIM_KEYS, DIM_NAMES
from .market import store as market_store

logger = logging.getLogger(__name__)

# ===== 阈值与口径 =====

CACHE_TTL_SECONDS = 60        # 档案缓存时长（切 tab 高频调用，避免重复聚合）
SESSION_SCAN_LIMIT = 20       # 最多扫描多少场会话（取场次总数与最近时间）
MAX_HISTORY_POINTS = 10       # 成长曲线最多取多少个点（一次 JOIN 取回，非 N+1）
TARGET_DIM_SCORE = 4.0        # 五维目标线（1-5 制）：低于此值记为差距
ACTIVE_WEAKNESS_MIN = 30.0    # 长期薄弱度（0-100）超过此值才算"活跃短板"
MAX_GAPS = 5                  # 差距清单最多展示条数（首屏信息密度取舍）

# 缓存：owner_id → (写入时刻 monotonic, 档案 dict)
_cache: dict[str, tuple[float, dict]] = {}


# ===== 通用小工具 =====

def _cache_key(owner_id: str | None) -> str:
    return owner_id or "__anon__"


def invalidate_profile_cache(owner_id: str | None = None) -> None:
    """档案变更后清缓存。owner_id 为空则全清（如退出登录）。"""
    if owner_id is None:
        _cache.clear()
        return
    _cache.pop(_cache_key(owner_id), None)


def _load_json(raw, default):
    """解析 JSON 字符串，失败返回默认值（老库/脏数据不得让整段崩掉）。"""
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _first_list(parsed: dict, keys: tuple[str, ...], limit: int) -> list[str]:
    """从解析结果里按候选键名取字符串列表（简历解析器字段口径历史上变过多次）。"""
    for key in keys:
        v = parsed.get(key)
        if isinstance(v, list) and v:
            return [str(x).strip() for x in v if str(x).strip()][:limit]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
    return []


def _normalize_skills(raw, limit: int = 8) -> list[str]:
    """市场 top_skills 的口径不确定（可能是 dict 列表 / 字符串列表 / 元组），统一成字符串。"""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            val = item.get("skill") or item.get("name") or item.get("tag")
            if not val:
                # 只有一个键值对时取它的值
                val = next(iter(item.values()), None) if len(item) == 1 else None
        else:
            val = item
        if val:
            out.append(str(val))
        if len(out) >= limit:
            break
    return out


# ===== 段一：我是谁 =====

async def _load_identity(owner_id: str | None) -> dict:
    """简历画像。list_resumes 不含 parsed_json（列清单刻意排除了大字段），
    故先取列表拿最新一份，再按 id 单独取解析结果。"""
    resumes = await list_resumes(owner_id=owner_id, limit=1)
    if not resumes:
        return {"has_resume": False, "skills": [], "highlights": []}

    latest = resumes[0]
    identity = {
        "has_resume": True,
        "resume_id": latest.get("id", ""),
        "title": latest.get("title", ""),
        "char_count": latest.get("char_count", 0),
        "updated_at": latest.get("updated_at", ""),
        "skills": [],
        "highlights": [],
    }
    try:
        row = await get_resume(latest.get("id", ""))
        parsed = _load_json((row or {}).get("parsed_json"), {})
        if isinstance(parsed, dict):
            identity["skills"] = _first_list(
                parsed, ("skills", "skill_tags", "tech_skills", "abilities"), 12)
            identity["highlights"] = _first_list(
                parsed, ("highlights", "experience_highlights", "strengths", "summary"), 3)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 简历解析结果读取失败，降级为空画像: {e}")
    return identity


# ===== 段二：我要去哪 =====

async def _match_keyword(position_title: str) -> str | None:
    """用目标岗位标题反查已采集的市场关键词。

    口径：完整命中优先；其次子串命中取最长（避免"Java"命中"JavaScript"这类
    短词抢占）。命中不到返回 None——没有采集数据时不应硬凑一个基准。
    """
    try:
        keywords = await market_store.list_keywords()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 市场关键词读取失败，跳过市场基准: {e}")
        return None

    title = (position_title or "").strip().lower()
    if not title or not keywords:
        return None
    exact = [k for k in keywords if (k or "").strip().lower() == title]
    if exact:
        return exact[0]
    hits = [k for k in keywords if k and k.lower() in title]
    return max(hits, key=len) if hits else None


async def _load_target(owner_id: str | None) -> dict:
    """目标岗位 + 市场基准（两个库，服务层拼接）。"""
    positions = await list_positions(owner_id=owner_id, limit=1)
    if not positions:
        return {"has_target": False, "market": {}}

    latest = positions[0]
    target = {
        "has_target": True,
        "position_id": latest.get("id", ""),
        "title": latest.get("title", ""),
        "department": latest.get("department", ""),
        "updated_at": latest.get("updated_at", ""),
        "jd_excerpt": "",
        "market": {},
    }
    try:
        row = await get_position(latest.get("id", ""))
        jd = (row or {}).get("jd_text") or ""
        if jd:
            target["jd_excerpt"] = jd[:200]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 岗位 JD 读取失败，降级为空: {e}")

    try:
        kw = await _match_keyword(target["title"])
        if kw:
            stats = await market_store.get_stats(keyword=kw)
            cities = []
            for c in (stats.get("cities") or []):
                name = (c.get("city") or c.get("name")) if isinstance(c, dict) else c
                if name:
                    cities.append(str(name))
                if len(cities) >= 3:
                    break
            target["market"] = {
                "keyword": kw,
                "sample_size": int(stats.get("total") or 0),
                "avg_salary": stats.get("avg_salary"),
                "top_skills": _normalize_skills(stats.get("top_skills")),
                "cities": cities,
            }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 市场基准聚合失败，降级为空: {e}")

    return target


# ===== 段三：我现在什么水平 =====

def _dim_scores(report: dict) -> dict:
    """从报告里取五维均分；缺维度返回空（不补默认分，避免"没测过"被当成"中等"）。"""
    avgs = report.get("dimension_averages") or {}
    out = {}
    for k in DIM_KEYS:
        v = avgs.get(k)
        if isinstance(v, (int, float)):
            out[k] = round(float(v), 2)
    return out


def _report_weights(report: dict) -> dict:
    scoring = report.get("scoring") or {}
    weights = scoring.get("weights") or {}
    return {k: float(weights.get(k, 0.20)) for k in DIM_KEYS}


async def _load_level(owner_id: str | None) -> dict:
    """五维能力 + 环比变化 + 成长曲线。

    取数策略：会话数仍走 list_sessions（要总量与最近时间），报告序列走
    list_recent_reports **一次 JOIN**——成长曲线要的是 N 场历史，逐份
    get_report 会退化成 N 次 IO。
    """
    sessions = await list_sessions(limit=SESSION_SCAN_LIMIT, owner_id=owner_id)
    if not sessions:
        return {
            "has_history": False, "session_count": 0, "report_count": 0,
            "overall": None, "dimensions": [], "delta": {}, "history": [],
            "last_session_at": "",
        }

    # 报告按时间倒序（最新在前）
    reports: list[dict] = []
    stamps: list[str] = []
    for row in await list_recent_reports(owner_id=owner_id, limit=MAX_HISTORY_POINTS):
        rep = _load_json(row.get("report_json"), None)
        if isinstance(rep, dict) and rep:
            reports.append(rep)
            stamps.append(row.get("created_at") or "")

    if not reports:
        return {
            "has_history": False, "session_count": len(sessions), "report_count": 0,
            "overall": None, "dimensions": [], "delta": {}, "history": [],
            "last_session_at": sessions[0].get("updated_at", ""),
        }

    latest_scores = _dim_scores(reports[0])
    prev_scores = _dim_scores(reports[1]) if len(reports) > 1 else {}
    weights = _report_weights(reports[0])

    # 当前水平：取最近两份报告的均值（有两份时），降低单场波动带来的误判
    sample = [latest_scores] + ([prev_scores] if prev_scores else [])
    dimensions = []
    for k in DIM_KEYS:
        vals = [d[k] for d in sample if k in d]
        if not vals:
            continue
        cur = round(sum(vals) / len(vals), 2)
        delta = None
        if k in latest_scores and k in prev_scores:
            delta = round(latest_scores[k] - prev_scores[k], 2)
        dimensions.append({
            "key": k,
            "name": DIM_NAMES.get(k, k),
            "score": cur,
            "weight": round(weights.get(k, 0.20), 3),
            "delta": delta,
        })

    overall_vals = [d["score"] for d in dimensions]

    # 成长曲线：按时间正序（旧 → 新），只收有综合分的场次
    history = []
    for rep, at in zip(reversed(reports), reversed(stamps)):
        overall = rep.get("overall_avg")
        try:
            overall = round(float(overall), 2)
        except (TypeError, ValueError):
            continue
        history.append({"at": at, "overall": overall, "dims": _dim_scores(rep)})

    return {
        "has_history": True,
        "session_count": len(sessions),
        "report_count": len(reports),
        "overall": round(sum(overall_vals) / len(overall_vals), 2) if overall_vals else None,
        "dimensions": dimensions,
        "delta": {d["key"]: d["delta"] for d in dimensions if d["delta"] is not None},
        "history": history,
        "last_session_at": sessions[0].get("updated_at", ""),
    }


# ===== 段四：待提升项 =====

def _build_gaps(level: dict, memory_points: list[dict]) -> list[dict]:
    """差距清单：长期薄弱点优先（有 EMA 累积证据），再补未达标的维度。

    纯函数，不碰 IO——便于单测覆盖排序口径。
    """
    score_map = {d["key"]: d["score"] for d in (level.get("dimensions") or [])}
    gaps: list[dict] = []
    claimed: set[str] = set()

    for p in memory_points or []:
        dim = p.get("dimension", "")
        if not dim:
            continue
        try:
            severity = float(p.get("weakness_score") or 0)
        except (TypeError, ValueError):
            severity = 0.0
        if severity < ACTIVE_WEAKNESS_MIN:
            continue
        claimed.add(dim)
        gaps.append({
            "dimension": dim,
            "name": DIM_NAMES.get(dim, dim),
            "kind": "weakness",
            "current": score_map.get(dim),
            "target": TARGET_DIM_SCORE,
            "severity": round(severity, 1),
            "occurrence": int(p.get("occurrence_count") or 0),
            "evidence": [str(x) for x in (p.get("risk_points") or [])][:2],
            "action_tab": "interview",
        })

    # 补位：五维低于目标线但尚未进入长期记忆的（"一次失手"也该提示，只是排后面）
    for d in level.get("dimensions") or []:
        if d["key"] in claimed or d.get("score") is None:
            continue
        if d["score"] >= TARGET_DIM_SCORE:
            continue
        gaps.append({
            "dimension": d["key"],
            "name": d.get("name", DIM_NAMES.get(d["key"], d["key"])),
            "kind": "dimension",
            "current": d["score"],
            "target": TARGET_DIM_SCORE,
            "severity": round((TARGET_DIM_SCORE - d["score"]) / 4 * 100, 1),
            "occurrence": 1,
            "evidence": [],
            "action_tab": "interview",
        })

    gaps.sort(key=lambda g: (-g["severity"], -g["occurrence"]))
    return gaps[:MAX_GAPS]


# ===== 段六：技能缺口（简历 vs 市场）=====

def compute_skill_gap(resume_skills: list[str], market_skills: list[str],
                      limit: int = 6) -> dict:
    """简历技能与市场热门技能的集合运算（纯函数：不碰 IO、不调 LLM）。

    为什么用集合运算而不是 LLM：这是确定性事实判断——有没有这个技能是
    客观事实，不该由模型"猜"。零成本、可解释、结果稳定，LLM 只用在它
    擅长的规划生成上。

    匹配口径：忽略大小写的精确匹配优先；未命中再做子串包含。市场侧技能名
    口径很脏（"Python" vs "python3"、"Redis 缓存"），只做精确匹配会把大量
    真实匹配误判成缺口。子串匹配要求词长 ≥2，否则 "C" 会命中 "C++"。
    """
    resume = [str(s).strip() for s in (resume_skills or []) if str(s).strip()]
    market = [str(s).strip() for s in (market_skills or []) if str(s).strip()]
    if not resume or not market:
        return {"matched": [], "missing": [], "market_total": len(market)}

    lower_resume = [s.lower() for s in resume]
    matched: list[str] = []
    missing: list[str] = []
    for skill in market:
        ls = skill.lower()
        hit = ls in lower_resume or any(
            (r in ls) or (ls in r) for r in lower_resume if len(r) >= 2
        )
        (matched if hit else missing).append(skill)

    return {
        "matched": matched[:limit],
        "missing": missing[:limit],
        "market_total": len(market),
    }


async def build_skill_gap_context(owner_id: str | None = None, limit: int = 4) -> str:
    """给职业规划用的技能缺口上下文（纯文本块）。

    与 build_weakness_context 的分工：那边说"你面试表达上弱在哪"，
    这边说"你的技能离目标岗位的市场要求还差什么"——前者是能力维度，
    后者是硬技能，规划的第一阶段两样都要看。
    无数据时返回空串，调用方据此跳过注入。
    """
    try:
        profile = await get_profile(owner_id=owner_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 规划上下文：技能缺口读取失败，跳过注入: {e}")
        return ""

    gap = ((profile.get("target") or {}).get("skill_gap") or {})
    missing = gap.get("missing") or []
    matched = gap.get("matched") or []
    if not missing and not matched:
        return ""

    lines = []
    if matched:
        lines.append(f"简历已具备的市场热门技能：{'、'.join(str(x) for x in matched[:limit])}")
    if missing:
        lines.append(
            f"目标岗位市场热门、但简历中未体现的技能（按市场热度排序）："
            f"{'、'.join(str(x) for x in missing[:limit])}"
        )
        lines.append("要求：第一阶段优先补足上述技能缺口，并给出可验证的补齐方式。")
    return "\n".join(lines)


# ===== 段五：五步主线完成度 =====

# 五步主线的 key 与 navConfig.js 的 JOURNEY_STEPS 顺序严格对应。
# 前三步由档案实时推导，只有 career_path 必须打点（档案里没有"是否规划过"的痕迹）。
JOURNEY_KEYS = ("positioning", "resume", "practice", "diagnosis", "career_path")
JOURNEY_STEP_KEY_NEEDS_MARK = "career_path"


def derive_journey(identity: dict, target: dict, level: dict,
                   marks: dict | None = None) -> dict:
    """推导五步主线的完成度（纯函数，不碰 IO —— 便于单测覆盖判定口径）。

    判定口径：
        职业定位 = 已选定目标岗位
        简历准备 = 已上传简历
        面试演练 = 已开过至少一场（session_count > 0）
        能力诊断 = 已产出至少一份报告（report_count > 0）
        发展路径 = 已生成过规划（**唯一无法推导的一步**，靠 journey_marks 打点）

    状态：done（已完成）/ current（第一个未完成的步骤）/ todo（未开始）。
    current 至多一个——它同时是"下一步该走到哪"的视觉答案。
    """
    marks = marks or {}
    checks = {
        "positioning": bool((target or {}).get("has_target")),
        "resume": bool((identity or {}).get("has_resume")),
        "practice": int((level or {}).get("session_count") or 0) > 0,
        "diagnosis": int((level or {}).get("report_count") or 0) > 0,
        "career_path": JOURNEY_STEP_KEY_NEEDS_MARK in marks,
    }

    steps = []
    current_assigned = False
    for key in JOURNEY_KEYS:
        done = checks.get(key, False)
        state = "done" if done else ("todo" if current_assigned else "current")
        if state == "current":
            current_assigned = True
        steps.append({"key": key, "state": state})

    completed = sum(1 for s in steps if s["state"] == "done")
    return {
        "steps": steps,
        "completed": completed,
        "total": len(JOURNEY_KEYS),
        # 全部完成时没有"下一步"，显式给出 None 而非让前端猜
        "current_key": None if completed == len(JOURNEY_KEYS) else
                       next((s["key"] for s in steps if s["state"] == "current"), None),
    }


# ===== 下一步建议 =====

def next_best_action(profile: dict) -> dict | None:
    """规则决策表（纯函数：不调 LLM、不碰 IO、可单测）。

    判定顺序即产品优先级：先有简历，再定目标，再测能力水平，
    然后才是"补短板 / 排路径"。返回的 target_tab 与前端 navConfig 的 tab 名一致。

    v8.1 文案纪律：一律使用职业发展领域的本行术语，禁用"加练""开一场"
    "打怪"一类游戏化表达——产品的可信度来自专业感，不是亲切感。
    """
    identity = profile.get("identity") or {}
    target = profile.get("target") or {}
    level = profile.get("level") or {}
    gaps = profile.get("gaps") or []

    if not identity.get("has_resume"):
        return {
            "action": "上传一份简历，建立档案基线",
            "target_tab": "resume-library",
            "reason": "档案中还没有简历信息，岗位匹配与面试追问均以它为输入。",
            "urgency": "high",
            "dimension": "",
        }

    if not target.get("has_target"):
        return {
            "action": "先选定一个目标岗位",
            "target_tab": "position-library",
            "reason": "尚未设定目标岗位，无法计算能力差距。",
            "urgency": "high",
            "dimension": "",
        }

    if not level.get("has_history"):
        title = target.get("title", "目标岗位")
        return {
            "action": "完成第一场模拟面试，建立能力基线",
            "target_tab": "interview",
            "reason": f"目标岗位已定为「{title}」，但尚无能力数据可供对比。",
            "urgency": "high",
            "dimension": "",
        }

    active = [g for g in gaps if g.get("kind") == "weakness"]
    if active:
        top = active[0]
        occ = int(top.get("occurrence") or 0)
        reason = (f"该维度薄弱度 {top['severity']}，已连续 {occ} 次未达标。"
                  if occ > 1 else f"该维度薄弱度 {top['severity']}，本轮首次暴露。")
        return {
            "action": f"针对「{top['name']}」做一次专项演练",
            "target_tab": "interview",
            "reason": reason,
            "urgency": "high",
            "dimension": top.get("dimension", ""),
        }

    if int(level.get("session_count") or 0) >= 3:
        return {
            "action": "生成发展路径",
            "target_tab": "career-plan",
            "reason": "待提升项已收敛，可基于当前能力水平规划长期路径。",
            "urgency": "normal",
            "dimension": "",
        }

    return {
        "action": "查看最近一次诊断报告",
        "target_tab": "report",
        "reason": "暂无突出短板，建议复盘最近一场的逐题分析再定下一步。",
        "urgency": "low",
        "dimension": "",
    }


# ===== 聚合入口 =====

async def get_profile(owner_id: str | None = None, use_cache: bool = True) -> dict:
    """聚合四组状态 + NBA。任一段失败只降级该段，整接口不 500。"""
    key = _cache_key(owner_id)
    if use_cache:
        hit = _cache.get(key)
        if hit and (time.monotonic() - hit[0]) < CACHE_TTL_SECONDS:
            return hit[1]

    degraded: list[str] = []

    # 三段并行聚合；整段崩溃也必须只降级自身（return_exceptions 是降级纪律的一部分）
    results = await asyncio.gather(
        _load_identity(owner_id),
        _load_target(owner_id),
        _load_level(owner_id),
        return_exceptions=True,
    )
    seg_names = ("identity", "target", "level")
    empties = (
        {"has_resume": False, "skills": [], "highlights": []},
        {"has_target": False, "market": {}},
        {"has_history": False, "session_count": 0, "report_count": 0,
         "overall": None, "dimensions": [], "delta": {}, "history": [],
         "last_session_at": ""},
    )
    values = []
    for name, res, empty in zip(seg_names, results, empties):
        if isinstance(res, BaseException):
            logger.warning(f"[档案] {name} 聚合失败，降级为空: {res}")
            degraded.append(name)
            values.append(empty)
        else:
            values.append(res)
    identity, target, level = values

    try:
        memory_points = await weakness_memory.active_memory_points(limit=MAX_GAPS)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 长期薄弱点读取失败，差距清单降级: {e}")
        memory_points = []
        degraded.append("gaps")

    # v8.1: 五步主线完成度。打点读取失败只让 career_path 回落到未完成，
    # 其余四步仍由档案推导——不把整段降级（它本来就是推导出来的）。
    try:
        marks = await list_journey_marks(owner_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 旅程打点读取失败，发展路径步骤降级为未完成: {e}")
        marks = {}

    # v8.1: 技能缺口（简历 vs 市场热门技能）——跨段计算，故放在聚合层而非 _load_* 内。
    # 任一段缺失都只是"算不出缺口"，不降级、不影响其它段。
    skill_gap = compute_skill_gap(
        (identity or {}).get("skills") or [],
        ((target or {}).get("market") or {}).get("top_skills") or [],
    )
    if isinstance(target, dict):
        target["skill_gap"] = skill_gap

    gaps = _build_gaps(level, memory_points)
    profile = {
        "identity": identity,
        "target": target,
        "level": level,
        "gaps": gaps,
        "journey": derive_journey(identity, target, level, marks),
        "next_action": None,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "degraded": degraded,
    }
    profile["next_action"] = next_best_action(profile)

    _cache[key] = (time.monotonic(), profile)
    return profile


async def build_weakness_context(owner_id: str | None = None, limit: int = 3) -> str:
    """给职业规划用的薄弱点上下文（纯文本块）。

    这是 P0 闭环的关键拼图：让规划器第一次知道"用户练过什么、弱在哪里"。
    无数据时返回空串——调用方据此跳过注入，保持既有行为不变。
    """
    try:
        points = await weakness_memory.active_memory_points(limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[档案] 规划上下文：长期薄弱点读取失败，跳过注入: {e}")
        return ""
    if not points:
        return ""

    lines = []
    for p in points:
        dim = p.get("dimension", "")
        name = DIM_NAMES.get(dim, dim)
        score = p.get("weakness_score", 0)
        occ = int(p.get("occurrence_count") or 0)
        risks = "；".join(str(x) for x in (p.get("risk_points") or [])[:2])
        seg = f"- {name}：长期薄弱度 {score}（累计 {occ} 次未达标）"
        if risks:
            seg += f"，近期风险点：{risks}"
        lines.append(seg)
    return "\n".join(lines)
