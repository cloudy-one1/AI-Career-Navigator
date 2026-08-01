# Week5 · v3.0 数据层（真实招聘数据采集）需求文档

> v3 总体方向：把项目从"纯 LLM 驱动"升级为"数据驱动 + LLM 驱动"。
> v3.0 是地基：没有真实岗位数据，v3.1 的 Gap 分析和 v3.2 的市场报告都是空中楼阁。
> 对标参照：cloudy-one1/job-crawler 的数据采集与清洗能力（用户明确批准的三个方向之一）。

---

## 一、模块目标

| # | 目标 | 解决的问题 |
|---|------|-----------|
| 1 | 真实岗位采集 | 当前"岗位画像研究"依赖 DDG 搜索 + LLM 分析，数据碎片化、不可控、无法结构化复用 |
| 2 | 薪资/经验/学历标准化清洗 | 原始 JD 中薪资写法五花八门（"1.5-2.5万·13薪"、"15-25K"、"面议"），无法直接用于统计和匹配 |
| 3 | 技能标签结构化提取 | JD 描述是自由文本，Gap 分析需要可计算的技能集合 |
| 4 | 本地岗位数据库 | 为 v3.1（简历-岗位 Gap 分析）和 v3.2（报告融合市场维度）提供查询基础 |

### 明确的非目标（防止范围蔓延）

- **不做**全国全量爬取：按"关键词 × 城市 × 有限页数"按需采集，与面试场景绑定
- **不做**实时反爬军备竞赛：Playwright + 基础 stealth 即可，被封则提示稍后重试，不上代理池
- **不做**分布式采集：单机 SQLite 足够支撑课程项目规模
- **不替换**现有 DDG 岗位画像研究：两者互补——DDG 研究定性（面试话题），本地数据库定量（薪资/技能分布）

---

## 二、技术方案

### 2.1 整体架构

```
backend/market/                 # [v3.0 NEW] 市场数据子包
├── __init__.py
├── collector.py                # 采集层：Playwright 抓 51job
├── cleaner.py                  # 清洗层：薪资/经验/学历/技能标准化
├── store.py                    # 存储层：market.db 读写（aiosqlite）
└── service.py                  # 服务层：供 API / Gap 分析调用的高层接口
```

**关键决策：独立数据库文件 `data/market.db`**，不并入 `interview.db`。
理由：两类数据生命周期不同——面试会话是用户私有数据，市场岗位是可再采集的公共缓存。
分开后删库重采不影响面试历史；反之面试表迁移也不碰市场数据。

### 2.2 采集层（collector.py）

- 目标站点：**51job**（与 job-crawler 一致，国内岗位覆盖全、字段规整）
- 技术栈：Playwright + Chromium headless + playwright-stealth
- 采集维度：`关键词（岗位名） × 城市 × 页数上限（默认 3 页/城）`
- 反爬策略（够用即止）：
  - headless Chromium + stealth 隐藏 `navigator.webdriver`
  - 随机请求间隔 1.5–4s，模拟人类翻页
  - 单关键词单次上限 5 页，防止失控
- 断点容错：单条解析失败跳过并记日志，不中断整批；原子写入（批量事务提交），中断不丢旧数据
- 去重键：`(source, source_id)` 唯一约束，重复采集自动更新

### 2.3 清洗层（cleaner.py）

| 字段 | 原始形态 | 清洗规则 |
|------|----------|----------|
| 薪资 | "1.5-2.5万·13薪"、"15-25K"、"面议"、"8千-1.2万" | 统一为月薪千元的 `(salary_min, salary_max)`，按薪月数折算；"面议"记 NULL |
| 经验 | "3-5年"、"应届生"、"无需经验" | 标准化为 `(exp_min, exp_max)` 年数，应届=0，无要求=NULL |
| 学历 | "本科及以上"、"大专"、"学历不限" | 有序枚举：不限<大专<本科<硕士<博士 |
| 技能标签 | JD 自由文本 | 复用现有 `skills_data.json` 技能词典做关键词匹配 + 51job 官方 jobTags 直接提取 |

### 2.4 存储层（store.py）

新表 `job_postings`（`data/market.db`）：

```sql
CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT '51job',
    source_id TEXT NOT NULL,
    keyword TEXT NOT NULL,            -- 采集时用的搜索词
    title TEXT NOT NULL,
    company TEXT DEFAULT '',
    city TEXT DEFAULT '',
    salary_raw TEXT DEFAULT '',
    salary_min REAL,                  -- 月薪（千元），NULL=面议
    salary_max REAL,
    exp_min REAL,                     -- 经验下限（年）
    exp_max REAL,
    education TEXT DEFAULT '',        -- 标准化枚举
    tags TEXT DEFAULT '[]',           -- JSON 技能标签
    description TEXT DEFAULT '',
    url TEXT DEFAULT '',
    collected_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(source, source_id)
);
CREATE INDEX idx_jobs_keyword ON job_postings(keyword);
CREATE INDEX idx_jobs_city ON job_postings(city);
```

