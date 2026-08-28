# Gua-AI-interview（瓜分Offer）深度研读报告

> 研读对象：<https://github.com/wzxgA/Gua-AI-interview>（MIT，18★，4 fork，177 commits）
> 研读方式：`git clone --depth 1` 全量源码通读 + 作者自撰的 6 篇 `lessons/` 设计方案交叉核对
> 研读目的：为本项目（AI 模拟面试官 v6.2）寻找可迁移机制、并识别应规避的坑
> 代码引用路径均相对该仓库根目录

---

## 0. 速览

| 项 | 内容 |
|---|---|
| 定位 | **招聘方视角**的 AI 面试 Agent 平台（管理端建岗/建题/传简历 → 生成候选人链接 → 候选人进面试间 → 五维评估报告） |
| 后端 | Java 21（虚拟线程）· Spring Boot 3.5.3 · Spring AI 1.1.2 · **LangGraph4j 1.8.22** |
| 存储 | PostgreSQL 16 + pgvector（halfvec 2048 / HNSW / pg_trgm）· Redis 7 · Kafka 3.8（KRaft）· MinIO |
| 前端 | React 19 + TS + Vite 6 + Tailwind + TanStack Query + zustand，约 12.9k 行 |
| 代码规模 | 后端 main 约 **20.5k 行 / 352 个 .java**；test 58 文件 / 7.9k 行 / **361 个 @Test** |
| 工程化 | Maven 5 模块 + Flyway 23 个迁移脚本 + Spotless(AOSP) + JaCoCo 门槛 + Actuator/Micrometer + Docker Compose |
| 文档 | README 30.8KB（中英双版）+ `lessons/` 6 篇设计方案（合计约 120KB，含大量 mermaid） |

一句话概括：**它是本领域里少见的"把面试流程当成显式状态机工程"的实现——用 LangGraph4j 把"面试进行到哪一步"从代码控制流里抽出来变成可持久化的 State + Checkpoint，并且保留旧命令式链路做灰度回退。**

与前两份研读对象的定位差异：

| | GrillMind | HakiMeet | **Gua-AI-interview** |
|---|---|---|---|
| 面试官编排 | 自研状态机（阶段+轮次计数） | **整体外包**给豆包 Realtime | 自研 + LangGraph4j 状态图 |
| 视角 | 候选人自练 | 候选人自练 | **招聘方 + 候选人双端** |
| 可控性 | 高（配置驱动阶段） | 极低（不可控不可测） | 高（节点/边/State 显式） |
| 测试 | 少 | **0** | **361 个 @Test** |
| 工程复杂度 | 中 | 低 | 高（也是它最大的成本） |

---

## 1. 架构总览

### 1.1 Maven 五模块与依赖方向

```
interview-core     领域模型/统一响应/错误码（无框架依赖，纯 POJO+record）
interview-ai       ModelRouter/ModelTier/AiChatFacade/Advisor 链/Redis 对话记忆
interview-agent    7 个 Agent + Prompt Builder + orchestration（graph/node/state/checkpoint/observability）
interview-infra    MyBatis-Plus 持久层/pgvector RAG/Kafka/MinIO/TTS/Flyway
interview-gateway  启动入口/REST Controller/WebSocket Handler/WorkflowEngine/JWT/Kafka Consumer
```

依赖方向：`gateway → agent → ai → core`，`gateway → infra → ai → core`。

> 这与本项目 CHARTER 的 L1–L4 分层是同一件事，差别在于**它用 Maven 模块边界做物理强制**（编译期即报错），我们用 `.importlinter` 契约做工具强制。它的做法更硬，代价是模块拆分带来的 pom 维护与循环依赖调试成本。

一个值得学的抽象：`StreamEmitter` 定义在 agent 层（纯接口，default 空实现），`WebSocketStreamEmitter` 实现在 gateway 层——**业务节点只认识"往外发 chunk"这个动作，不认识 WebSocket**。

```266:280:lessons/lessons-05-WebSocket 流式问答 设计方案.md
public interface StreamEmitter {
    default void emitStart(Long sessionId, int seq) {}
    default void emit(Long sessionId, String chunk) {}
    default void emitEnd(Long sessionId, String fullQuestion) {}
}
```

### 1.2 面试状态机（会话级）

```
CREATED → PLANNING → IN_PROGRESS ⇄ PAUSED → EVALUATING → REPORTING → COMPLETED
                         └────────────────────→ CANCELLED / FAILED
```

关键设计：`/plan` 只生成计划、状态停在 `PLANNING`；只有 `/start` 才进 `IN_PROGRESS`。**"只有 CREATED 才允许生成计划"这一条状态守卫，天然防住了重复调用 AI 覆盖已有 plan_json**。

---

## 2. 核心机制拆解

### 2.1 双链路并行 + 灰度开关（本项目最该学的一条）

作者没有把旧的命令式 `InterviewWebSocketHandler`（53.6KB，全仓最大文件）删掉，而是让它和新的 Graph 链路共存，用一个配置开关切：

```39:45:lessons/lesson-06-两条链路一张图——LangGraph4j 状态图编排 设计方案.md
graph TD
    A["同一个 WebSocket 入口"] --> B["鉴权、参数校验、状态校验"]
    B --> C{"engine.isEnabled()"}
    C -->|false| D["旧 Handler 命令式推进"]
    C -->|true| E["WorkflowEngine Graph 推进"]
```

```28:31:interview-gateway/src/main/resources/application-local.yml
  engine:
    enabled: true  # LangGraph4j 灰度开关：false=旧命令式Handler，true=Engine编排
  supervisor:
    enabled: true  # F1-SupervisorAgent 灰度开关：false=纯透传（不参与决策），true=SUPERVISE节点参与决策
```

注意代码里的默认值是**保守的 false**（`@Value("${interview.engine.enabled:false}")`），只有 local profile 显式开成 true。这是"新链路默认不生效、按环境逐步放量"的标准做法。

作者自己给出的理由，值得原文引用：

> 面试流程不是一个普通的同步请求……如果一次性删掉旧链路、直接切到 Graph，一旦出现 checkpoint 恢复、重复提交、流式发送或状态同步问题，**就没有快速回退手段。**

