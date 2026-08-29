"""
公司风格配置层（v6.5，借鉴 interviewerAgent 的 companies/*.yaml 热加载）。

对标来源：chenyongzhi1119/interviewerAgent 的 `loadCompanies`（扫目录读 YAML，加文件即加公司、
零改码）与 `CompanyProfile`（role_description 人格层 + rounds[].instructions 轮次行为层 +
evaluation_rubric 评估量表，字段结构仅 15 行）。

与原版的差异（为什么不照抄）：
  - 原版轮次按键 1/2/3 索引（它只有"一面/二面/三面"一种结构）；本项目有拟真 6 阶段与
    传统 5 轮两种模式，轮次名不同，因此改为**按轮次名关键词匹配**，两种模式同时兼容；
  - 原版要求"有 JD 才能开面"，公司风格无自动匹配；本项目增加 match_keywords，创建会话
    时可按 JD 关键词自动选定；
  - 原版公司评估量表只进对话式点评；本项目量表进结构化报告（company_rubric）。

分层：L2 领域数据（禁 import L3/L4）。容错哲学与 v6.2 简历追问点提取一致——
pyyaml 缺失 / 目录不存在 / 单文件解析失败时降级为空注册表并告警，**不阻断面试主流程**。
"""

import logging
import os

logger = logging.getLogger(__name__)

# 配置目录：backend/company_profiles/*.yaml
PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_profiles")


def _load_yaml(text: str) -> tuple[dict | None, str | None]:
    """安全加载 YAML。返回 (data, error)；error="no_yaml" 表示 pyyaml 缺失（全局降级），
    其它 error 表示该文件不可解析（跳过单文件）。"""
    try:
        import yaml  # noqa: PLC0415  # 延迟导入：pyyaml 缺失时其余功能不受影响
    except ImportError:
        return None, "no_yaml"
    try:
        return yaml.safe_load(text), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _normalize_profile(data: dict, source: str) -> dict | None:
    """校验并规整单份公司配置；不合法的文件跳过（返回 None），不影响其它文件。"""
    if not isinstance(data, dict):
        logger.warning(f"公司配置 {source} 顶层不是对象，已跳过")
        return None
    name = str(data.get("name") or "").strip()
    display_name = str(data.get("display_name") or "").strip()
    role_description = str(data.get("role_description") or "").strip()
    rubric = str(data.get("evaluation_rubric") or "").strip()
    if not name or not display_name:
        logger.warning(f"公司配置 {source} 缺少 name/display_name，已跳过")
        return None
    # 完全没有内容性字段（人格/轮次指令/量表全空）的配置没有注入价值
    rounds_raw = data.get("rounds") or []
    if not isinstance(rounds_raw, list):
        rounds_raw = []
    rounds = []
    for entry in rounds_raw:
        if not isinstance(entry, dict):
            continue
        match = entry.get("match")
        if isinstance(match, str):
            match = [match]
        if not isinstance(match, list):
            match = []
        match = [str(m).strip() for m in match if str(m).strip()]
        instructions = str(entry.get("instructions") or "").strip()
        if instructions:
            rounds.append({"match": match, "instructions": instructions})
    keywords = data.get("match_keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    # 展示名本身也是匹配关键词（JD 里写"字节跳动"应命中）
    for dn in (display_name, name):
        if dn and dn not in keywords:
            keywords.append(dn)

    if not role_description and not rounds and not rubric:
        logger.warning(f"公司配置 {source} 无任何注入内容，已跳过")
        return None
    return {
        "name": name,
        "display_name": display_name,
        "match_keywords": keywords,
        "role_description": role_description,
        "rounds": rounds,
        "evaluation_rubric": rubric,
        # 轮次指令是否命中过（会话运行期填充，避免重复判断）
        "_source_file": os.path.basename(source),
    }


def load_profiles(directory: str | None = None) -> dict[str, dict]:
    """扫描目录加载全部公司配置；任何失败都降级（空注册表 / 跳过单文件）。

    directory 默认取模块常量 PROFILES_DIR（运行时读取而非默认参数绑定，
    便于测试热替换目录）。
    """
    directory = directory or PROFILES_DIR
    profiles: dict[str, dict] = {}
    if not os.path.isdir(directory):
        logger.info(f"公司配置目录不存在（{directory}），公司风格层未启用")
        return profiles
    try:
        entries = sorted(os.listdir(directory))
    except OSError as e:
        logger.warning(f"公司配置目录读取失败: {e}")
        return profiles
    for fname in entries:
        if not fname.lower().endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, fname)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            logger.warning(f"公司配置 {fname} 读取失败: {e}")
            continue
        data, err = _load_yaml(text)
        if err == "no_yaml":
            logger.warning("pyyaml 未安装，公司风格层整体降级（pip install pyyaml 启用）")
            return profiles
        if err is not None:
            logger.warning(f"公司配置 {fname} 解析失败，已跳过: {err}")
            continue
        if not isinstance(data, dict):
            # 空/注释文件 → safe_load 返回 None，跳过该文件即可
            continue
        profile = _normalize_profile(data, fname)
        if profile is None:
            continue
        if profile["name"] in profiles:
            logger.warning(f"公司配置重名（{profile['name']}），后者覆盖：{fname}")
        profiles[profile["name"]] = profile
    if profiles:
        logger.info(f"公司风格层已加载 {len(profiles)} 份配置: {', '.join(profiles)}")
    return profiles


