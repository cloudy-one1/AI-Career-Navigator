"""
v6.3: 简历锚点五分类（借鉴 mock-interviewer 的 references/出题策略.md）。

解决的问题：
  v6.2 的简历追问点是 **deep / vague 二分类**（对标 GrillMind deepDivePoints/vaguePoints）。
  二分法能定位"哪里值得问"，但**不能告诉模型"该往哪个方向问"**——
  同样是"写了但没展开"，技术选型、量化数据、业务决策的追问方向完全不同。

  本项目把锚点拆成五类，每类绑定一条追问方向：

    tech_choice       技术选型    → 为什么选它不选别的？原理？限制？踩过什么坑？
    metric            量化数据    → 怎么测的？AB 还是前后对比？峰值？置信度？
    architecture      架构设计    → 整体怎么设计的？为什么？瓶颈？迁移怎么做？
    business_decision 业务决策    → 为什么做？谁发起？优先级？归因？自然增长多少？
    team              团队管理    → 怎么组建分工？跨团队难点？怎么推动？

与原书的一处关键判断（直接采纳）：**简历中出现的所有数字都是高价值追问点**——
这条规则简单、可执行、命中率极高，因此 metric 类对数字给了额外权重。

分层契约：本模块属 L2 领域层，仅依赖标准库，禁止 import L3/L4。
被 L3（question_gen）与 L2 同层（resume_parser）调用。

两种产出路径（互为兜底，不互相依赖）：
  1) resume_parser 让 LLM 直接按五类输出（结构化，质量高，依赖模型遵守格式）；
  2) 本模块的 classify() 用关键词规则对既有 deep/vague 点做分类（确定性，零成本）。
LLM 输出缺失/格式不符时自动回落到路径 2，功能不退化。
"""

import re
from typing import Iterable

# ===== 五类锚点定义 =====

TECH_CHOICE = "tech_choice"
METRIC = "metric"
ARCHITECTURE = "architecture"
BUSINESS_DECISION = "business_decision"
TEAM = "team"

ANCHOR_KEYS = (TECH_CHOICE, METRIC, ARCHITECTURE, BUSINESS_DECISION, TEAM)

ANCHOR_META = {
    TECH_CHOICE: {
        "label": "技术选型",
        "probe": "为什么选它而不是别的方案？它的核心机制理解到什么程度？实际使用中踩过什么坑、有什么限制？",
        "keywords": (
            "用了", "基于", "采用", "选型", "引入", "接入", "替换为", "迁移到",
            "框架", "组件", "中间件", "技术栈", "工具", "库", "sdk", "api",
            "redis", "kafka", "mysql", "es", "mq", "rpc", "orm",
        ),
    },
    METRIC: {
        "label": "量化数据",
        "probe": "这个数字是怎么测出来的？AB 实验还是前后对比？峰值和低谷分别是多少？置信度如何？",
        "keywords": (
            "提升", "降低", "减少", "增长", "下降", "优化", "节省", "缩短",
            "qps", "tps", "延迟", "耗时", "毫秒", "吞吐", "并发", "p99", "p95",
            "转化率", "留存", "覆盖率", "准确率", "倍", "万", "亿",
        ),
    },
    ARCHITECTURE: {
        "label": "架构设计",
        "probe": "整体架构是怎么设计的？为什么这样设计？瓶颈在哪？老架构有什么问题、迁移怎么做的？",
        "keywords": (
            "架构", "系统设计", "重构", "从0到1", "从零", "搭建", "设计",
            "微服务", "分布式", "模块", "分层", "高可用", "容灾", "扩展性",
            "演进", "解耦", "治理", "中台",
        ),
    },
    BUSINESS_DECISION: {
        "label": "业务决策",
        "probe": "为什么做这件事？谁发起的？优先级怎么定的？成果怎么归因？有多少是自然增长？",
        "keywords": (
            "业务", "主导", "决策", "优先级", "立项", "产品", "需求", "上线",
            "商业化", "战略", "规划", "目标", "指标", "增长", "营收", "成本", "roi",
        ),
    },
    TEAM: {
        "label": "团队管理",
        "probe": "团队怎么组建与分工的？跨团队协作的难点是什么？怎么推动别人接受你的方案？",
        "keywords": (
            "团队", "带领", "协同", "协作", "跨部门", "跨团队", "管理", "招聘",
            "培养", "分工", "推广", "成员", "沟通", "推动", "考核", "汇报",
        ),
    },
}

# 数字是 metric 类最强特征：含阿拉伯数字或百分号即视为强信号
_NUMBER_RE = re.compile(r"\d|%|％")

# 每类每条最多注入的点数（防 prompt 膨胀）；整段上限另行控制
_ANCHOR_ITEM_LIMIT = 3
_ANCHOR_TOTAL_LIMIT = 8