两条链路共用 WebSocket 协议、DB 表、Agent 和 Kafka 评估链路，因此还能"用同一批业务测试对比两条链路行为是否一致"。

**代价也是真实的**：`ANSWER_ACK` 这条协议消息在旧链路发、在 Engine 链路不发，前端要兼容两种时序（lessons-05 明确承认了这一点）；旧 Handler 里还留着一份"生成下一题/判断结束"的逻辑，两份逻辑长期并存必然漂移（见 §4.3）。

### 2.2 LangGraph4j 状态图编排

实际拓扑（已核对代码，与 lesson-06 的图一致）：

```
START → plan → ask → answer → followUpDecision ─┬─(需追问且 count<3)→ followUp → answer（回环）
                                                 └─(否则/有错误)→ summary → supervise → endCheck
        endCheck ─┬─(seq<totalRounds 且未强制结束)→ ask（主循环）
                  └─(达上限/forceEnd/supervisor=END/lastError)→ END
```

三个设计判断值得记下来：

**(1) 节点只做动作，不决定下一步。** `AnswerNode` 只把回答转成一条 `QaPair` 追加进 `QA_HISTORY`，完全不知道后面是追问还是下一题：

```41:56:interview-agent/src/main/java/com/aims/agent/orchestration/node/AnswerNode.java
        QaPair qaPair =
                state.pendingFollowUp()
                        ? new QaPair(state.currentSeq(), state.currentQuestion(), answer,
                                state.followUpIndex(), state.followUpType())
                        : new QaPair(state.currentSeq(), state.currentQuestion(), answer);
        return Map.of(InterviewState.QA_HISTORY, qaPair);
```

**主问题回答与追问回答复用同一个 AnswerNode**，靠 State 里的 `pendingFollowUp / parentSeq / followUpIndex / followUpType` 区分——避免了两套近似代码。

**(2) 追问不占主问题序号。** 追问 `parentSeq=2` 而不是 `seq=3`，主问题数与追问数可分开统计。评估去重键因此要编码：

```87:90:interview-agent/src/main/java/com/aims/agent/orchestration/node/EvaluateNode.java
    /** 评估去重键：主问题用 seq；追问编码为 seq*100+followUpIndex（追问 ≤3 次，与主问题 seq 无碰撞）。 */
    private long evalKey(QaPair qa) {
        return qa.followUpIndex() == null ? qa.seq() : qa.seq() * 100L + qa.followUpIndex();
    }
```

**(3) EndCheckNode 是个空节点，故意的。** `apply()` 只打日志返回 `Map.of()`，存在的唯一价值是"在流程图上留一个显式的决策边界"，避免把结束判断塞进 summary 让摘要节点职责变重。这是一种"用一个空节点换架构可读性"的取舍，见仁见智，但理由是清楚的。

**(4) 条件边路由函数是 package-private 的普通方法**（`routeAfterFollowUpDecision` / `routeAfterEndCheck`），可以脱离 Graph 单独单测——`InterviewGraphFactoryTest` 就是这么测的。这一点非常实用：**把"路由决策"从"节点执行"里剥出来后，分支逻辑变成了纯函数**。

结束路由的判定优先级（代码为准）：

```298:328:interview-agent/src/main/java/com/aims/agent/orchestration/graph/InterviewGraphFactory.java
    String routeAfterEndCheck(InterviewState state) throws Exception {
        if (state.lastError() != null) return END;
        if (state.forceEnd()) return END;
        if (state.totalRounds() <= 0) { log.error("totalRounds<=0 异常，按配置错误终止 ..."); return END; }
        if (state.currentSeq() >= state.totalRounds()) return END;
        if (state.supervisorDecision() != null
                && state.supervisorDecision().action() == SupervisorAction.END) { ... return END; }
        return NodeNames.ASK;
    }
```

`totalRounds<=0` 那条防御很老练：它防的是"checkpoint 残留 state 下 `currentSeq>=totalRounds` 恒真导致 0 题面试直接进评估"。这类"异常数据下的恒真条件"是状态机最容易出的 bug。

### 2.3 InterviewState：Channel 语义 = 状态更新语义显式化

`InterviewState extends AgentState`，全部字段用 `Map<String, Channel<?>> SCHEMA` 声明更新语义：

```126:148:interview-agent/src/main/java/com/aims/agent/orchestration/state/InterviewState.java
                    // 对话历史 — Append
                    Map.entry(QA_HISTORY, Channels.appender(ArrayList::new)),
                    Map.entry(QUESTIONS_ASKED, Channels.appender(ArrayList::new)),

                    // 当前轮次 — Replace
                    Map.entry(CURRENT_ROUND_ID, Channels.base((old, v) -> v)),
                    Map.entry(CURRENT_SEQ, Channels.base(() -> 0)),
                    ...
                    // 评估结果 — Append
                    Map.entry(ROUND_EVALUATIONS, Channels.appender(ArrayList::new)),
```

价值在于：节点只返回"本次的增量"，"增量怎么并进全局"由 Channel 统一决定。`Channels.appender` 让 `return Map.of(QA_HISTORY, qaPair)` 自动追加而不是覆盖——**这消除了一整类"忘记先读旧 list 再 add"的 bug**。

一个小细节暴露了踩坑史：可为 null 的字段一律写成 `Channels.base((old, v) -> v)` 而不是 `Channels.base(() -> null)`，注释说明是为了避开 `initialDataFromSchema` 里 `Collectors.toMap` 的 NPE。

### 2.4 Checkpoint 断线恢复：`interruptBefore(ANSWER)` + Redis

这是全项目最精巧的一环。图编译时声明"进入 ANSWER 之前中断"：

```244:252:interview-agent/src/main/java/com/aims/agent/orchestration/graph/InterviewGraphFactory.java
    public CompiledGraph<InterviewState> compileWithInterruptBeforeAnswer(
            BaseCheckpointSaver checkpointer) throws Exception {
        CompileConfig.Builder builder =
                CompileConfig.builder().recursionLimit(100).interruptBefore(NodeNames.ANSWER);
        if (checkpointer != null) builder.checkpointSaver(checkpointer);
        return buildGraph().compile(builder.build());
    }
```

