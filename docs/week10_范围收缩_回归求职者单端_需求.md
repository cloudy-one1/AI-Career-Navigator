# week10 · 范围收缩：删除招聘者端与报告分享，回归求职者单端 需求文档

> 日期：2026-08-31
> 版本目标：v7.5 范围收敛 · 推翻 week8「报告分享与招聘端只读视图」与 week9 v7.0.1「招聘者收件箱」
> 决策依据：本需求文档 + CHARTER.md DC-08（推翻 DC-06 的招聘端与分享部分）

---

## 1. 模块目标

### 1.1 要解决的本质问题

v7.0/v7.0.1 引入了"双端"结构：注册时选择身份（求职者 / 招聘者），招聘者登录后进入只读视图（收到的报告收件箱），并配套了"求职者 → 招聘者"的报告分享链路（免登录链接 + 指定用户名进收件箱）。

复盘后的判断：**这个项目的定位是面向求职者的**。求职者练完、拿到诊断、规划路径，产品使命即告完成；"让招聘者进来验收"是强加的第二端，属于画蛇添足：

- **招聘者端没有独立价值**：它只是"收到的报告"一个列表 + 打开报告，且打开的仍是求职者侧的数据；
- **分享链路失去落点**：分享链接的全部意义是给招聘者看；招聘者端删除后，链接没有接收对象；
- **结构复杂度是净负担**：身份分流（`applyRoleView` / `data-audience`）、角色校验（`is_recruiter` / `AUTH_ROLES`）、收件箱数据表（`share_links.shared_with`）、四个前端入口文件（share.html / share-main.js / shareReport.js / recruiterInbox.js），都是为了支撑一个不该存在的第二端。

**结论**：删除招聘者端与报告分享，产品回到"纯求职者单端"。认证与资源归属**保留**——求职者登录后跨设备归集自己的简历/岗位/历史，这是求职者自己的功能，与双端无关。

### 1.2 目标

1. 删除 `recruiter` 角色：注册不再选身份，`AUTH_ROLES` 只剩 jobseeker，`validate_role` 对 recruiter 一律回退 jobseeker
2. 删除招聘者收件箱：后端 `/api/recruiter/*` 两个接口、前端收件箱面板/导航/文件全部移除
3. 删除报告分享：`/api/sessions/{id}/share`、`/api/sessions/{id}/shares`、`/api/shares/{token}`、`/api/shared/{token}`、`/share/{token}` 分享页全部移除
4. 六步旅程改五步：取消"连机会（报告分享 / 招聘者收件箱）"，产品叙事同步收敛
5. 保留认证与资源归属（`AUTH_ENABLED` 开关、登录/注册、会话 owner、简历库/岗位库归属）不变

### 1.3 非目标（明确不做）

- **不删除认证体系**：登录/注册、JWT、匿名模式、资源归属全部保留——这是求职者单端自身的功能
- **不删除 `users` 表的 `role` 列**：SQLite 删列需重建表，存量数据无碍；逻辑上恒为 jobseeker，文档注明即可
- **不重写任何既有求职者功能**：面试/报告/题库/记忆/规划/市场/简历库/岗位库一律不动
- **不修改 docs 历史文档**（week8 需求、竞品研读、UI 评审等）：它们是历史记录，不是现行规范

---

## 2. 技术方案（删除清单）

### 2.1 后端

| 文件 | 动作 | 说明 |
|---|---|---|
| `backend/routers/share.py` | **删除** | 分享管理（share/shares/revoke）+ 免登录只读（shared）+ 收件箱（recruiter/inbox、recruiter/reports）+ 分享页 HTML（share/{token}）全部路由 |
| `backend/share_access.py` | **删除** | token 签发/摘要、`redact_pii` 脱敏、`create_share_link`、`recruiter_inbox`、`open_inbox_report`、`resolve_shared_report` 全部逻辑 |
| `backend/main.py` | 修改 | 移除 `share` 模块导入与 `include_router(share.router)`（L32-33、L125） |
| `backend/schemas.py` | 修改 | 删 `ShareCreateRequest`；`UserRole` 枚举删 `RECRUITER`；`RegisterRequest.role` 保留字段但恒为 JOBSEEKER（前端不再传） |
| `backend/auth.py` | 修改 | 删 `UserContext.is_recruiter` 属性；`validate_role` 只认 jobseeker，其余一律回退 jobseeker；`AUTH_ROLES` 校验随之收窄 |
| `backend/config.py` | 修改 | `AUTH_ROLES = ("jobseeker",)` |
| `backend/db.py` | 修改 | 删 share_links 建表（L185-205）、`shared_with` 迁移（L272-282）、save/get/list/revoke/bump/list_inbox/get_inbox 等 8 个函数；`init_db` 末尾加幂等 `DROP TABLE IF EXISTS share_links`（老库清理） |
| `.importlinter` | 修改 | L2 层模块列表移除 `backend.share_access`（L18） |

**`users.role` 列处理**：保留列（默认 jobseeker），删除所有"注册传 role / 读 role 分流"的代码路径。历史 recruiter 用户自然降级为 jobseeker——不再有任何代码读取该字段做身份区分。

### 2.2 前端