def classify(text: str) -> str:
    """把一条追问点归入五类之一；无法归类时返回空串。

    计分规则：命中一个关键词 +1；含数字/百分号对 metric 额外 +1。
    取最高分类，分数为 0 或并列最高时返回空串（宁可不分类，也不乱分类）。

    两个刻意的取舍：
    - 数字只加 1 而非 2：加 2 会让"带领 5 人团队"这类点常与 team 打平，
      平局又弃权，等于白白丢掉一个可用锚点。数字仍是强信号，只是不再压过语义。
    - 为什么"并列即弃权"：强行归入某一类会把错误的追问方向注入 prompt，
      比不分类的损害更大——不分类时模型至少还能自己判断往哪问。
    """
    if not text:
        return ""
    low = str(text).lower()

    scores: dict[str, int] = {}
    for key, meta in ANCHOR_META.items():
        score = sum(1 for kw in meta["keywords"] if kw in low)
        if score:
            scores[key] = score

    if _NUMBER_RE.search(low):
        scores[METRIC] = scores.get(METRIC, 0) + 1

    if not scores:
        return ""

    best = max(scores.values())
    if best <= 0:
        return ""
    winners = [k for k, v in scores.items() if v == best]
    return winners[0] if len(winners) == 1 else ""


def group_points(points: Iterable) -> dict[str, list[str]]:
    """把扁平的追问点列表按五类分组（规则分类兜底路径）。

    无法归类的点**丢弃**而不是塞进某一类——分组的目的是给出追问方向，
    方向不明的点保留为"无方向提示"意义不大，反而稀释有效锚点。
    """
    grouped: dict[str, list[str]] = {k: [] for k in ANCHOR_KEYS}
    for p in points or []:
        s = str(p).strip()
        if not s:
            continue
        key = classify(s)
        if key:
            grouped[key].append(s)
    return grouped


def normalize_anchors(raw) -> dict[str, list[str]]:
    """规整 LLM 产出的五类锚点为标准结构 {key: [point, ...]}。

    接受两种输入：
      - dict：{"tech_choice": [...], "metric": [...], ...}
      - list：[{"type": "metric", "point": "..."}, ...]
    非法/缺失一律降级为空字典（由调用方回落到规则分类）。
    """
    out: dict[str, list[str]] = {k: [] for k in ANCHOR_KEYS}
    if not raw:
        return out

    if isinstance(raw, dict):
        for key in ANCHOR_KEYS:
            items = raw.get(key) or []
            if isinstance(items, str):
                items = [items]
            if not isinstance(items, (list, tuple)):
                continue
            out[key].extend(str(x).strip() for x in items if str(x).strip())

    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                key = str(item.get("type", "") or "").strip()
                point = str(item.get("point", "") or "").strip()
            else:
                key = classify(str(item))
                point = str(item).strip()
            if key in out and point:
                out[key].append(point)

    for key in out:
        out[key] = list(dict.fromkeys(out[key]))  # 去重保序
    return out


def merge_anchor_sources(llm_anchors: dict | None,
                         flat_points: Iterable | None) -> dict[str, list[str]]:
    """合并 LLM 五类输出与规则分类结果。

    优先用 LLM 输出；某一类 LLM 没给出时，用规则对 flat_points 的分类结果补齐。
    这样即使模型只输出了两类，其余三类也不会整体缺失。
    """
    merged = normalize_anchors(llm_anchors)
    ruled = group_points(flat_points)
    for key in ANCHOR_KEYS:
        if not merged[key] and ruled[key]:
            merged[key] = ruled[key]
    return merged


def build_anchors_block(anchors: dict | None,
                        item_limit: int = _ANCHOR_ITEM_LIMIT,
                        total_limit: int = _ANCHOR_TOTAL_LIMIT) -> str:
    """把五类锚点格式化为出题/诊断 prompt 片段；无有效内容返回空串。

    为什么每类只带 2-3 条并设总量上限：锚点段落是**提示**不是题库，
    条数一多就会挤占 JD 与简历正文的上下文预算，反而降低出题质量。
    """
    if not isinstance(anchors, dict):
        return ""

    lines: list[str] = []
    used = 0
    for key in ANCHOR_KEYS:
        items = [str(x).strip() for x in (anchors.get(key) or []) if str(x).strip()]
        if not items or used >= total_limit:
            continue
        meta = ANCHOR_META[key]
        take = items[:max(1, min(item_limit, total_limit - used))]
        lines.append(f"· {meta['label']}（{len(take)} 条）—— 追问方向：{meta['probe']}")
        for it in take:
            lines.append(f"  - {it}")
        used += len(take)

    if not lines:
        return ""

    return (
        "\n★ 锚点类型与追问方向（按类型给出该往哪个方向问，不要只问「再展开讲讲」）：\n"
        + "\n".join(lines)
    )