于是"等待候选人回答"不再是"方法返回、下条消息重新推断进度"，而是**图真的停在那里**，位置写进 Redis checkpoint。提交回答时：

```230:233:interview-gateway/src/main/java/com/aims/gateway/orchestration/InterviewWorkflowEngine.java
        // 从 checkpoint 断点恢复：answer 经 resume 更新数据合并进 checkpoint state，由 ANSWER 节点消费。
        // 不可用 invoke(Map)——那是 GraphArgs 语义，会从 START 重跑并丢失回答。
        compiledGraph.invoke(
                GraphInput.resume(Map.of(InterviewState.CURRENT_ANSWER, answer)), config);
```

`GraphInput.resume(map)` vs `invoke(map, config)` 的区别，作者用 12 行 javadoc 记录了这个坑（后者会从 START 重跑，导致 plan/ask 重跑且注入的回答被 QuestionNode 清空）。**这类"框架语义踩坑"写进 javadoc 而不是提交信息里，是很好的知识沉淀方式。**

还有三处"判断是否结束"的讲究：

```382:397:interview-gateway/src/main/java/com/aims/gateway/orchestration/InterviewWorkflowEngine.java
    /**
     * 面试是否已结束：checkpoint 的 nextNodeId 为 END（图真正走到 END）。
     * <p>不能用 {@code currentSeq >= totalRounds} 判定——QuestionNode 生成下一题时会把 CURRENT_SEQ 提前递增 ...
     * 导致"最后一题已生成、尚未回答"时误判结束并提前触发评估。
     */
```

以及重连恢复的三分支容错（`resumeInterview`）：checkpoint 不存在 → `rebuildFromDb` 重建并重跑；checkpoint 已 END → 幂等触发评估；正常暂停 → 让 Handler 从 DB 补发当前待答题。**"Redis 可能过期，所以必须能从 DB 重建 State"这一条是长会话系统的必备兜底。**

`startInterview` 的幂等同理：若已有 checkpoint 就不重跑，只补偿上次失败的落库。

**Checkpoint 序列化的取舍值得单独说。** 作者明确拒绝了 Jackson Default Typing，理由写了 3 条（record/enum 是 final 不会写 `@class`；`As.PROPERTY` 无法给标量/数组加类型标识导致 `Long` 往返变 `Integer` 抛 CCE；`@class` 全限定名有反序列化 gadget 风险），改用"普通 ObjectMapper + Schema 感知的类型登记表"手工归一化：

```99:141:interview-agent/src/main/java/com/aims/agent/orchestration/checkpoint/CheckpointSerializer.java
    private static final Map<String, Class<? extends Enum<?>>> ENUM_TYPES = ...
    private static final Map<String, Class<?>> RECORD_TYPES = ...
    private static final Map<String, Class<?>> LONG_TYPES = ...
    private static final Map<String, Class<?>> LIST_RECORD_ELEMENTS = ...
```

安全性上这个选择是对的（消掉了整个反序列化攻击面）；但它把类型信息从"数据自描述"改成了"代码里的登记表"，作者自己在类注释里承认：新增 record/enum 字段必须来这里补齐，否则该字段会静默退化成 `LinkedHashMap`。`CONFLICT_DETAILS_BY_ROUND` 的归一化方法上就留着一条"否则 EvaluateNode/ReportNode 访问 conflictField() 会抛 ClassCastException"的注释——**这个坑已经踩过一次了。**

### 2.5 三层容错：节点重试 / 模型重试 / 模型降级

| 层 | 组件 | 行为 |
|---|---|---|
| 节点级 | `FaultTolerantNode` | 指数退避重试，**重试耗尽不抛异常**，把错误写进 `LAST_ERROR`，让条件边决定路由 |
| 调用级 | `RetryAdvisor`（Spring AI Advisor，order 300） | 同一模型原地重试：429/5xx/IOException/TransientAiException 可重试；阻塞用 `Thread.sleep` 退避，流式用 `Retry.backoff` |
| 模型级 | `ModelRouter` | 重试耗尽后换 fallback 模型；`AiOutputParseException`（结构化解析失败）**显式不降级**，直接抛 |

节点重试参数是按节点"贵不贵、能不能重试"分别给的，这个粒度设计很实用：

```160:166:interview-agent/src/main/java/com/aims/agent/orchestration/graph/InterviewGraphFactory.java
        graph.addNode(NodeNames.PLAN, async(wrap(planNode, 2, 1000)));
        graph.addNode(NodeNames.ASK, async(wrap(questionNode, 2, 2000)));
        graph.addNode(NodeNames.ANSWER, async(wrap(answerNode, 1, 0)));          // 纯内存，不重试
        graph.addNode(NodeNames.FOLLOW_UP_DECISION, async(wrap(followUpDecisionNode, 3, 500)));
        graph.addNode(NodeNames.FOLLOW_UP, async(wrap(followUpNode, 2, 2000)));
        graph.addNode(NodeNames.SUMMARY, async(wrap(summaryNode, 2, 1000)));
        graph.addNode(NodeNames.END_CHECK, async(wrap(endCheckNode, 1, 0)));     // 空节点，不重试
```

"重试耗尽不抛异常、写 State 让路由处理"是很干净的容错哲学：**异常不再穿透框架，而是变成一份数据**。但它对有副作用的节点是危险的（见 §4.1）。

### 2.6 多模型档位路由与配置热更新

四档位 `FLAGSHIP / STANDARD / ECONOMY / EMBEDDING`，按"任务对质量的敏感度"分配：

| 档位 | 默认模型 | 用途 | fallback |
|---|---|---|---|
| FLAGSHIP | qwen-max | 面试主对话、追问问题**生成** | → deepseek-chat |
| STANDARD | deepseek-chat | 追问**决策**、评分、计划、报告 | 无 |
| ECONOMY | qwen-turbo | 摘要、简历解析 | 无 |
| EMBEDDING | text-embedding-v4 | 2048 维向量化 | 无 |

