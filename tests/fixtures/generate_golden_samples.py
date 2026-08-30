# -*- coding: utf-8 -*-
"""黄金样本夹具生成器（v7.2.1 新增）—— expected 由规则引擎实算，杜绝手算误差。

用法（在项目根目录）：python tests/fixtures/generate_golden_samples.py

为什么需要这个脚本：
  golden_answers.json 的 expected（总分区间 / 最弱维度 / evidence_keys）必须与
  score_adjustments 的确定性规则严格自洽。手写标注极易在「长回答 2-gram 重叠
  意外触发 irrelevant_answer」「同分维度取 DIM_KEYS 序靠前者」这类细节上出错
  （v7.2.1 扩容时实算纠正了 3 处手算偏差），因此标注意图由人给出
  （weakest_intent / 原始五维分 / quote / 评语），期望值由本脚本跑
  detect_adjustments → apply_adjustments → weighted_score 实算生成，
  weakest_intent 与实算不一致、quote 不是答案字面子串时直接拒绝写入。

幂等性：只保留最初 4 条人工基线样本（无 evidence_keys 的即原始样本），
其余一律由 NEW 表重新生成，可安全重跑；baseline 标定在 live 扫描后手工
回填进本文件对应样本或直接改 fixture。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.score_adjustments import (  # noqa: E402
    detect_adjustments, apply_adjustments,
)
from backend.dimension_weights import DIM_KEYS, weighted_score, DEFAULT_WEIGHTS  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "golden_answers.json")


def D(star, quant, logic, job, depth):
    return {
        "star_completeness": star, "quantification": quant,
        "logic_coherence": logic, "job_relevance": job,
        "professional_depth": depth,
    }


# 每条：(id, category, question, answer, 原始五维分, weakest_intent, next_action,
#        follow_up, overall_comment, impact, risk_points, {dim: (quote, comment)}, rewrite)
NEW = [
    dict(
        id="data_conflict_ratio", category="数据前后矛盾 · 同指标两个值",
        question="你优化过哪个接口？性能提升了多少？",
        answer="我们把下单接口优化了，转化率提升了 30%，之后又做了一轮本地缓存改造，"
               "转化率提升到 50%，还把接口的 P99 延迟压缩到了 80ms，整体效果非常明显。",
        dims=D(4.0, 3.0, 4.0, 4.0, 4.0), weakest_intent="quantification",
        next_action="follow_up",
        follow_up="这两个转化率数字口径一致吗？分别是在什么范围和时间段统计的？",
        overall_comment="量化意识强，但同一指标先后给出两个不同数值，数据可信度存疑",
        impact="面试官一旦发现数字对不上，会怀疑整段经历的真实性",
        risks=["同一指标数据前后矛盾"],
        quotes={
            "star_completeness": ("我们把下单接口优化了", "有个人动作，但背景交代偏少"),
            "quantification": ("转化率提升了 30%", "先说 30% 后说 50%，同指标冲突"),
            "logic_coherence": ("之后又做了一轮本地缓存改造", "两轮优化关系交代不清"),
            "job_relevance": ("还把接口的 P99 延迟压缩到了 80ms", "指标与后端岗位相关"),
            "professional_depth": ("整体效果非常明显", "未解释缓存改造的具体机制"),
        },
        rewrite=("我们把下单接口的链路做了两轮优化：第一轮定位慢查询并引入连接池，转化率提升 30%；"
                 "第二轮加本地缓存，转化率提升到 50%，P99 延迟从基线降到 80ms。",
                 ["明确两轮优化的先后关系", "统一指标口径"]),
    ),
    dict(
        id="term_stacking_recall", category="名词堆砌 · 背诵感",
        question="你熟悉哪些消息队列和缓存组件？",
        answer="你问我熟悉哪些消息队列和缓存？Redis、Kafka、MySQL、Docker、K8s、Nginx、"
               "Zookeeper、Elasticsearch 这些我都在生产环境用过。",
        dims=D(3.5, 3.0, 3.0, 3.5, 2.0), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="挑 Kafka 讲讲：你在生产环境用它解决过什么具体问题？",
        overall_comment="组件名罗列密集，但没有任何使用场景和因果展开，背诵感明显",
        impact="面试官会立刻切换到深挖模式，用场景题检验是真用过还是背题",
        risks=["名词堆砌缺少展开"],
        quotes={
            "star_completeness": ("你问我熟悉哪些消息队列和缓存", "没有事件与个人行动的叙事结构"),
            "quantification": ("Redis", "无规模或效果数据"),
            "logic_coherence": ("Kafka", "词与词之间没有逻辑关联"),
            "job_relevance": ("Kafka", "组件与岗位相关，但停留在名词层"),
            "professional_depth": ("这些我都在生产环境用过", "只声明用过，无任何细节支撑"),
        },
        rewrite=("消息队列主要用 Kafka：曾在日志收集场景把单机写入扩到 5 个分区解决消费积压；"
                 "缓存用 Redis，做过热点 key 的本地二级缓存来挡住促销流量。",
                 ["补充使用场景", "补充解决的问题与效果"]),
    ),
    dict(
        id="irrelevant_offtopic", category="答非所问 · 完全跑题",
        question="讲讲 MySQL 索引的底层结构，为什么用 B+ 树？",
        answer="我平时生活里最喜欢的事情是周末去郊外爬山，上个月刚去爬了黄山看日出感觉特别震撼，"
               "此外我还比较喜欢摄影和做饭这些放松方式，我觉得兴趣广泛的人心态会更好一些。",
        dims=D(3.0, 3.0, 2.5, 3.0, 3.0), weakest_intent="logic_coherence",
        next_action="follow_up",
        follow_up="我们回到问题本身：B+ 树和哈希索引比，各自适合什么场景？",
        overall_comment="回答与所问的技术问题完全无关，无法评估目标能力",
        impact="面试官会认为候选人在回避问题，直接记为负面信号",
        risks=["答非所问"],
        quotes={
            "star_completeness": ("我平时生活里最喜欢的事情是周末去郊外爬山", "与问题无关的叙事"),
            "quantification": ("上个月刚去爬了黄山", "无任何与问题相关的数据"),
            "logic_coherence": ("此外我还比较喜欢摄影和做饭这些放松方式", "内容无法回应提问"),
            "job_relevance": ("我觉得兴趣广泛的人心态会更好一些", "与岗位能力无关联"),
            "professional_depth": ("我觉得兴趣广泛的人心态会更好一些", "无技术内容"),
        },
        rewrite=("MySQL 索引用 B+ 树：叶子节点存数据且有序，等值和范围查询都能走索引，"
                 "相比哈希索引多了范围扫描能力，也更适合磁盘页的按块读取。",
                 ["正面回答问题", "给出结构与原因"]),
    ),
    dict(
        id="blame_shift_product", category="甩锅外部 · 排期问题",
        question="为什么这个项目延期了两个月才上线？",
        answer="主要是产品要求的改动太多了，跟我没关系，都是他们排期的问题。",
        dims=D(2.5, 3.5, 3.0, 3.5, 3.5), weakest_intent="star_completeness",
        next_action="follow_up",
        follow_up="延期两个月，你这边做了哪些努力去追赶进度？",
        overall_comment="把延期完全归因外部，没有说明自己的判断与应对动作",
        impact="面试官会质疑协作意识与担当，这类回答在行为面是明显减分项",
        risks=["归因外部", "回答过短未展开"],
        quotes={
            "star_completeness": ("主要是产品要求的改动太多了", "归因外部，无个人行动"),
            "quantification": ("都是他们排期的问题", "无数据支撑"),
            "logic_coherence": ("跟我没关系", "因果链断裂"),
            "job_relevance": ("主要是产品要求的改动太多了", "未回应自身职责"),
            "professional_depth": ("都是他们排期的问题", "无技术内容"),
        },
        rewrite=("当时需求变更比立项时多了三成，我先和产品对齐了优先级，把 P0 需求保住按期上线，"
                 "P1 需求排到下个迭代，并把这个机制固化到了后续项目的需求评审里。",
                 ["承认客观因素的同时给出个人应对", "补充结果"]),
    ),
    dict(
        id="too_short_passive", category="回答过短 · 被动等待追问",
        question="介绍一下你负责过的最有挑战的项目？",
        answer="我做过一个电商后台，挑战挺大的，顺利完成了上线。",
        dims=D(2.0, 3.0, 3.0, 3.0, 3.0), weakest_intent="star_completeness",
        next_action="follow_up",
        follow_up="挑战具体体现在哪里？你在里面负责哪一块？",
        overall_comment="信息量过少，没有展开任何背景、动作与结果",
        impact="面试官需要连续追问才能拼出信息，第一印象是表达意愿不足",
        risks=["回答过短未展开"],
        quotes={
            "star_completeness": ("我做过一个电商后台", "只有事件名词，无背景与个人动作"),
            "quantification": ("挑战挺大的", "无量化"),
            "logic_coherence": ("挑战挺大的", "挑战是什么未交代"),
            "job_relevance": ("电商后台", "与岗位相关性待确认"),
            "professional_depth": ("顺利完成了上线", "无技术细节"),
        },
        rewrite=("我负责电商后台的订单超时关闭模块：难点是高并发下关单与支付的状态一致性，"
                 "我用延迟队列加幂等兜底解决了重复关单，上线后零客诉。",
                 ["补充背景与难点", "补充个人动作与结果"]),
    ),
    dict(
        id="verb_without_numbers", category="有成果动词 · 无任何数字",
        question="你做的性能优化工作效果怎么样？",
        answer="这次性能优化工作效果最明显的是商品详情页：我们改造了缓存策略，命中率提升非常大，"
               "接口耗时改善也很大，大促期间卡顿投诉基本消失了。",
        dims=D(3.5, 2.5, 3.5, 3.5, 3.5), weakest_intent="quantification",
        next_action="follow_up",
        follow_up="命中率具体提升了多少？接口耗时从多少降到多少？",
        overall_comment="方向和动作都合理，但通篇没有一个数字，效果无法评估",
        impact="面试官会逐项追问数字，答不出会让前面所有描述的可信度打折",
        risks=["成果描述未量化"],
        quotes={
            "star_completeness": ("我们改造了缓存策略", "有个人动作，缺少背景任务结构"),
            "quantification": ("命中率提升非常大", "有成果动词但无任何数值"),
            "logic_coherence": ("这次性能优化工作效果最明显的是商品详情页", "对象明确，表述通顺"),
            "job_relevance": ("接口耗时改善也很大", "与岗位相关"),
            "professional_depth": ("我们改造了缓存策略", "未说明缓存策略的具体设计"),
        },
        rewrite=("详情页缓存命中率从 62% 提升到 94%，接口 P99 从 450ms 降到 120ms，"
                 "大促期间卡顿类工单下降了九成。",
                 ["为每项成果补充量化数据"]),
    ),
    dict(
        id="quantified_metrics", category="量化充分 · 多组指标",
        question="这轮优化带来的可量化收益有哪些？",
        answer="这轮优化可量化的收益主要有三个：接口 P99 延迟从 800ms 降到 200ms，"
               "吞吐量提升到 6000 QPS，线上故障率下降了 40%，前后持续 6 周，"
               "覆盖订单和支付两条核心链路。",
        dims=D(4.0, 4.5, 4.0, 4.0, 3.5), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="故障率下降 40% 是怎么归因到这轮优化的？有没有对照数据？",
        overall_comment="多组量化指标前后对照清晰，数据意识很强",
        impact="量化扎实会显著提升面试官信任，但会被追问数据口径与归因",
        risks=["数据归因待补充"],
        quotes={
            "star_completeness": ("覆盖订单和支付两条核心链路", "范围明确，背景交代完整"),
            "quantification": ("接口 P99 延迟从 800ms 降到 200ms", "多组量化前后对照"),
            "logic_coherence": ("吞吐量提升到 6000 QPS", "指标并列罗列，归因链路可再补"),
            "job_relevance": ("覆盖订单和支付两条核心链路", "与后端岗位高度相关"),
            "professional_depth": ("线上故障率下降了 40%", "未解释优化如何传导到故障率"),
        },
        rewrite=("这轮优化 6 周内分两阶段落地：先降 P99（800ms→200ms），再扩容提吞吐（6000 QPS），"
                 "故障率下降 40% 通过上线前后各一个月的告警数据对照归因。",
                 ["补充归因方法", "分阶段呈现"]),
    ),
    dict(
        id="cross_project_link", category="跨项目串联 · 系统性思维",
        question="除了这个项目，你还主导过哪些有代表性的工作？",
        answer="主导过支付网关的重构，把老的同步对账改成了异步批处理，日对账时效从 T+1 提前到 T+0；"
               "同时我还牵头做了统一鉴权平台，把三个业务线的登录逻辑收敛到一处，"
               "token 泄漏类工单下降了 70%；另外在数据侧推动过埋点规范的落地，"
               "让后续的漏斗分析有了统一口径。",
        dims=D(4.0, 3.5, 4.0, 3.0, 2.5), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="统一鉴权平台迁移三个业务线时，灰度和兼容是怎么做的？",
        overall_comment="能把多段工作用关联词串成体系，体现系统性；但各段的技术深度都偏浅",
        impact="多线程推进的经历是加分项，深度追问会集中在迁移与兼容方案上",
        risks=["单项深度不足"],
        quotes={
            "star_completeness": ("主导过支付网关的重构", "有多段完整事件"),
            "quantification": ("token 泄漏类工单下降了 70%", "有关键量化"),
            "logic_coherence": ("同时我还牵头做了统一鉴权平台", "用关联词串联多段经历"),
            "job_relevance": ("统一鉴权平台", "与岗位相关性强"),
            "professional_depth": ("把三个业务线的登录逻辑收敛到一处", "迁移与兼容方案未展开"),
        },
        rewrite=("统一鉴权平台按业务线分三批灰度迁移：先接测试流量验证协议兼容，"
                 "再用双 token 过渡期保证老客户端无感升级，最后下线旧登录模块。",
                 ["补充迁移与灰度方案", "补充风险控制"]),
    ),
    dict(
        id="candid_unknown_with_plan", category="坦诚不足 · 给出学习方向",
        question="讲讲 JVM G1 垃圾回收器的原理，你了解多少？",
        answer="G1 的回收原理这块我之前只在课程项目里碰过一次，说实话我对它不太了解，"
               "接下来我会去把官方文档和源码过一遍，再自己搭个集群练手，"
               "争取下次能讲清楚它的触发机制和调优思路。",
        dims=D(3.0, 3.0, 3.5, 3.5, 1.0), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="那你现在能讲讲 CMS 和 G1 最核心的一个区别吗？",
        overall_comment="坦承知识边界并给出可执行的学习计划，态度分拉回部分专业分",
        impact="比不懂装懂好得多；面试官可能降低该领域预期，转而考察学习执行力",
        risks=["核心知识存在空白"],
        quotes={
            "star_completeness": ("我之前只在课程项目里碰过一次", "交代了经验边界"),
            "quantification": ("只在课程项目里碰过一次", "无量化需求"),
            "logic_coherence": ("接下来我会去把官方文档和源码过一遍", "学习路径清晰"),
            "job_relevance": ("争取下次能讲清楚它的触发机制和调优思路", "学习方向与岗位相关"),
            "professional_depth": ("说实话我对它不太了解", "坦诚知识空白"),
        },
        rewrite=("G1 我掌握到使用层：region 分区、增量回收、可预测停顿目标是它的三个关键词，"
                 "回收算法细节我计划两周内通过官方文档加源码补齐，先用小集群验证。",
                 ["先框定已知边界", "给出补齐计划与验证方式"]),
    ),
    dict(
        id="failure_reflection", category="失败案例 · 反思改进",
        question="说一次你搞砸过的经历，当时怎么处理的？",
        answer="这个项目第一版上线后 3 天就出过一次线上事故，我们后来复盘总结，"
               "重新设计了灰度发布的流程，改进了回滚机制，之后半年没再出过大问题。",
        dims=D(3.5, 3.0, 4.0, 3.5, 1.5), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="那次事故的根因是什么？灰度流程具体改了哪几步？",
        overall_comment="主动暴露失败并给出机制层面的改进，复盘意识好；根因分析偏浅",
        impact="敢于讲失败是成熟信号，但面试官一定会追问根因，答不出会反转印象",
        risks=["根因分析未展开"],
        quotes={
            "star_completeness": ("这个项目第一版上线后 3 天就出过一次线上事故", "事件背景完整"),
            "quantification": ("3 天", "有时间量化"),
            "logic_coherence": ("我们后来复盘总结", "事故到改进的因果清晰"),
            "job_relevance": ("重新设计了灰度发布的流程", "与工程实践相关"),
            "professional_depth": ("改进了回滚机制", "根因与机制细节未展开"),
        },
        rewrite=("事故根因是灰度批次间隔过短导致配置热更新冲突；复盘后我把灰度从两批改成五批，"
                 "每批加自动回归检查点，并给回滚脚本加了幂等锁，此后同类问题零复发。",
                 ["补充根因分析", "改进措施落到机制层面"]),
    ),
    dict(
        id="mixed_bonus_strong", category="双加分 · 量化充分且跨项目串联",
        question="说说你主导过的两项有代表性的技术工作，分别带来了什么结果？",
        answer="我主导过两件事：因为老网关的同步对账跑批太慢，我把对账链路重构成异步批处理，"
               "时效从 T+1 提前到 T+0，资损告警响应时间缩短了 80%；同时我把鉴权模块抽成了独立服务，"
               "三条业务线接入后 token 类工单下降了 70%，这套思路后来还被日志平台借鉴走了。",
        dims=D(4.0, 4.0, 4.5, 3.0, 3.0), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="对账从同步改异步，一致性怎么保证？对不平的账怎么处理？",
        overall_comment="量化与系统性兼备的高质量回答，两段工作都有明确收益",
        impact="这类回答会让面试官提升对候选人的整体预期，追问会走向实现细节",
        risks=["一致性方案待展开"],
        quotes={
            "star_completeness": ("我主导过两件事", "两段完整事件叙事"),
            "quantification": ("资损告警响应时间缩短了 80%", "多组量化收益"),
            "logic_coherence": ("因为老网关的同步对账跑批太慢", "因果动机清晰"),
            "job_relevance": ("同时我把鉴权模块抽成了独立服务", "工作与岗位强相关"),
            "professional_depth": ("我把对账链路重构成异步批处理", "改造机制未展开"),
        },
        rewrite=("对账一致性靠日切快照加对账单补偿：异步批处理前先冻结快照，对不平自动生成"
                 "差异单进人工审核队列，T+1 前闭环。",
                 ["补充一致性设计", "补充异常路径"]),
    ),
    dict(
        id="mixed_penalty_caps", category="三重扣分 · 堆砌且未量化且过短",
        question="聊聊你的后端技术储备和最近的实践？",
        answer="熟悉 Redis、Kafka、MySQL、Docker、K8s，优化过很多模块，效果很好",
        dims=D(3.0, 2.5, 3.0, 3.0, 2.0), weakest_intent="professional_depth",
        next_action="follow_up",
        follow_up="挑一个你优化过的模块，讲讲当时的问题和你的方案？",
        overall_comment="名词堆砌加无数据加过短，三类信号同时触发，是典型的背诵式回答",
        impact="面试官基本会判定为准备不足，进入压力追问模式",
        risks=["名词堆砌", "成果描述未量化", "回答过短未展开"],
        quotes={
            "star_completeness": ("优化过很多模块", "无任何具体事件"),
            "quantification": ("优化过很多模块", "有成果动词但无数字"),
            "logic_coherence": ("效果很好", "结论无支撑"),
            "job_relevance": ("Redis", "组件相关但无场景"),
            "professional_depth": ("熟悉 Redis", "只有名词层，无深度信号"),
        },
        rewrite=("最近在用 Kafka 做订单事件分发：遇到过消费积压，我把分区从 6 扩到 12 并给"
                 "消费者加了批量拉取，积压在 20 分钟内清零，订单延迟从分钟级降到秒级。",
                 ["挑一个组件展开", "补充问题、方案与量化结果"]),
    ),
    dict(
        id="clamp_double_penalty", category="夹紧保护 · 规则不再重复惩罚",
        question="这个功能上线的效果如何？",
        answer="这个功能上线之后效果提升特别明显，核心功能的完成率提高了很多，"
               "用户反馈都说体验好了不少，老板在周会上也专门表扬了这个项目，"
               "团队整体士气提升很大。",
        dims=D(3.5, 1.0, 3.5, 3.5, 3.5), weakest_intent="quantification",
        next_action="follow_up",
        follow_up="完成率从多少提高到多少？找一个你能报出来的数字。",
        overall_comment="通篇是定性形容，模型已把量化维度打到最低分，规则修正被夹紧不再重复扣",
        impact="面试官会直接要求报数字，报不出则整段评价都会被降级",
        risks=["成果描述未量化"],
        quotes={
            "star_completeness": ("老板在周会上也专门表扬了这个项目", "有事件但结果未量化"),
            "quantification": ("效果提升特别明显", "模型已给最低分，规则扣分被夹紧"),
            "logic_coherence": ("核心功能的完成率提高了很多", "表述通顺但空洞"),
            "job_relevance": ("核心功能的完成率", "与岗位相关"),
            "professional_depth": ("用户反馈都说体验好了不少", "定性描述无技术细节"),
        },
        rewrite=("上线两周后核心功能完成率从 71% 提升到 89%，用户侧好评率 96%，"
                 "周会表扬之外我把这次的经验沉淀成了操作 SOP。",
                 ["用数字替换定性形容"]),
    ),
    dict(
        id="blame_shift_core_module", category="甩锅其他团队 · 回避角色",
        question="你在核心模块的开发里承担了什么角色？",
        answer="核心模块当时是其他团队在做，我们这边只提供了数据接口，"
               "具体他们内部怎么排期的我不太清楚，反正最后延期不归我们管。",
        dims=D(2.0, 3.0, 3.0, 3.0, 3.0), weakest_intent="star_completeness",
        next_action="follow_up",
        follow_up="你提供的数据接口被他们怎么使用的？接口设计上你做了哪些取舍？",
        overall_comment="把自己放在事件之外，连自己负责的接口都没有展开",
        impact="面试官会认为候选人不了解全局也缺乏参与感，追问会很难受",
        risks=["归因外部", "答非所问倾向"],
        quotes={
            "star_completeness": ("核心模块当时是其他团队在做", "归因外部，回避个人角色"),
            "quantification": ("只提供了数据接口", "无量化"),
            "logic_coherence": ("反正最后延期不归我们管", "结论与论证脱节"),
            "job_relevance": ("我们这边只提供了数据接口", "接口工作本可展开却放弃"),
            "professional_depth": ("具体他们内部怎么排期的我不太清楚", "无技术内容"),
        },
        rewrite=("核心模块由其他团队主开发，我负责给他们提供数据接口：当时为了支撑他们的"
                 "高并发查询，我把接口改成了批量模式并加了二级缓存，P99 稳定在 50ms 内。",
                 ["正面回答自己的角色", "把自己负责的部分讲深"]),
    ),
    dict(
        id="next_question_clean", category="高质量回答 · 直接进入下一题",
        question="你平时靠什么流程保证代码质量？",
        answer="我平时靠三层流程来保证代码质量：提交前跑本地单测和 lint，必须全部通过；"
               "评审环节请资深同事重点看边界条件和异常处理；上线前还有灰度发布和监控告警兜底，"
               "出问题 5 分钟内可以回滚。",
        dims=D(4.5, 3.5, 4.0, 4.0, 4.0), weakest_intent="quantification",
        next_action="next_question",
        follow_up="这三层流程里，评审环节发现过哪类最高频的问题？",
        overall_comment="流程分层清晰、有兜底手段，可直接进入下一题",
        impact="流程化思维是工程成熟度的直接信号，整体印象加分",
        risks=["量化覆盖还可加强"],
        quotes={
            "star_completeness": ("提交前跑本地单测和 lint", "行动具体可验证"),
            "quantification": ("出问题 5 分钟内可以回滚", "有关键时间量化"),
            "logic_coherence": ("我平时靠三层流程来保证代码质量", "三层结构清晰"),
            "job_relevance": ("评审环节请资深同事重点看边界条件和异常处理", "贴合工程实践"),
            "professional_depth": ("上线前还有灰度发布和监控告警兜底", "有兜底设计意识"),
        },
        rewrite=("在现有三层流程之上，我还会把每轮评审的高频问题归类成 checklist 沉淀到团队 wiki，"
                 "让下一轮评审有据可依。",
                 ["补充流程的迭代机制"]),
    ),
    dict(
        id="candid_gap_short", category="坦诚不足 · 短回答双信号",
        question="聊聊你对服务网格 Istio 的理解？",
        answer="这个我没接触过，不太了解，不过我会去查一下资料补上。",
        dims=D(2.5, 2.5, 2.5, 2.5, 2.0), weakest_intent="star_completeness",
        next_action="follow_up",
        follow_up="那换个你熟悉的：讲一个你最近深入学过的技术组件？",
        overall_comment="坦诚但没有展开任何已有知识的迁移，回答过短",
        impact="诚实是加分项，但完全不尝试迁移已有知识会显得积累单薄",
        risks=["回答过短未展开", "知识空白"],
        quotes={
            "star_completeness": ("这个我没接触过", "无任何事件展开"),
            "quantification": ("这个我没接触过", "无量化需求"),
            "logic_coherence": ("不过我会去查一下资料补上", "有转折但内容单薄"),
            "job_relevance": ("我会去查一下资料补上", "学习意愿与岗位相关"),
            "professional_depth": ("这个我没接触过", "坦诚知识空白"),
        },
        rewrite=("Istio 我没在生产用过，但我理解它解决的是服务间流量治理问题，"
                 "和我们自研网关做灰度路由是同一类需求，区别在于它把能力下沉到了 sidecar 层。",
                 ["尝试知识迁移", "给出已有的相近经验"]),
    ),
]


def main():
    with open(FIXTURE, encoding="utf-8") as f:
        fixture = json.load(f)

    # 幂等：只保留最初 4 条人工基线样本（v7.1 手工标定并已带 live baseline），
    # 其余一律由 NEW 表重新生成，可安全重跑。用硬编码 id 识别，避免误判。
    ORIGINAL_IDS = {
        "quantified_full_star_gap", "vague_slogans",
        "star_complete_quantified", "blame_shift_avoidance",
    }
    base_samples = [s for s in fixture["samples"] if s["id"] in ORIGINAL_IDS]
    base_ids = {s["id"] for s in base_samples}
    new_samples = []

    for s in NEW:
        if s["id"] in base_ids:
            continue
        q, a, dims = s["question"], s["answer"], s["dims"]
        adjs = detect_adjustments(q, a)
        adj_dims = apply_adjustments(dims, adjs)
        overall = weighted_score(adj_dims, DEFAULT_WEIGHTS)
        valid = {k: v for k, v in adj_dims.items() if v > 0}
        weakest = min(valid, key=lambda k: (valid[k], -DEFAULT_WEIGHTS.get(k, 0.2)))
        fired = [x.key for x in adjs]

        # ---- 校验 1：意图最弱维度必须与实算一致 ----
        assert weakest == s["weakest_intent"], (
            f"{s['id']}: 实算最弱 {weakest} != 意图 {s['weakest_intent']} "
            f"(adjusted={adj_dims}, fired={fired})")

        # ---- 校验 2：quote 必须是答案字面子串 ----
        for dim, (quote, _c) in s["quotes"].items():
            assert quote in a, f"{s['id']}: quote 不是字面子串: {quote!r}"
        assert set(s["quotes"]) == set(DIM_KEYS), f"{s['id']}: quotes 维度不齐"

        # ---- expected 由实算生成（区间宽度 ±0.4，规则真值见 score_adjustments.py） ----
        sample = {
            "id": s["id"],
            "category": s["category"],
            "question": q,
            "answer": a,
            "diagnosis": {
                **{k: {"score": dims[k], "comment": s["quotes"][k][1],
                       "quote": s["quotes"][k][0]} for k in DIM_KEYS},
                "weakest_dimension": s["weakest_intent"],
                "follow_up_question": s["follow_up"],
                "overall_score": round(sum(dims.values()) / 5, 2),
                "overall_comment": s["overall_comment"],
                "real_interview_impact": s["impact"],
                "next_action": s["next_action"],
                "risk_points": s["risks"],
            },
            "rewrite": {
                "rewritten_answer": s["rewrite"][0],
                "key_changes": s["rewrite"][1],
            },
            "expected": {
                "overall_min": round(overall - 0.4, 1),
                "overall_max": round(overall + 0.4, 1),
                "weakest_dimension": weakest,
                "evidence_keys": sorted(set(fired)),
            },
            # baseline 留空：待 live-LLM 扫描标定（测试对无 baseline 样本自动跳过基线守护）
        }
        print(f"[{s['id']}] fired={fired} overall={overall} weakest={weakest} "
              f"adj={ {k: adj_dims[k] for k in DIM_KEYS if adj_dims[k] != dims[k]} }")
        new_samples.append(sample)

    fixture["samples"] = base_samples + new_samples
    fixture["note"] = (
        "黄金样本回归夹具（v7.1 新增，v7.1 校准 baseline，v7.2.1 扩容 4→20 条）。"
        "样本覆盖：量化充分但 STAR 欠缺 / 全篇口号 / STAR 完整且量化充分 / 甩锅避答（原 4 条），"
        "以及数据矛盾、名词堆砌、答非所问、甩锅外部、回答过短、有动词无数字、量化充分、"
        "跨项目串联、坦诚不足、失败反思、双加分、三重扣分封顶、夹紧保护、高质量 next_question 等 16 条新类别。"
        "expected = 人工标注的『应然』区间，供第 1 层确定性回归断言（验证全链路不回退）与人工对照质量线；"
        "v7.2.1 起新增样本的 expected.evidence_keys 由 tests/fixtures/generate_golden_samples.py "
        "跑规则引擎实算生成（标注意图由人给出，期望值由确定性规则取真值），保证子集断言自洽。"
        "baseline = deepseek-chat 的『实然』快照：原 4 条已标定；"
        "v7.2.1 新增 16 条暂无 baseline，live-LLM 抽检自动跳过无 baseline 样本，待首轮 live 扫描后补标。"
        "diagnosis 为人工标注的诊断 JSON（模拟 LLM 输出，使全链路确定性可回归）。"
    )

    with open(FIXTURE, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)
    print(f"\nOK: fixture updated, total samples = {len(fixture['samples'])}")


if __name__ == "__main__":
    main()