| 文件 | 动作 | 说明 |
|---|---|---|
| `frontend/share.html` | **删除** | 分享页独立入口 |
| `frontend/src/share-main.js` | **删除** | 分享页装配 |
| `frontend/src/js/shareReport.js` | **删除** | 分享页报告渲染（雷达/脱敏内容） |
| `frontend/src/js/recruiterInbox.js` | **删除** | 招聘者收件箱 |
| `frontend/vite.config.js` | 修改 | `rollupOptions.input` 只留 main（移除 share 入口） |
| `frontend/src/js/app.js` | 修改 | 删 `RECRUITER_TABS`、`applyRoleView`（身份分流）、收件箱导入/初始化、`auth:changed` 中角色分支 |
| `frontend/src/js/auth.js` | 修改 | 删注册身份选择 `rolePicker`；登录态元信息不再区分求职者/招聘者 |
| `frontend/src/js/report.js` | 修改 | 删 `renderShareSection`/`renderShareList`/`renderLastUrl` 及其调用（报告页分享卡片整块移除，L300-441） |
| `frontend/index.html` | 修改 | 删侧边栏"连接"分组标签与"收到的报告"入口（L96-101）、`recruiter-inbox-panel`（L122-123）、底部导航收件箱（L167-171） |
| `frontend/src/css/pages/auth.css` | 修改 | 删 `.role-seg*` 注册身份样式与 `share-*` 分享样式（share 样式主体集中在此） |
| `frontend/src/css/pages/report.css` | 修改 | 清理分享残留（注释与孤立选择器） |

**导航结构变化**：侧边栏从"备战 / 演练 / 洞察 / 连接 / 账户"五组回到"备战 / 演练 / 洞察 / 账户"四组（"连接"整组删除）；`data-audience` 属性与显隐机制一并移除——不再有按身份切换视图的逻辑。

### 2.3 测试

| 文件 | 动作 |
|---|---|
| `tests/test_share.py` | **删除**（token/脱敏/归属/HTTP/收件箱全部用例） |
| `tests/test_auth.py` | 修改：`test_invalid_role_falls_back_to_jobseeker` 中 `validate_role("recruiter")` 断言改为回退 jobseeker |

### 2.4 文档

| 文件 | 动作 |
|---|---|
| **README.md** | 删「👥 双端使用（v7.0）」整节；核心亮点"双端平台化"改为"认证与资源归属（单端）"；项目结构树删 4 个前端文件 + 2 个后端模块；简介/局限表同步 |
| **CHARTER.md** | 产品命题六步 → 五步（删"连机会"）；**新增 DC-08**（推翻 DC-06 招聘端与分享部分）；架构约束 L2 表删 share_access |
| **CHANGELOG.md** | 新增 v7.5.0 条目 |
| **CODEBUDDY.md** | 定位描述、结构树、版本号同步 |
| **docs/产品定位延伸_全流程求职陪跑.md** | 六步旅程表 → 五步（删"连机会"行及其叙事） |

---

## 3. 涉及的知识点

1. **范围收缩也是决策**：双端不是"默认好"或"默认坏"，而是与定位匹配才成立。v7.0 加双端时定位是"平台化"，v7.3 之后定位收敛为"面向求职者陪跑"，第二端失去叙事落点——删除是让结构与定位对齐，不是"回滚失败"。
2. **认证 ≠ 双端**：登录/资源归属是求职者单端的自身能力（跨设备归集、数据不外泄），与"第二端"解耦；删除时不能误伤认证本身。
3. **删除的完整性**：功能删除必须连带数据表、分层契约（`.importlinter`）、前端入口（vite）、导航、样式、测试、文档八处一起清，否则留下"看得见改不了"的死角。
4. **历史文档 vs 现行规范**：week8 需求文档记录的是当时的决策与理由，保留作为历史；现行规范以本需求 + CHARTER DC-08 为准。

---

## 4. 验证方式

1. `pytest tests/test_auth.py -q` 全绿；**全量 `pytest tests/ -q` 全绿**（大改动必须全量）
2. 分层契约：`python run.py lint` 通过（L2 不再登记 share_access）
3. 前端构建：`cd frontend && npm run build` 成功（单入口）
4. 冒烟：
   - 注册页**不再出现身份选择**；登录后无"收到的报告"入口
   - 报告页**不再有分享卡片**；`/api/sessions/{id}/share` 等四个端点返回 404
   - 求职者登录后简历库/岗位库/历史记录归属正常（认证未被误伤）
   - `frontend/share.html` 访问 404（入口已删）
5. `grep -ri "recruiter\|share" backend frontend/src tests --include=*.py --include=*.js --include=*.html` 无残留（allowlist：CHANGELOG 历史条目、docs 历史文档除外）

---

## 修改记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-08-31 | v7.5.0 | 发布。后端删 `routers/share.py`、`share_access.py`；`main.py` 移除挂载；`config.py` 角色收窄；`auth.py` 删 `is_recruiter`；`schemas.py` 删 `ShareCreateRequest`/`RECRUITER`；`db.py` 删 share_links 全部函数 + 幂等 DROP 老表；`.importlinter` 移除契约。前端删 share.html/share-main.js/shareReport.js/recruiterInbox.js 四文件，vite 单入口；app.js 删身份分流；auth.js 删身份选择；report.js 删分享卡片；index.html 删收件箱导航与"连接"分组；auth.css 删 193 行分享样式 + role-seg。测试删 test_share.py（36 例），test_auth.py 角色断言回退。文档：README/CHARTER（+DC-08）/CHANGELOG（v7.5.0）/CODEBUDDY/产品定位（六步→五步）。验证：pytest 996 passed + 1 skipped；run.py lint 通过；npm run build 通过。 |
