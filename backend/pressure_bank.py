"""
v6.3: 压力题库（借鉴 mock-interviewer 的 references/出题策略.md「四、压力题库」）。

弥补的能力缺口：
  在此之前，本系统的"压力"只体现在**语气**上（pressure 风格、attack_level、
  hardcore 模式），题目本身仍全部来自简历与 JD —— 候选人多少都准备过。
  而真实面试的压力很大一部分来自**内容层面的不可预测**：突然被问到一道
  完全没准备过的题。这类题无法从简历/JD 推导，只能内置题库随机插入。

设计原则：
  1. **题库是纯数据**，不调 LLM、不查库、不依赖 L3/L4（分层契约：L2）；
  2. **随机但不任性**：注入概率由面试官 attack_level 决定，
     friendly/encouraging 风格几乎不注入（那不符合人设），pressure 风格高概率注入；
  3. **整场限量**（默认 1 道）：压力题是调味不是主菜，多了会让面试变成刁难；
  4. **破冰轮与收尾轮不注入**：前者要让人放松，后者要体面收束（与 CLOSING_INSTRUCTION 一致）；
  5. **注入即登记去重**：走会话层的 asked_question_hashes，避免同一场问到重复的题。

分层契约：本模块属 L2 领域层，仅依赖标准库，禁止 import L3/L4。
被 L3（interview_engine.session）调用。
"""

import random
from typing import Iterable

# ===== 题库：5 类，每类 3-4 道 =====
# 每道题都刻意**不绑定任何简历/JD 内容**——绑定了就失去"不可预测"的意义。

PRESSURE_BANK: dict[str, list[dict[str, str]]] = {
    "方案被否": [
        {
            "question": "如果你精心设计了两个月的方案，被上级当场否掉了，你会怎么处理？",
            "intent": "考察面对否定的情绪管理与复盘能力，看是据理力争、全盘接受还是有第三条路",
        },
        {
            "question": "你和另一个团队的方案在评审会上冲突了，而你俩谁也说服不了谁，接下来你会怎么做？",
            "intent": "考察跨团队冲突处理方式，看是否能上升到目标层面对齐而非陷入技术之争",
        },
        {
            "question": "产品经理说你的技术方案太复杂，要求砍掉一半功能先上线，你怎么取舍？",
            "intent": "考察技术与业务的权衡能力，看是否能在让步的同时守住关键约束",
        },
    ],
    "故障场景": [
        {
            "question": "你负责的服务现在挂了，线上影响还在扩大。你的第一反应是什么，前五分钟做什么？",
            "intent": "考察故障响应的优先级判断：先止损还是先定位，有无清晰的应急顺序",
        },
        {
            "question": "大促期间你负责的接口延迟突然飙升十倍，你会按什么顺序排查？",
            "intent": "考察系统性排障思路，看是凭经验乱猜还是按依赖链路逐层收敛",
        },
        {
            "question": "你刚上线的功能出了严重 bug，已经影响到付费用户了。你怎么处理这件事？",
            "intent": "考察事故处理的完整闭环：止损、通知、定位、复盘，以及是否敢主动担责",
        },
    ],
    "反转": [
        {
            "question": "你说这个方案提升了三倍效率——如果当初没做这件事，团队会怎么做，结果会差多少？",
            "intent": "考察归因是否清醒：成果到底是方案带来的，还是本来就该这么做",
        },
        {
            "question": "这个项目如果不是你来做，换成团队里的另一个人，能做到一样的效果吗？",
            "intent": "考察个人贡献的真实占比，以及对自身可替代性的诚实认知",
        },
        {
            "question": "如果你方案里依赖的核心外部服务价格突然涨十倍，你的方案还成立吗？",
            "intent": "考察方案的前提假设是否被检验过，以及成本敏感度",
        },
    ],
    "竞品对比": [
        {
            "question": "竞品也在做高度类似的事，你们团队投入更大。你觉得你们的壁垒到底在哪？",
            "intent": "考察是否真正理解自己业务的差异化，而非停留在我们做得更好的口号",
        },
        {
            "question": "如果行业头部公司做了一模一样的产品，你怎么赢？",
            "intent": "考察竞争格局判断与差异化策略，看能否给出具体而非空泛的回答",
        },
        {
            "question": "市面上有成熟的开源方案，你们为什么还要自研？",
            "intent": "考察自研决策是否合理，能否说清取舍依据而非陷入重复造轮子",
        },
    ],
    "自我认知": [
        {
            "question": "你觉得自己目前最大的技术短板是什么？这个短板在上一份工作里实际造成过什么后果？",
            "intent": "考察自我认知的真实度，看是否敢于说出具体短板而非套话式缺点",
        },
        {
            "question": "讲一个你做过的最失败的项目。如果重来一次，你会在哪个节点做不同的决定？",
            "intent": "考察复盘深度：能否定位到关键决策节点，而非笼统归因为经验不足",
        },
        {
            "question": "如果让你的团队成员匿名评价你，你觉得他们会怎么说？",
            "intent": "考察自我认知与他人视角的偏差，以及对协作关系的敏感度",
        },
    ],
}


def all_topics() -> list[str]:
    """返回全部压力题类别。"""
    return list(PRESSURE_BANK.keys())


def _fingerprint(text: str) -> str:
    """题目文本指纹（去空白后比对，避免只差空格被当成两道题）。"""
    return "".join((text or "").split())


def list_questions(topic: str | None = None) -> list[dict]:
    """列出题库中的全部题目（含 topic 标注）；指定 topic 时只返回该类。"""
    out: list[dict] = []
    for t, items in PRESSURE_BANK.items():
        if topic and t != topic:
            continue
        for item in items:
            out.append({
                "topic": t,
                "question": item["question"],
                "intent": item["intent"],
            })
    return out


def sample_questions(count: int = 1,
                     exclude: Iterable[str] | None = None,
                     rng: random.Random | None = None) -> list[dict]:
    """随机抽取压力题（不重复类别优先）。

    Args:
        count: 抽取数量。
        exclude: 已用过的题目文本（会话层登记的去重集合），命中则跳过。
        rng: 随机源。测试时传入固定种子的 Random 即可复现；生产用默认全局随机。

    返回 [{"question", "intent", "topic", "is_pressure": True}, ...]。
    题库被抽空或全部命中 exclude 时返回空列表——宁可不出压力题，
    也不要为凑数而重复提问（重复的压力题会直接暴露"这是题库题"）。
    """
    if count <= 0:
        return []

    rand = rng or random
    excluded = {_fingerprint(x) for x in (exclude or [])}

    # 每个类别一个候选池，池内打乱
    topics = all_topics()
    rand.shuffle(topics)
    pools: list[list[dict]] = []
    for t in topics:
        items = [i for i in PRESSURE_BANK.get(t, [])
                 if _fingerprint(i["question"]) not in excluded]
        rand.shuffle(items)
        pools.append([{
            "question": i["question"],
            "intent": i["intent"],
            "topic": t,
            "is_pressure": True,
        } for i in items])

    # 轮转取题（第 1 轮每类取 1 道，第 2 轮再各取 1 道……）：
    # 保证多道时尽量覆盖不同类别。若按顺序填满一个类别再取下一个，
    # 连着问两道"故障场景"会像在考应急预案，而不是真实面试的意外感。
    out: list[dict] = []
    depth = 0
    while len(out) < count:
        added = False
        for pool in pools:
            if depth < len(pool):
                out.append(pool[depth])
                added = True
                if len(out) >= count:
                    break
        if not added:
            break
        depth += 1
    return out[:count]
