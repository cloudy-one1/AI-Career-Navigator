# API 参考

> 后端 FastAPI 服务的完整接口清单。路由按域拆分在 `backend/routers/*.py`，由 `backend/main.py` 统一注册。
> 生成方式：从各 router 的装饰器逐条提取（`system` / `voice` / `sessions` / `assets` / `reports` / `question_bank` / `diagnostics` / `market` / `analytics` / `profile` / `interview_ws`），共 **59 个 HTTP 端点 + 1 个 WebSocket 端点**（口径：只计 11 个 router 注册的路由；`main.py` 直接注册的 `GET /` 产品落地页不在其内）。

## 通用约定

| 项 | 说明 |
|---|---|
| Base URL | `http://localhost:8000`（开发态；生产由 Docker 映射） |
| 认证 | **无**——v8.3 起全站免登录（CHARTER DC-10，单用户本地工具）。所有接口均不含身份概念 |
| 请求体上限 | 普通请求 **1MB**；上传类路径 **10MB**（`/api/sessions/upload`、`/api/resumes/upload`、`/api/upload-jd`、`/api/market/import`、`/api/voice/asr`）。超限返回 `413` |
| 限流 | slowapi 按 IP 计数，超限返回 `429 {"detail": "请求过于频繁，请稍后再试。限制：<规则>"}` |
| 错误格式 | FastAPI 默认 `{"detail": "<原因>"}`；业务错误同样走 detail 字段 |
| 交互文档 | 服务启动后访问 `/docs`（Swagger UI）与 `/redoc`——由 Pydantic Schema 自动生成，字段级结构以它为准 |

限流档位（可在 `.env` 覆盖）：全局 `100/minute` · 上传 `10/minute` · 会话 `20/minute` · Gap `20/minute` · 职业规划 `10/minute` · 语音 `20/minute` · 市场采集 `3/minute`。硬编码档位：预热 `1/minute`、岗位研究 `10/minute`、市场导入 `5/minute`、跨岗位对比 `5/minute`、市场解读 `20/minute`。

## 1. 系统与健康 `system.py`

| 方法 | 路径 | 说明 | 限流 |
|---|---|---|---|
| GET | `/api/health` | 健康检查（含 AI 后端连通状态） | 全局 |
| GET | `/api/providers` | 列出全部 AI 后端及当前生效后端 | 全局 |
| POST | `/api/switch-provider` | 切换 AI 后端（Key 无效时告警但仍允许切换） | 全局 |
| POST | `/api/warmup` | 预热模型连接（避免首题冷启动延迟） | 1/minute |

## 2. 求职档案 `profile.py`（v8.0 领域核心）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/profile` | 聚合档案：当前简历 / 目标岗位 / 能力水平 / 待提升项 / 五步完成度 / 下一步建议。60s TTL 缓存，是**投影而非新真相源** |
| POST | `/api/profile/refresh` | 让档案缓存失效（面试出报告后调用，避免"练完要等 60 秒才更新"） |

## 3. 会话与面试准备 `sessions.py`

| 方法 | 路径 | 说明 | 限流 |
|---|---|---|---|
| POST | `/api/sessions` | 创建会话并生成首轮题目（可带 `resume_id` / `position_id` / `mode` / `company_profile`） | 20/minute |
| GET | `/api/sessions` | 会话列表 | 全局 |
| GET | `/api/sessions/{session_id}` | 会话详情 | 全局 |
| POST | `/api/interview/{session_id}/mode` | 会话中切换模式 / 阶段（实时生效） | 20/minute |
| GET | `/api/company-profiles` | 公司风格配置列表（字节 / 腾讯 / 阿里…） | 全局 |
| POST | `/api/sessions/upload` | 简历文件解析（PDF/DOCX/TXT）。**注意：为兼容旧前端，文本截断到 5000 字**——入库场景请用 `/api/resumes/upload` | 10/minute |
| POST | `/api/upload-jd` | JD 文件解析，仅回文本、不入库 | 10/minute |

## 4. 资产库（简历库 / 岗位库）`assets.py`