注意 `DefaultFollowUpAgent` 里"决策用 STANDARD、生成用 FLAGSHIP"的分裂——**同一个 Agent 内部按子任务再分档**，这个粒度比"一个 Agent 绑一个模型"更精细。

热更新做法：`synchronized refresh()` 里重建 `apis/handles` 两张不可变 Map，然后整体替换 `volatile` 字段。**旧请求继续用旧句柄跑完，新请求拿新句柄**——靠"句柄不可变 + 引用原子替换"实现无锁切换，比加读写锁干净。

DB 覆盖 yml 的合并规则也有讲究：DB 字段非 null 才覆盖；**空串语义 = 清除覆盖回退 yml**；档位级 override 通过动态创建 `<TIER>@override` 虚拟 provider 实现（不污染共享 provider），回显时过滤掉。API Key 用 AES-256-GCM（`v1:<b64 iv>:<b64 ct+tag>`），密钥优先取 `AIMS_CONFIG_ENCRYPT_KEY`，退化为 `SHA-256(JWT_SECRET)`，**都没有则 warn 后明文存储**（这条兜底在生产上是危险的，好在有日志）。

### 2.7 RAG 混合检索

**存储层选型判断（最值得抄的一条技术决策）**：

> pgvector 的 HNSW 索引对 `vector` 类型最多支持 2000 维，对 `halfvec` 最多 4000 维。text-embedding-v4 是 2048 维——继续用 `vector` 就**建不了 HNSW**，只能全表顺序扫。

于是迁移脚本把三张表的 embedding 列统一改成 `halfvec(2048)` 并建 `hnsw (embedding halfvec_cosine_ops)`。副作用是存储减半（8KB→4KB/条），代价是 float16 精度——作者的论证是"检索关心相对排序，余弦相似度对小数点后第 4 位的扰动稳定"，这个论证站得住。

**检索层**：一条 SQL 里同时算向量分与关键词分，`最终分 = 向量分×0.7 + 关键词分×0.3`；关键词用 `pg_trgm` 加速的 `ILIKE`，按字段分级给分（题库 content 1.0 / topic 0.9 / category 0.8；简历 工作经历 1.0 / 项目 0.95 / raw_text 0.9 / skills 0.85 / 姓名 0.8）。DB 先返 `topK×3` 候选，**Java 侧再重排截断**，避免数据库预截断漏召回。

**缓存与降级**：结果缓存（TTL 60s）+ 查询向量缓存（TTL 30min，key=`rag:embed:{md5(query)}`）；Redis 异常自动降级直查；混合检索失败 → 退化纯向量 → 再失败抛 `RAG_SEARCH_FAILED`。

**写入管道（简历侧）的两个亮点：**

1. **双状态机 + 原子抢占**。`parse_status` 与 `embedding_status` 各自独立流转，`FAILED` 不是死状态可被重新抢占；并发重复触发不加锁，用条件 UPDATE 抢：
   ```sql
   UPDATE resume SET parse_status='PROCESSING', parse_attempts=parse_attempts+1
   WHERE id=#{id} AND parse_status IN ('PENDING','FAILED')
   ```
   只有影响行数=1 的线程继续干活。`claimEmbedding` 更严：要求 `parse_status='PARSED'`。
2. **用 LLM 结构化解析替代文档切片**。embed 的输入不是简历原文，而是 LLM 提炼后拼的结构化文本（姓名/职位/年限/技能/工作经历/项目经历）——"一份简历一个向量就够了"，天然绕开 chunking/overlap/父子块那套复杂度。**这是把 RAG 的复杂度从"检索侧"前移到"入库侧"的思路，很值得借鉴。**
3. 解析结果**双写**：`parsed_json`（给前端展示/人工编辑）+ `work_experience`/`project_experience` 两张明细表（给实体级交叉验证用），`syncFromParsed` 先删后插保证幂等。内容一变，JSON/经历表/向量三处同步刷新（`invalidateEmbedding`）。

### 2.8 追问决策 + 简历真实性校验（差异化最强的功能）

追问决策 prompt 的骨架：4 个评估维度（完整性/具体性/准确性/相关性）+ 4 个 action（NEXT/CLARIFY/DEEPEN/REDIRECT）+ **4 条可操作启发式**：

```28:38:interview-agent/src/main/java/com/aims/agent/FollowUpPromptBuilder.java
注意：
- 如果候选人回答过于简短（<50字）或纯泛化表述，应追问
- 如果回答与简历存在明显矛盾，应追问（CLARIFY）
- 如果回答提及具体技术但未展开，应追问（DEEPEN）
- 如果回答完整且有具体细节，应进入下一题（NEXT）
- 追问问题应基于预设的追问方向（followUpHints），不脱离面试主线

工具（简历交叉验证）：
- 如需验证回答与简历是否一致 ... 可调用 resumeCrossCheck 工具查证。
- 工具返回的 score ... score < 0.5 表示回答内容在简历中缺乏对应支持 ... 应倾向 CLARIFY 追问；score >= 0.7 表示与简历一致，可信任回答。
- 工具结果仅作证据参考，最终判断仍由你做出；工具不可用（无结果）时按常规判断，不要臆造证据。
```

三点很专业：**把工具返回的连续分数翻译成明确的决策阈值**（0.5/0.7）；**明确"工具结果只是证据，裁决权在模型"**；**明确"工具不可用时不要臆造证据"**（反幻觉）。

还有一条现场踩出来的 JSON 约束：

```40:44:interview-agent/src/main/java/com/aims/agent/FollowUpPromptBuilder.java
JSON 输出约束：
- 所有字符串值内不得包含未转义的双引号 "；如需在文本中引用内容，请用单引号或中文引号『』。
```

配套的四级 JSON 容错：`extractJson`（截取首 `{` 到末 `}`）→ Jackson 解析 → 失败则**正则宽松提取 `action`**（保住"追问 vs 不追问"这个关键决策）→ 仍失败默认不追问。降级方向始终是"保守不追问"，不会因为解析失败卡住面试。

**简历交叉验证的三级探测**（`probeConflicts`）是成本控制的教科书案例：