# 模块级注册表：import 时加载一次；YAML 增删后调用 reload() 热更新
_PROFILES: dict[str, dict] = load_profiles()


def reload() -> dict[str, dict]:
    """热重载公司配置（运维/测试用）。"""
    global _PROFILES
    _PROFILES = load_profiles()
    return _PROFILES


def list_profiles() -> list[dict]:
    """全部公司配置摘要（供前端选择器 / GET /api/company-profiles）。"""
    return [
        {
            "name": p["name"],
            "display_name": p["display_name"],
            "match_keywords": p["match_keywords"],
            "has_role_description": bool(p["role_description"]),
            "round_rules": len(p["rounds"]),
            "has_rubric": bool(p["evaluation_rubric"]),
        }
        for p in _PROFILES.values()
    ]


def get_profile(name: str | None) -> dict | None:
    """按 name 取配置；未知/空返回 None（调用方降级为不注入）。"""
    if not name:
        return None
    return _PROFILES.get(str(name).strip())


def match_profile(jd_text: str | None) -> dict | None:
    """按 JD 文本关键词命中数自动匹配公司配置；0 命中返回 None。

    打分：命中数最高者胜出，平手取注册顺序首个（加载顺序稳定，结果可复现）。
    """
    if not jd_text or not _PROFILES:
        return None
    jd = str(jd_text)
    best: tuple[int, dict] | None = None
    for p in _PROFILES.values():
        hits = sum(1 for kw in p["match_keywords"] if kw and kw in jd)
        if hits <= 0:
            continue
        if best is None or hits > best[0]:
            best = (hits, p)
    if best:
        logger.info(f"公司风格按 JD 自动匹配: {best[1]['display_name']}（命中 {best[0]} 个关键词）")
    return best[1] if best else None


def company_role_block(profile: dict | None) -> str:
    """公司人格层 prompt 片段（整场注入，置于角色卡最前 —— 公司是外层人格，风格卡是内层语气）。"""
    if not profile:
        return ""
    desc = str(profile.get("role_description") or "").strip()
    display = str(profile.get("display_name") or "").strip()
    if not desc:
        return ""
    return f"【目标公司面试风格 · {display}】\n{desc}"


def company_round_block(profile: dict | None, round_name: str) -> str:
    """本轮的公司轮次指令片段：轮次名命中任一 match 关键词即注入。

    轮次名取自 config.INTERVIEW_ROUNDS / TRADITIONAL_ROUNDS 的 name 字段
    （如"技术广度"、"技术一面"、"项目拷问"），关键词命中为子串匹配。
    """
    if not profile:
        return ""
    rname = str(round_name or "")
    parts = [
        entry["instructions"]
        for entry in profile.get("rounds", [])
        if any(kw and kw in rname for kw in entry.get("match", []))
    ]
    if not parts:
        return ""
    return "【本轮公司特定考察要求】\n" + "\n".join(parts)


def company_rubric(profile: dict | None) -> str:
    """公司评估量表（进报告，供候选人知道目标公司怎么打分）。"""
    if not profile:
        return ""
    return str(profile.get("evaluation_rubric") or "").strip()