| 方法 | 路径 | 说明 | 限流 |
|---|---|---|---|
| GET | `/api/resumes` | 简历列表 | 全局 |
| POST | `/api/resumes` | 新建简历（直接提交文本） | 全局 |
| POST | `/api/resumes/upload` | 上传简历文件并**入库**（不截断）→ `201` | 10/minute |
| GET | `/api/resumes/{resume_id}` | 简历详情（含全文 `raw_text`） | 全局 |
| PATCH | `/api/resumes/{resume_id}` | 改标题 / 解析结果 | 全局 |
| DELETE | `/api/resumes/{resume_id}` | 删除简历（物理删除） | 全局 |
| GET | `/api/positions` | 岗位列表 | 全局 |
| POST | `/api/positions` | 新建岗位 | 全局 |
| GET | `/api/positions/{position_id}` | 岗位详情（含 `jd_text` 全文） | 全局 |
| PATCH | `/api/positions/{position_id}` | 改标题 / JD 文本 | 全局 |
| DELETE | `/api/positions/{position_id}` | 删除岗位 | 全局 |

> `/api/resumes/upload` 与 `/api/sessions/upload` 的区别是**历史遗留**：后者为兼容旧前端会静默截断到 5000 字，入库一律走前者。

## 5. 报告 `reports.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/reports/{session_id}` | 综合报告（五维评分 / 逐题拆解 / 薄弱点 / 市场基准） |
| GET | `/api/reports/{session_id}/review` | 导出 Markdown 复盘 |
| GET | `/api/reports/{session_id}/export.html` | 导出打印友好的 HTML（浏览器 Ctrl+P 得 PDF） |

## 6. 诊断与长期记忆 `diagnostics.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/feedback` | 提交单题诊断请求（HTTP 兼容模式；正式面试走 WebSocket） |
| GET | `/api/feedback/{session_id}` | 取会话的诊断反馈 |
| GET | `/api/weakness-profile` | 全局薄弱点聚合（**支持 `?position_id=` 按岗位过滤**） |
| GET | `/api/weakness-profile/{session_id}` | 单场薄弱点画像 |
| GET | `/api/weakness-profile/points` | 薄弱点明细（记忆图谱数据源，支持 `include_resolved` / `limit` / `position_id`） |
| GET | `/api/weakness-profile/suggestions` | 复习建议（最该优先补的未解决薄弱点） |
| PUT | `/api/weakness-profile/{point_id}/resolve` | 标记已解决 / 恢复未解决 |
| DELETE | `/api/weakness-profile/{point_id}` | 删除单条薄弱点（物理删除，不可恢复） |

## 7. 市场数据 `market.py`

| 方法 | 路径 | 说明 | 限流 |
|---|---|---|---|
| GET | `/api/market/jobs` | 岗位列表（过滤 + 分页：`limit` / `offset` / 关键词 / 城市 / 学历…） | 全局 |
| GET | `/api/market/jobs/{job_id}` | 岗位详情（含 Gap 分析用 JD 文本） | 全局 |
| GET | `/api/market/stats` | 统计概览（`avg_salary` 是 `{avg_k, min_k, max_k}` 对象） | 全局 |
| GET | `/api/market/charts` | 全部图表的聚合数据（一次取回，避免每卡一请求） | 全局 |
| POST | `/api/market/insight` | 对指定图表 section 生成 AI 解读（服务端 TTL 缓存 5 分钟；无 Key / 异常返回 `{"error": ...}` 而非 5xx） | 20/minute |
| POST | `/api/market/crawl` | 启动实时采集（后台任务，返回 `task_id`；`cities` 不传 = 全国） | 3/minute |
| GET | `/api/market/crawl/status/{task_id}` | 轮询采集进度 | 全局 |
| GET | `/api/market/city-map` | 省份 → 城市级联数据 | 全局 |
| POST | `/api/market/jobs/{job_id}/interest` | 切换「感兴趣」收藏（落库，重新采集不清空） | 全局 |
| POST | `/api/market/jobs/{job_id}/to-position` | 市场岗位导入岗位库（幂等，返回 `{position, created}`） | 全局 |
| POST | `/api/market/import` | 从 job-crawler 的 `data.db` 导入存量数据 | 5/minute |
| POST | `/api/research-position` | 岗位画像研究（DuckDuckGo 检索 + LLM 分析） | 10/minute |

## 8. 分析：Gap / 对比 / 职业规划 `analytics.py`