```83:107:interview-agent/src/main/java/com/aims/agent/DefaultFollowUpAgent.java
            // 一级：正则低成本提名；无候选 → 零 AI 成本直接返回
            List<...ResumeMention> regexMentions = regexMentionExtractor.extract(context.answer());
            if (regexMentions == null || regexMentions.isEmpty()) return List.of();
            // 二级：AI 语义判定，过滤非真实体；null（AI 不可用）→ 回退正则提名
            List<...ResumeMention> mentions = aiMentionExtractor.extract(context.answer());
            if (mentions == null) mentions = regexMentions;
            ...
            // 三级：每个真实体作为 companyHint 走 DB 实体比对 + 时间线冲突
```

正则先做"零成本提名"，绝大多数轮次的回答里没有公司/项目名 → 直接返回，**不花任何 AI 调用**；只有正则命中了才请 AI 判定是不是真实体（注释里的例子很生动：过滤掉「CLH 等待队列」这种像项目名但不是的），最后才查 DB 比对。这是"廉价过滤器前置 + 昂贵判定后置"的标准漏斗，我们项目在"简历证据检索"上完全可以照抄这个形状。

矛盾点最终按轮次写进 State，一路带到评估与报告：

```69:78:interview-agent/src/main/java/com/aims/agent/orchestration/node/FollowUpDecisionNode.java
        if (!decision.conflictDetails().isEmpty()) {
            String key = state.followUpIndex() != null
                            ? state.currentSeq() + ":" + state.followUpIndex()
                            : String.valueOf(state.currentSeq());
            Map<String, List<ConflictDetail>> merged = new LinkedHashMap<>(state.conflictDetailsByRound());
            merged.put(key, decision.conflictDetails());
            updates.put(InterviewState.CONFLICT_DETAILS_BY_ROUND, merged);
        }
```

矛盾点在 prompt 里的呈现也做了人性化格式化（不是丢原始字段）：

```84:97:interview-agent/src/main/java/com/aims/agent/FollowUpPromptBuilder.java
        return switch (c.conflictField()) {
            case "company" -> "公司矛盾：回答提到「" + c.actual() + "」，简历未提及该公司";
            case "project" -> "项目矛盾：回答提到「" + c.actual() + "」，简历未提及该项目";
            case "period" -> "时间线矛盾：回答称 " + c.actual() + "，简历为 " + c.expected();
            ...
```

### 2.9 五维评估与报告

```13:27:interview-agent/src/main/java/com/aims/agent/EvaluationPromptBuilder.java
            评分维度与权重：
            1. PROFESSIONAL（专业能力 40%）：知识点准确性、深度、实践经验真实性
            2. LOGIC（逻辑思维 20%）：条理、结构化表达、问题拆解能力
            3. COMMUNICATION（沟通表达 15%）：清晰度、简洁性、专业术语运用
            4. JOB_MATCH（岗位匹配 15%）：与 JD 要求的契合度
            5. POTENTIAL（学习与潜力 10%）：对未知问题的态度与推理过程
            要求：
            1. 每维度评分 1-5 分（5 分优秀，1 分差）
            2. 每维度必须提供评语，说明评分理由
            3. 每维度必须引用候选人回答中的原话作为证据
            4. 基于事实评分，不主观臆断
```

**"每维度必须引用原话作为证据（evidenceQuote）"是最值得抄的一条**——它把打分从"感觉"逼回"可追溯的文本证据"，也让前端能把评分和原话并排展示。我们的五维诊断目前没有强制 evidence 引用。

报告侧：`summary`（200–500 字，需说明简历矛盾点影响）+ 维度聚合 + `recommendation` 四级枚举，且给了明确阈值：`STRONG_RECOMMEND ≥4.0 / RECOMMEND 3.5–4.0 / NEUTRAL 2.5–3.5 / NOT_RECOMMEND <2.5`。

评估链路走 Kafka：面试结束 → `tryTransitionTo(EVALUATING, from IN_PROGRESS|PAUSED)` 原子转移保证只触发一次 → 发 Kafka → `EvaluationConsumer` 逐轮评分 → `ReportConsumer` 生成报告置 `COMPLETED` → 前端 2s 轮询感知。触发前还有一层竞态防御：

```406:411:interview-gateway/src/main/java/com/aims/gateway/orchestration/InterviewWorkflowEngine.java
        // FE.10 P6 竞态防御：resume 完成后若会话已断开（无活跃 WS 连接），不触发评估，
        // 保持 PAUSED 由重连时 resumeInterview 恢复，避免断线动作被评估覆盖
        if (sessionManager != null && !sessionManager.hasActiveSession(sessionId)) { ... return; }
```

### 2.10 WebSocket 工程细节（一堆能直接抄的经验）

| 问题 | 解法 |
|---|---|
| 握手鉴权 | `beforeHandshake` 阶段校验 JWT/GuestToken + sessionId 绑定 + accessMode，失败直接拒绝 Upgrade（不进 Handler） |
| 单会话单连接 | Redis `interview:lock:{sessionId}`，TTL 60s，前端 30s 心跳续租（**留一次容错空间**）；同候选人刷新页面允许抢占 |
| 流式边界 | 三段式 `QUESTION_START / QUESTION_CHUNK×N / QUESTION_END`，roundId 只在 END 阶段回传（此前 DB 轮次还没创建） |
| 跨线程传 sessionId | **Reactor Context 而非 ThreadLocal**（chunk 在 reactor-netty 线程发出，ThreadLocal 拿不到）——`contextWrite` 写、`transformDeferredContextual` 读 |
| 并发发送 | `synchronized (session)` 单连接内串行发送，不同连接仍并行（`WebSocketSession` 非线程安全） |
| 大消息 1009 | **双层防御**：业务限回答 ≤10000 字符 + 容器 buffer 提到 16MB。作者明确解释了为什么不能只做一层 |
| 断线重连 | 前端指数退避（1/2/4/8/16s，上限次数）；主动退出置 `shouldConnectRef=false` 不重连 |
| 流式期间 Markdown | **两阶段渲染**：流式期只渲染纯文本 + 打字光标，END 后才跑 react-markdown（chunk 边界不对齐 Markdown 语法会闪动/DOM 重建） |
| 结束回执重复 | WS 实时 + REST 轮询兜底双通道，zustand 按 **业务字段四元组**（role/status/finishedBy/finishReason）去重，而非随机消息 ID |

