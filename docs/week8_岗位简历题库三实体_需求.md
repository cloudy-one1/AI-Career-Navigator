# week8 · 岗位/简历/题库三实体 需求文档

> 日期：2026-08-29
> 版本目标：v7.0 双端平台化改造 · D2
> 决策依据：CHARTER.md DC-06；数据模型选 A（保留"求职者自主发起"）

---

## 1. 模块目标

### 1.1 要解决的本质问题

当前简历的处理方式是一次性的：

- `POST /api/sessions/upload`（`392:backend/main.py`）把 PDF/DOCX/TXT 解析成文本，**直接塞进 `sessions.resume_text` 列，不落独立的简历表**
- 结果是同一份简历想练第二场，必须重新上传、重新解析（解析要调 LLM）

同时，"岗位"目前只是一个文本框里的 JD 字符串，没有实体——无法在多场面试间复用，也无法与题库建立关联。

**一句话：缺了"可复用的输入资产"这一层。** 招聘方平台（Gua-AI-interview）恰恰是围绕"岗位/题库/简历"三个实体建的，这也是两端能共用同一套内核的地基。

### 1.2 目标

1. **简历库**：上传一次，跨会话复用；保留解析结果（技能/项目/经历摘要）
2. **岗位库**：JD 存成实体，练习时直接选用，不用每次粘贴
3. **会话关联**：`sessions` 记录 `resume_id` / `position_id`，报告可回溯"这场练的是哪份简历、哪个岗位"

### 1.3 非目标（明确不做）

- **题库不动**：`question_bank` 表已存在（`83:backend/db.py`），本次不加归属、不改结构。理由：题库当前是"从会话导入的收藏夹"语义，加归属会牵动 `questionBank.js` 与 6 个端点的签名，收益却很低（题库对招聘端无意义）。**"三实体"里的题库本次实际不改造，需求文档保留它是为了与 DC-06 的措辞对齐。**
- 不做简历版本管理（一份简历只留当前版本，改了就覆盖）
- 不做简历自动去重（同名/同内容不合并）
- 不做岗位 JD 的结构化解析（存原文，解析留给现有的 `dimension_weights.analyze_jd_weights`）

---

## 2. 技术方案

### 2.1 数据模型

```sql
-- 简历库
CREATE TABLE IF NOT EXISTS resumes (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT,                  -- 无外键约束（SQLite ALTER 限制），归属由应用层保证
    title        TEXT NOT NULL,         -- 用户可改的显示名，默认取文件名
    filename     TEXT,                  -- 原始文件名
    raw_text     TEXT NOT NULL,
    parsed_json  TEXT,                  -- 解析出的技能/项目/经历摘要（JSON 字符串），可为空
    char_count   INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now','localtime')),
    updated_at   TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_resumes_owner ON resumes(owner_id);

-- 岗位库
CREATE TABLE IF NOT EXISTS positions (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT,
    title        TEXT NOT NULL,
    department   TEXT,
    jd_text      TEXT NOT NULL,
    created_at   TEXT DEFAULT (datetime('now','localtime')),
    updated_at   TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_positions_owner ON positions(owner_id);
```

`sessions` 通过 `_ensure_owner_columns`（D1 已建）追加的 `owner_id` / `resume_id` / `position_id` 三列与两个实体关联。

### 2.2 CRUD 落点（全部在 `backend/db.py`）

按现有分区追加两个区块，命名沿用现有风格（`save_session` / `get_report` 等）：

```
Resumes   : save_resume / get_resume / list_resumes / update_resume / delete_resume
Positions : save_position / get_position / list_positions / update_position / delete_position
```

**归属过滤的统一约定**：所有 `list_*` 与 `get_*` 接受 `owner_id: str | None`，非 None 时加 `WHERE owner_id = ?`，None 时不过滤（对应 `AUTH_ENABLED=false`）。这条约定与 D1 的 sessions 过滤保持一致，避免两套写法。