| 方法 | 路径 | 说明 | 限流 |
|---|---|---|---|
| POST | `/api/gap-analysis` | 简历-岗位六维 Gap 分析（直接提交文本） | 20/minute |
| GET | `/api/gap-analysis/{session_id}` | 按会话做 Gap 分析 | 全局 |
| POST | `/api/cross-job-compare` | 一份简历 vs 多个岗位，输出排名与择岗建议 | 5/minute |
| POST | `/api/career-plan` | 职业路径规划（时间轴多阶段；可注入 `weakness_context` / `skill_gap_context`；成功时给「发展路径」打点） | 10/minute |

## 9. 题库 `question_bank.py`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/question-bank` | 题目列表（支持分类 / 难度 / 收藏等过滤） |
| POST | `/api/question-bank` | 新建题目 |
| PUT | `/api/question-bank/{question_id}` | 更新题目 |
| DELETE | `/api/question-bank/{question_id}` | 删除题目 |
| POST | `/api/question-bank/{question_id}/favorite` | 切换收藏 |
| POST | `/api/question-bank/import` | 从历史会话导入题目 |

## 10. 语音（MiMo 云端）`voice.py`

| 方法 | 路径 | 说明 | 限流 |
|---|---|---|---|
| POST | `/api/voice/tts` | 文本合成语音，返回 `{used, audio_b64, format, message}` | 20/minute |
| POST | `/api/voice/asr` | 录音转写，返回 `{ok, text, message}` | 20/minute |

`used` / `ok` 为 `false` 表示未配 `MIMO_API_KEY` 或云端失败，**前端自动降级到浏览器原生语音**，不阻塞面试。

---

## 11. WebSocket 面试主循环 `/ws/interview/{session_id}`

面试的核心链路走 WebSocket（HTTP 端点只负责准备与取结果）。

**帧格式**：一律 `{"type": "<类型>", "data": {…}}`，`data` 必须嵌套、不能展开到顶层。

**握手**：只校验会话是否存在。不存在 → 先发 `error{message:"会话不存在"}` 再 `close(4000, "session_not_found")`。v8.3 起不再做身份校验（原 `4001` 已随认证下线）。

### 客户端 → 服务端

| type | data | 说明 |
|---|---|---|
| `answer` | `{text, source?, from_voice?}` | 提交回答（`source:"voice"` 时诊断注入 ASR 容错评分话术） |
| `ping` | `{}` | 心跳，服务端回 `pong` |
| `switch_mode` | `{mode?, stage?}` | 会话中切换模式 / 阶段，非法值回 `error` 不中断 |
| `skill` | `{action: "list" \| "activate" \| "deactivate", name?}` | 面试技能（有状态多轮，**显式触发**，不靠关键词猜测） |

回答文本命中「结束面试」等退出口令时，不诊断、不计分，直接收束并照常生成部分报告。

### 服务端 → 客户端

| type | 时机 |
|---|---|
| `interviewer_info` | 连接后：风格 / 模式 / 阶段 / 轮次信息 |
| `dimension_weights` | 连接后：本场各维度权重（按 JD 动态计算，告知评分口径） |
| `interviewer_change` | 面试官角色切换 |
| `round_start` | 每轮开始 |
| `question` | 出题（含 `intent` / `focus_dimension` / `is_pressure` / `basis` 出题依据） |
| `diagnosis_result` | 单题诊断结果（五维评分 + 证据引用 `quote`） |
| `radar_update` | 雷达图增量数据 |
| `weakness_update` | 薄弱点累计更新 |
| `follow_up` / `follow_up_received` | 追问下发 / 追问回答已收到 |
| `difficulty_change` | 动态难度调整 |
| `round_quality_check` / `extra_question` | 轮次质检 / 追加题 |
| `mode_change` | 模式切换生效 |
| `skill_list` / `skill_start` / `skill_end` | 面试技能事件 |
| `interview_closing` / `round_summary` / `interview_done` | 收尾、轮次小结、面试完成 |
| `security_block` | 内容护栏拦截（启发式，可被绕过，**非安全边界**） |
| `error` / `pong` | 错误 / 心跳响应 |

**关闭码**：`1000` = 正常完成（服务端主动关闭，前端不重连）；`4000` = 会话不存在（不可恢复，前端应停止重连）。

> 端到端集成测试见 `tests/test_interview_ws.py`（4 条主路径 + 握手契约）。

---

## 相关文档

- 字段级 Schema：`/docs`（Swagger UI，服务启动后访问）或 `backend/schemas.py`
- 环境变量与限流档位：`.env.example`
- 分层依赖约束（改路由前必读）：[CHARTER.md](../CHARTER.md)