其中"Reactor Context 而非 ThreadLocal"和"两阶段渲染"两条，是我们的语音/流式链路可以直接受益的。

### 2.11 防作弊（前端 WASM，帧不出浏览器）

- 眼神检测：MediaPipe `@mediapipe/tasks-vision` FaceLandmarker，跑在 **Web Worker** 里；用 `new VideoFrame()` + `postMessage(..., [frame])` **转移所有权**给 worker，worker 只回分类结果并 `frame.close()`——**原始视频帧永不出浏览器**，隐私友好。
- 采样 5fps（200ms）；阈值 `YAW_RATIO 0.2`（鼻尖相对脸颊中线偏移/脸宽）、`IRIS_DEVIATION 0.3`；**需持续 3s 才记一次事件**（防瞬时误判），有 `inflight` 背压跳过未推理完的帧。
- 切屏检测：`visibilitychange`/`blur`/`focus`，10s 批量上报，`pagehide` 用 `fetch(keepalive:true)` 兜底。
- 后端 `interview_proctor_event` 表按会话聚合；报告页 `ProctorFocusCard` 四格展示，并**明确标注"与评估打分解耦，仅作参考，不计分"**。

最后这条定性很克实：**把不可靠的行为信号排除在评分之外，只作参考**。这与我们 CHARTER"诚实披露局限"的精神一致。

### 2.12 可观测性

`GraphTraceAspect`（AOP 埋节点耗时）+ `GraphMetricsRegistry`（`aims.graph.node.retry` / `aims.graph.checkpoint.restore` / execution outcome / 当前轮次 Gauge）+ `TokenMeterAdvisor`（prompt/completion token、延迟、**按价目表估算成本**、按图节点归集 token）。

能回答"哪个节点最慢、哪个流程最贵、哪个模型最爱降级"——这是 LLM 应用运维的核心问题，我们目前只有日志。

---

## 3. 值得借鉴的工程判断（浓缩清单）

1. **灰度双链路**：重写核心编排时，新旧并存 + 配置开关 + 默认关，比"大爆炸替换"安全得多。
2. **流程位置也是状态**：DB 存"业务事实"，checkpoint 存"程序计数器"。旧链路必须从"最后一轮有没有回答"反推下一步，这种反推随分支增加会指数级变脆。
3. **节点不决定下一步**：动作与路由分离，路由变成可单测的纯函数。
4. **重试耗尽不抛异常，写进 State**：异常降级为数据，由路由统一处理（但要求节点无副作用，见 §4.1）。
5. **廉价过滤器前置**：正则提名 → AI 判定 → DB 比对，多数情况零 AI 成本。
6. **把工具分数翻译成 prompt 里的决策阈值**（<0.5 倾向追问 / ≥0.7 可信任），而不是让模型自己领会。
7. **评分必须引用原话**（evidenceQuote），把主观打分锚到文本证据上。
8. **JSON 四级容错 + 保守降级方向**（解析失败 → 不追问，而不是卡住）。
9. **入库侧提炼替代检索侧切片**：LLM 结构化后一份简历一个向量。
10. **条件 UPDATE 原子抢占**替代分布式锁做"防重复处理"。
11. **halfvec 换 HNSW 可用性**：向量维度 >2000 时的必要选择。
12. **心跳 30s / 锁 TTL 60s**：留一次丢包容错窗口。
13. **两阶段 Markdown 渲染**：流式期纯文本，结束后再解析。
14. **业务字段去重而非消息 ID 去重**：兼容"实时通道 + 轮询兜底"双来源。
15. **框架语义踩坑写进 javadoc**（`GraphInput.resume` vs `invoke`），知识留在代码旁边。

---

## 4. 值得警惕的问题（诚实指出）

### 4.1 QuestionNode 重试会重复推流（我认为是最实质的隐患）

`ASK` 节点被 `wrap(questionNode, 2, 2000)` 包成可重试，而 `QuestionNode.apply()` 的执行序列是：
`emitStart` → 逐 chunk `emit`（已经发给前端了）→ `blockLast()` → `emitEnd`。

如果流在中途失败（模型断流、网络抖动），前端已经收到了 `QUESTION_START` + 若干 `QUESTION_CHUNK`；重试第二次会**再发一次 START 和一整套 chunk**。前端 `appendChunk` 是"追加到最后一个流式消息"，结果就是半截问题 + 完整问题拼在一个气泡里。

同样的模式在 `FollowUpNode` 也存在。**根因是"重试装饰器"被套在了"有外部副作用"的节点上。** 正确做法是要么让重试只包裹纯计算部分（先累积完再统一 emit，牺牲首字延迟），要么给 emit 加"本轮已发过 START 则先发一个 RESET"的协议。

### 4.2 SuperviseNode 的 avgScore 恒为 null（设计漂移的直接证据）

`SuperviseNode` 组装 `SupervisorContext` 时传了 `avgScore(state)`，取自 `state.roundEvaluations()`。但——**`ROUND_EVALUATIONS` 只由 `EvaluateNode` 写入，而 `EvaluateNode` 已经从图里移除了**（评估改走 Kafka，面试结束后才跑）：

```39:40:interview-agent/src/main/java/com/aims/agent/orchestration/graph/InterviewGraphFactory.java
 * <p>评估（evaluate）与报告（report）已移至 Kafka 链路（面试结束后由 {@code EvaluationConsumer}/{@code ReportConsumer} 从
 * DB 统一评估并落库），故不注册在图内。
```

所以面试过程中 `roundEvaluations` 恒为空列表 → `avgScore` 恒返回 null → 总指挥拿不到"候选人答得好不好"这个维度，只能靠耗时/题数做节奏判断。功能没坏，但**"评分驱动节奏"这个设计意图已经悄悄失效了**，代码里没有任何地方标注这件事。这是"把子流程搬走后忘了回头看谁在依赖它"的典型。

### 4.3 双链路的长期成本正在显现