### 2.3 API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/resumes` | 列表（按 owner 过滤），返回摘要不含 `raw_text`（省流量） |
| POST | `/api/resumes` | 新建（可传文本，也可传文件） |
| GET | `/api/resumes/{id}` | 详情（含 raw_text） |
| PATCH | `/api/resumes/{id}` | 改标题 / 重新解析 |
| DELETE | `/api/resumes/{id}` | 删除 |
| GET/POST/GET{id}/PATCH/DELETE | `/api/positions` 同构 | 岗位库 CRUD |

**不新增文件上传端点**：复用现有 `POST /api/sessions/upload` 的解析逻辑，在其内部增加"解析完成后同时写入 resumes 表"的分支，返回 `resume_id`。这样前端"上传新简历"的交互路径不变。

**创建会话时的关联**：`POST /api/sessions` 增加可选参数 `resume_id` / `position_id`；传入时从库里取 `raw_text` / `jd_text` 填充，未传时保持现有"直接传文本"的行为（向后兼容）。

### 2.4 前端改造

- 新增 `frontend/src/js/resumeLibrary.js` 与 `positionLibrary.js` 两个面板模块
- `index.html` 两处导航（侧边栏 + 移动端底部）与面板区各加 2 项
- `app.js` 的 `switchTab` 注册 `initResumeLibrary` / `initPositionLibrary`
- `interview.js` 的简历/JD 区域改为分段控件：「从库选择 / 上传新简历」「从库选择 / 粘贴 JD」，保持"临时上传"路径可用（向后兼容，不强制要求先入库）

设计约束（沿用项目既有视觉语言）：与既有面板同构、卡片化、信息密度优先、带清晰的状态徽标；主色 `#2563EB`，功能色 `#16A34A / #DC2626 / #D97706`。

---

## 3. 涉及的知识点

1. **实体 vs 属性**：什么时候该把一个字段提升为独立实体（复用性 + 可管理性 + 关联查询需求），什么时候不该（过度设计）。本次的判断依据是"跨会话复用"这个真实需求，而不是"招聘平台都有这三个实体"
2. **SQLite 的外键限制**：`ALTER TABLE ADD COLUMN` 不支持 `REFERENCES`，所以存量表加列只能放弃数据库级外键，改用应用层保证引用完整性——这是 SQLite 的硬限制，需要在代码注释里写明，否则后来者会以为是实现疏漏
3. **向后兼容的 API 演进**：给已有端点加可选参数（而非改必填或加新端点），使老客户端零改动继续工作
4. **列表接口的字段裁剪**：列表不返回大字段（`raw_text` 可能几万字符），详情才返回——避免 N 条简历把响应撑到几 MB
5. **归属过滤的统一抽象**：`owner_id: str | None` 这一个参数同时表达"按用户过滤"与"不过滤（匿名模式）"两种语义，避免为匿名模式再写一套查询

---

## 4. 验证方式

1. `pytest tests/test_entities.py tests/test_db.py -q` 全绿
2. 冒烟：
   - 上传一份简历 → 出现在简历库 → 新建会话时选中 → 会话正常开始，且 `sessions.resume_id` 正确
   - 用户 A 看不到用户 B 的简历/岗位
   - 不传 `resume_id` 直接传文本创建会话 → 行为与改造前一致（回归底线）
3. `python run.py lint` 通过

---

## 修改记录

### 修改记录 2026-08-29（范围收窄）

- **原方案**：DC-06 写的是"引入岗位/题库/简历库三个实体"，字面理解要改造三个。
- **问题本质**：`question_bank` 表其实**已经存在**（v3.0 起就有，带收藏/导入/使用计数等完整 CRUD）。所谓"引入题库实体"实际上是"给已有题库加归属"。而加归属要牵动 6 个端点签名 + `questionBank.js` 全部调用点，收益却接近于零——题库是求职者个人的收藏夹，对招聘端没有任何意义。
- **用户判断点**：工期仅 5 天，应把预算投在简历/岗位这两个**真正缺失**的实体上；对已有功能做"为了对齐措辞而改"的手术是本末倒置。
- **修改后的方案**：本次只新增 `resumes` / `positions` 两张表；`question_bank` 保持原样不动，并在本文档 §1.3 明确记录"题库本次不改造"及理由，避免后续误以为遗漏。