### 2.5 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/market/collect` | POST | 触发采集（后台任务）：`{keyword, cities[], max_pages}` |
| `/api/market/collect/status` | GET | 查询采集任务进度 |
| `/api/market/jobs` | GET | 岗位列表查询（关键词/城市/学历/薪资区间过滤 + 分页） |
| `/api/market/stats` | GET | 数据概览：总量、城市分布、薪资分布、热门技能 Top N |

安全约束（吸取 job-crawler 经验）：
- 采集接口需 `COLLECT_TOKEN` 口令（`.env` 配置），防局域网内被滥用
- 采集接口限流：单关键词每小时最多 3 次
- 查询接口参数全部走 Pydantic 校验，防注入

### 2.6 与现有系统的集成点

- 创建面试会话时，若 `market.db` 中已有该岗位数据 → 把真实技能分布/薪资区间注入 `web_research` 的岗位画像（定性 + 定量合并）
- 若无数据 → 回退现有 DDG 流程，并提示"可采集该岗位市场数据"（不自动采集，尊重用户选择）

---

## 三、涉及的知识点

| 知识点 | 应用场景 |
|--------|----------|
| Playwright 浏览器自动化 | 无头 Chromium 加载 51job 列表页、等待动态渲染、提取 DOM |
| 反爬对抗基础 | stealth 指纹隐藏、请求节流、User-Agent 轮换 |
| 正则与规则引擎 | 中文薪资表述解析（万/K/千/年薪/13薪/面议） |
| SQLite 并发（WAL） | 采集写入与查询读取并发不互锁 |
| FastAPI BackgroundTasks | 采集是分钟级长任务，不能阻塞 HTTP 响应 |
| 数据库 schema 设计 | 去重约束、索引选择、NULL 语义（面议 vs 未知） |

---

## 四、依赖变更

`requirements.txt` 新增：

```
playwright>=1.44.0
playwright-stealth>=1.0.6
```

部署注意：需额外执行 `playwright install chromium`（约 170MB），
Dockerfile 需相应调整（v3.0 收尾时处理）。

---

## 修改记录 [2026-08-01]

### v3.0 架构变更：从"自行采集"切换为"从 job-crawler 导入"

- **原方案**：本项目的 `collector.py` 用 Playwright 直接爬取 51job，与 job-crawler 的功能重复
- **用户指出的问题**：
  1. job-crawler 已有成熟采集管道（250+ 测试用例验证），本项目不应重复造轮子
  2. "不能复用"的原约束是出于学术诚信的过度保守——导入数据资产不等于复现代码
  3. Playwright 依赖体积大（~200MB），移除后项目更轻量、维护成本更低
- **修改后的方案**：
  - `collector.py` 删除，新建 `importer.py`：读取 job-crawler `data.db` → 字段映射 → 批量写入 `market.db`
  - `service.py` 简化：删除采集任务编排（`IMPORT_TASKS`/限流/口令），只保留 `import_and_store()` + `find_relevant_snapshot()`
  - `config.py` 简化：`IMPORT_TOKEN/RATE/MAX_PAGES` → `JOB_CRAWLER_DB_PATH`
  - `main.py` 简化：`POST /api/market/import` 从后台任务改为同步端点
  - `requirements.txt` 瘦身：移除 `playwright>=1.44.0`、`playwright-stealth>=1.0.6`
  - `.env.example` 更新：采集配置 → `JOB_CRAWLER_DB_PATH`
  - `项目前备知识_决策过程记录.md` 2.3 节追加"推翻不复用约束"决策记录

- **批判性思维判断点**：
  - 原"不能复用"约束的问题本质：把"担心查重"的模糊顾虑上升为硬性规则，未经"数据复用 vs 代码复用"的语义区分。数据复用在学术诚信语境下不构成问题（引用的是工具产出的数据资产，不是作业本身），而原约束不加区分地一禁了之，导致做了大量无价值的重复工程。
  - 工程原则取舍：项目核心定位是"回答质量诊断"，市场数据是支撑层而非核心层。在支撑层重复造轮子（Playwright 爬虫）完全背离第一性原理——既不提升诊断质量，又增加维护负担，是典型的"技术自嗨"。

---

## 五、验收标准

1. 输入关键词"Python 后端"+ 城市"上海"，能采到 ≥ 50 条结构化岗位
2. 薪资清洗准确率：人工抽查 20 条，`(min, max)` 解析正确 ≥ 90%（"面议"不计入错误）
3. 空库启动不崩溃，所有查询端点返回友好空态
4. 采集中断后重启，已有数据完整，重复采集不产生重复记录
5. `/api/market/stats` 能返回正确的聚合统计

---

## 六、前置修复（动工时一并处理）

`backend/db.py` `init_db()` 第 91/105 行：`diagnosis_feedback` 建表误用未定义变量
`cursor`（应为 `db`），当前初始化即抛 `NameError`。属于 v2.5 遗留缺陷，
在 v3.0 提交中一并修复并在 commit message 中说明。