`EvaluateNode` / `ReportNode` 仍留在代码库（有 @Component 注解、有测试），但已不在图上；Kafka Consumer 里另有一套评估实现。**同一件事两份实现**，prompt 或去重规则改一处漏一处的风险很高。旧 `InterviewWebSocketHandler` 53.6KB 里那套"判断追问/判断结束/生成下一题"同理。

灰度期该有的东西是"到期删除计划"，README 和 lessons 里都没看到。

### 4.4 混合检索的关键词通道在主链路上实际是空转

关键词分是把**整个 query 当一个 ILIKE 模式**：

```79:84:interview-infra/src/main/java/com/aims/infra/persistence/service/impl/ResumeRagServiceImpl.java
                    + "CASE WHEN COALESCE(w.work_text, '') ILIKE '%' || ? || '%' THEN 1.0 "
                    + "WHEN COALESCE(p.project_text, '') ILIKE '%' || ? || '%' THEN 0.95 "
                    ...
```

而主链路两处调用传的 query 是**岗位 JD 全文**：

```321:322:interview-gateway/src/main/java/com/aims/gateway/controller/interview/InterviewController.java
                    questionRagService.search(position.getJdText(), RAG_TOP_K).results();
            String ragQuestions = formatRagQuestions(ragResults);
```

一整篇 JD 原文作为子串出现在某道题的 content 里，概率约等于零。也就是说：**面试计划生成和面试中检索这两条主路径上，keywordScore 恒为 0，"混合检索"实际退化为"向量分 × 0.7"（排序等价于纯向量检索）**。真正让关键词通道生效的只有 `/api/v1/rag` 调试接口（短查询词）。lesson-03 自己也写了"把整个 query 当成一个关键词做 ILIKE"，但没意识到这个后果。

修法不难（分词后多关键词 OR 计分，或改用 PG 全文检索 `to_tsvector`/`websearch_to_tsquery` 做 BM25 通道），但现状下"混合检索"这个卖点是打折的。

### 4.5 其他

- **ModelHandle 的 Semaphore 并发闸口未接线**：`ModelHandleFactory` 给每个 provider 建了 Semaphore，但 `ModelRouter` 从未 `acquire/release`，注释写明"P1 仅预留"。README 的"provider 并发闸口"实际未生效。
- **防作弊上报接口无限流、无条数上限**：`POST /access/interviews/{id}/proctor/events` 只有 GUEST 角色 + 同会话校验，恶意候选端可无限灌事件（查询侧有 LIMIT 200，写入侧没有）。
- **API Key 加密密钥缺失时明文落库**（仅 warn），生产上应该 fail-fast。
- **`CONFLICT_DETAILS_BY_ROUND` 用 Replace 语义 + 节点内手动 merge**（读旧 Map → put → 写回），绕过了 Channel 的累积语义。单线程图执行下正确，但破坏了"更新语义集中在 SCHEMA 声明"这条自定规则。
- **`evalKey = seq*100 + followUpIndex`** 是脆弱魔数：注释论证"追问≤3 与主问题 seq 无碰撞"成立的前提是面试题数 <101，属于隐式约束。
- **人设只作用于提问，不作用于评估**：压力面下候选人的表现不会被差异化校准（同一份回答在温和面/压力面下应该给不同分吗？项目没有回答这个问题）。
- **lessons 与代码有小幅不一致**：lesson-06 与类注释都说"7 节点 2 条件边"，实际注入 SuperviseNode 后是 8 节点；README mindmap 仍把"面试评估与报告"画在 AI Agent 层（已移到 Kafka）。文档滞后于代码。

---

## 5. 与本项目（AI 模拟面试官 v6.2）的对比

| 维度 | Gua-AI-interview | 本项目 |
|---|---|---|
| 语言/框架 | Java 21 / Spring Boot / Spring AI / LangGraph4j | Python 3.12 / FastAPI |
| 存储 | PG+pgvector / Redis / Kafka / MinIO | SQLite（interview.db / market.db） |
| 面试编排 | **显式状态图 + Redis Checkpoint** | 命令式 `InterviewSession` 对象（`rounds` / `current_round` / `current_question_idx` / `advance_round` / `check_round_quality`） |
| 流程恢复 | checkpoint 恢复执行位置，可从 DB 重建 | 内存态 `active_sessions`，进程重启即丢 |
| 追问 | LLM 决策（4 action）+ 每题上限 3 + 三级简历交叉验证 | `should_follow_up`（分数阈值）+ `generate_follow_up`（预设/弱维度） |
| 评估 | 五维（专业40/逻辑20/沟通15/匹配15/潜力10），1–5 分，**强制 evidenceQuote** | 五维（STAR/量化/逻辑/岗位相关/专业深度），`dimension_weights` 动态权重 |
| 评估时机 | 面试后 Kafka 异步逐轮 | 面试中同步逐题（双 Agent：诊断+改写） |
| 模型路由 | 四档位 + fallback + DB 热更新 + 成本计量 | 多 provider + `AI_PROVIDER=auto` 探测 + v4.3 fallback |
| 语音 | 火山 TTS（单向播报） | MiMo TTS/ASR 双向 + 浏览器降级 |
| 独有 | 防作弊、简历真实性校验、多模型成本指标、Kafka 异步、Graph 可观测性 | **职业规划时间轴**、市场数据采集与分析、Gap 分析、薄弱点跨轮累计、会话中多模式切换 |
| 测试 | 361 @Test（含 Live IT 分层、JaCoCo 门槛） | 559 用例（偏纯函数，CHARTER 已披露"验证工程正确性而非诊断有效性"） |

**结论**：它在"面试过程的工程可控性/可恢复性/可观测性"上明显强于我们；我们在"诊断深度 + 职业规划 + 市场数据"这条产品命题上是它没有的（它是招聘方工具，我们是候选人成长工具）。**两者不是同一个产品，但它的编排工程是我们的短板方向。**

我们目前正处在它 lesson-06 描述的"旧 Handler 命令式链路"阶段，而且面临的正是它列举的那几个症状：

> - 一条业务流程被分散到多个入口（我们的 `handle_answer` / `stream_answer` / `handle_follow_up_answer` / `switch_mode` / `advance_round`）
> - 没有显式的"当前执行节点"，只能从业务结果反推
> - 传输层（WebSocket 路由）承担了流程编排职责
> - 分支相互组合而非线性增加（自我介绍 / 追问 / 补题 / 恢复 / 模式切换 / 收尾强控）

---

## 6. 可迁移清单（按性价比排序）

> ⚠️ 依 CHARTER"范围纪律"，以下均为**建议**，需你明确批准后才实施；标注 ★ 的是我认为投入产出比最高的。

### P0：低成本、纯增益（不动架构）

1. **★ 评估强制 evidence 引用**（改 `diagnosis_engine.py` 的 prompt + schema）
   每个维度加一个 `evidence_quote` 字段，要求引用候选人回答原话。收益：诊断可追溯、前端可并排展示、抑制凭感觉打分。代价：prompt 微调 + schema 加字段 + 前端展示，约半天。

2. **★ 追问决策 JSON 的宽松兜底**（改 `session.py` / `question_gen.py`）
   现在若 LLM 返回带裸引号的 JSON，解析失败会走异常路径。抄它的四级容错：截取首尾大括号 → 标准解析 → **正则只提关键字段**（是否追问/追问类型）→ 默认保守不追问。收益：把"解析失败"从"功能丢失"降级为"保守降级"。

3. **★ 简历证据检索加"廉价过滤器前置"**（改 `resume_retriever.py`）
   当前每次回答都做检索。抄它的漏斗：先正则提名（公司/项目/技术名候选），**无候选直接跳过检索**，有候选再走向量/关键词检索。收益：省掉大量无效检索与 token；本项目正在改 `resume_retriever.py`，时机正好。

4. **两阶段 Markdown 渲染**（改前端流式渲染）
   流式期只渲染 `white-space: pre-wrap` 纯文本 + 光标，收到结束信号后才跑 Markdown 解析。收益：消除流式期闪动与 DOM 重建。

5. **结束回执按业务字段去重**（改前端 store）
   若我们也有"WS 实时 + 轮询兜底"双通道，按 `(角色, 状态, 结束人, 原因)` 四元组去重，而不是消息 ID。

6. **提问 prompt 补一条"评分职责隔离"**
   它的面试官 prompt 明确写"不要评分"。我们的出题/追问 prompt 如果没有这条，模型可能边问边评，污染后续诊断。

### P1：中等成本、结构性收益（需设计）

7. **★ 引入"流程位置"的显式持久化（不必引入图框架）**
   最小可行版本：在 `InterviewSession` 上增加一个显式的 `flow_state` 字段（枚举：`WAITING_ANSWER / DECIDING_FOLLOW_UP / GENERATING_QUESTION / CLOSING / FINISHED`）+ 每次变更落 DB。收益：不再从"最后一题有没有答"反推进度；进程重启/断线后可精确恢复；`switch_mode`、补题、收尾强控这些分支的组合爆炸有了统一落点。**这是它的核心思想里最能低成本移植的部分——要的是"显式程序计数器"，不是 LangGraph。**

8. **路由决策抽成纯函数**
   把 `check_round_quality` / `should_add_extra_question` / `should_follow_up` / `is_closing_round` 里"决定下一步是什么"的部分抽成不依赖 DB/WS 的纯函数 `decide_next(state) -> NextAction`。收益：这些分支终于能被单测精确覆盖（对应 CHARTER 已披露的"测试偏纯函数但不覆盖流程决策"）。

9. **追问决策补"回答—简历一致性"证据通道**
   我们已有 `resume_retriever`；可以把检索到的匹配度分数按它的做法翻译成 prompt 阈值（`<0.5 缺乏支持 → 倾向澄清追问`），并把矛盾点带进诊断/报告。收益：从"答得好不好"扩展到"说的是不是真的"，是差异化能力。

10. **节点级重试装饰器（但只包纯计算）**
    给 LLM 调用点加统一的指数退避重试 + "重试耗尽写 last_error 而非抛异常"。**必须避开它 §4.1 的坑：有推流副作用的地方不能整体重试。**

### P2：高成本或与定位不符（建议只记录、暂不做）

11. **halfvec + HNSW / pgvector**：我们是 SQLite，`knowledge_store` 规模下没有必要；但"向量维度 >2000 时 pgvector 必须用 halfvec 才能建 HNSW"这条知识值得记在文档里，将来若迁 PG 直接用。
12. **Kafka 异步评估**：我们的诊断是"面试中即时反馈"，异步化会破坏核心体验，不宜迁移。
13. **防作弊（切屏/眼神）**：我们的定位是"候选人自我提升"，监考没有意义（它是招聘方视角才需要）。**这是产品定位差异，不是能力差距，不必对标。**
14. **LangGraph（Python 版）重写编排**：收益真实但成本高，且会引入一个重量级依赖 + 新的踩坑面（它的 `GraphInput.resume` 坑、序列化类型登记表维护都是明证）。在课程项目规模下，P1-7 的"显式 flow_state"能拿到 70% 的收益、成本不到 10%。
15. **配置热更新 + AES-GCM 加密的 Key 入库**：我们用 `.env`，够用；且它"密钥缺失时明文落库"的兜底不该抄。

---

## 7. 一句话总结

**Gua-AI-interview 的价值不在"它是一个 AI 面试项目"，而在"它把 AI 对话流程当成一个需要显式状态、可持久化、可回退、可观测的工程系统来做"。** 它的 6 篇 lessons 把"为什么旧的 if/else 链路会吃力"论证得比多数教程都清楚——那段论证几乎逐条命中我们 `session.py` 的现状。

同时它也演示了这条路的代价：双链路并存的漂移、序列化类型登记表的维护债、重试装饰器套在有副作用节点上的隐患、子流程搬走后遗留的空转依赖（`avgScore` 恒 null）、以及"混合检索"在主链路上实际退化为纯向量。**引入强编排框架不会消除复杂度，只会把复杂度从控制流搬到状态管理与框架语义上——搬得值不值，取决于流程的分支数和恢复需求。**

对我们最实际的启示只有一句：**先给面试流程一个显式的"当前执行到哪一步"，其余（图框架、checkpoint、Kafka）都是这个想法的不同规模的实现。**
