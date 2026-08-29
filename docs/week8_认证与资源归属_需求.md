# week8 · 认证与资源归属 需求文档

> 日期：2026-08-29
> 版本目标：v7.0 双端平台化改造 · D1
> 决策依据：CHARTER.md DC-06（引入认证与资源归属，从课程项目定位转向工程化平台）

---

## 1. 模块目标

### 1.1 要解决的本质问题

当前系统的访问控制模型是**"知道 session_id 即可读写一切"**：

- `GET /api/sessions` 无任何归属过滤（`411:backend/main.py`），列出全库所有会话
- `/ws/interview/{session_id}` 只校验会话是否存在（`1172:backend/main.py`），不校验连接者身份
- 上传的简历不落库，但也因此**无法跨会话复用**，每次练习都要重传

这三点在当前定位（课程项目、单机自练）下被 CHARTER 记为"刻意取舍"。但一旦引入**招聘者角色**，性质就变了：

> 求职者上传的是**真实简历**，泄露后果与"练习数据泄露"不是一个量级；
> "无访问控制"在多角色场景下不再是取舍，而是缺陷。

### 1.2 目标（要达成什么）

1. **身份**：注册/登录，密码哈希存储，签发 JWT
2. **归属**：session / resume / position 按 `owner_id` 归属，列表与详情严格过滤
3. **连接身份**：WebSocket 握手校验连接者，消除 CHARTER 已披露的"WS 无连接身份校验"局限
4. **可回退**：`AUTH_ENABLED=false` 时行为完全等同现状（这是 DC-06 承诺的缓解措施）

### 1.3 非目标（明确不做）

- 不做 OAuth / 第三方登录 / 邮箱验证
- 不做 RBAC 权限矩阵（只有 `jobseeker` / `recruiter` 两种角色，且 recruiter 在本模块内无任何特权——它的权限在 D3 的分享链接模块体现）
- 不做密码找回（单机/课程场景，成本收益不成立）
- 不做 RefreshToken 轮换（会话时长远短于 token TTL）

---

## 2. 技术方案

### 2.1 分层落点（硬约束）

`.importlinter` 契约要求：L2 只能依赖 L1，禁止向上依赖。

**决策：新建 `backend/auth.py`，登记进 L2 层**。不塞进 `backend/security.py`。

理由：`security.py` 的文档字符串已明确定性为"启发式内容检查，非安全边界"，其 `check_*` 系列面向**面试回答内容**；密码哈希与 JWT 是**访问控制**，两者职责正交。混进同一个模块会让"security"这个名字同时指两件事，后续改任何一边都要读全文件。

```
L4  main.py            —— HTTP 端点 / WebSocket，组合鉴权（Depends）
L3  interview_engine 等 —— 零改动
L2  auth.py（新增）     —— 哈希 / JWT / get_current_user；依赖 L1 的 db 与 config
L1  db.py / config.py  —— users 表 CRUD、AUTH_ENABLED 开关
```

`auth.py` 内的 `get_current_user` 是 FastAPI `Depends` 依赖，调用 `db.get_user_by_id` 属 **L2→L1，合法**；`main.py` 只做 `Depends(auth.get_current_user)`，不自己实现鉴权逻辑。

### 2.2 依赖选型

| 用途 | 选型 | 理由 | 放弃的替代 |
|---|---|---|---|
| 密码哈希 | `bcrypt==4.*` | 自带盐、抗 GPU、久经考验 | `passlib`（已停止维护）、`hashlib.pbkdf2`（要自己管盐与迭代次数） |
| JWT | `PyJWT==2.*` | HS256 纯签发/校验，无框架耦合 | `python-jose`（维护活跃度低）、`fastapi-jwt-auth`（重、封死细节） |

bcrypt 4.x 在 Windows 上的 C 扩展编译问题：`bcrypt` 4.0+ 提供预编译 wheel，Python 3.12 有对应版本，无需本地编译。

### 2.3 开关设计（DC-06 承诺的回滚手段）

```python
# config.py
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
AUTH_SECRET = os.getenv("AUTH_SECRET", "")          # 空则自动生成并持久化到 data/.auth_secret
AUTH_TOKEN_TTL_HOURS = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "72"))
```

**默认 `false`** —— 合入当天零回归风险，出问题可一键退回现状。

`AUTH_ENABLED=false` 时 `get_current_user` 返回匿名虚拟用户 `UserContext(id=None, role="anonymous")`，所有归属过滤跳过，行为与现状逐字节一致。

**密钥处理**：`AUTH_SECRET` 缺省时不随机生成（否则每次重启所有 token 失效），而是生成后持久化到 `data/.auth_secret`（权限 600），首次启动时 warn 一次。该文件必须进 `.gitignore`。

### 2.4 数据模型

新增表（追加 `CREATE TABLE IF NOT EXISTS` 到 `init_db()` 尾部，`await db.commit()` 之前；新建表对老库自动生效，无需 PRAGMA 迁移——`143:144:backend/db.py` 已明确此约定）：

```sql
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'jobseeker',   -- jobseeker | recruiter
    display_name  TEXT,
    created_at    TEXT DEFAULT (datetime('now','localtime')),
    last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
```

ALTER 加列（`sessions` 已有数据，必须走 `_ensure_owner_columns` 迁移范式）：

```python
async def _ensure_owner_columns(db):
    """照抄 _ensure_weakness_columns 范式：PRAGMA table_info 判断后按需 ALTER。"""
    cur = await db.execute("PRAGMA table_info(sessions)")
    cols = {row[1] for row in await cur.fetchall()}
    for col in ("owner_id", "resume_id", "position_id"):
        if col not in cols:
            # SQLite 的 ALTER TABLE ADD COLUMN 不支持 REFERENCES，
            # 故此处不加外键约束，引用完整性由应用层保证（SQLite 硬限制，非偷懒）。
            await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
```

**老数据归属策略（需在 D1 收口前确认，我倾向方案一）**：

| 方案 | 行为 | 评价 |
|---|---|---|
| **一（推荐）** | 存量 `owner_id IS NULL` 的行对任何登录者**不可见**；关掉 `AUTH_ENABLED` 仍可查看 | 严格、语义清晰；代价是老会话"看不见但没丢" |
| 二 | `owner_id IS NULL` 的行对**所有登录者**可见 | 不丢也不需要认领流程，但单机多用户下等于共享 |

### 2.5 API 设计

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/auth/register` | 匿名 | 用户名 3-32 字符、密码 ≥8 位；用户名已存在返回 409 |
| POST | `/api/auth/login` | 匿名 | 返回 `access_token` + 用户基本信息；失败统一 401（不区分"用户不存在"与"密码错误"，防用户名枚举） |
| GET | `/api/auth/me` | 需登录 | 当前用户信息；`AUTH_ENABLED=false` 时返回 anonymous 态 |

**受保护端点接入方式**：`main.py` 里给需要归属过滤的端点加 `user: UserContext = Depends(auth.get_current_user)`；列表类查询在 SQL 层加 `WHERE owner_id = ?`（`AUTH_ENABLED=false` 时跳过该条件）。

**WebSocket 鉴权**：FastAPI 的 `@app.websocket` **不支持 `Depends`**，必须在函数体内手动校验：

```python
@app.websocket("/ws/interview/{session_id}")
async def ws_interview(websocket: WebSocket, session_id: str, token: str = Query(default="")):
    user = await auth.resolve_ws_user(token)          # AUTH_ENABLED=false 时返回匿名
    if not auth.can_access_session(user, session_id): # 校验归属
        await websocket.close(code=4001)              # 4001 = 未授权
        return
    ...
```

前端连接时把 token 作为 query 参数拼在 URL 上（见 §2.6）。

### 2.6 前端改造

- `api.js` 的 `request()` 是**全站唯一出口**，在其中统一注入 `Authorization: Bearer <token>`，改一处全站生效
- 新增 `auth.js`：登录/注册面板、token 存取（localStorage）、401 自动跳登录
- `index.html` 新增 `login-panel` 与对应 `.nav-item[data-tab="login"]`
- `app.js` 的 `switchTab` 注册 `initAuth`，并在未登录时引导到登录面板
- 提供"继续匿名练习"入口（对应 `AUTH_ENABLED=false` 场景），不强制阻断

---

## 3. 涉及的知识点

1. **密码存储**：为什么不能用 MD5/SHA 裸哈希（彩虹表 + GPU 爆破）；bcrypt 的 cost factor 与"慢哈希"的意义；为什么每个用户必须有独立盐
2. **JWT 结构**：Header.Payload.Signature 三段；HS256 签名与验签；JWT **不是加密**（payload 只是 base64，不可放敏感信息）；exp 过期校验
3. **认证 vs 授权**：认证（你是谁）≠ 授权（你能做什么）；本模块只做认证与归属，授权逻辑在 D3
4. **WebSocket 的鉴权特殊性**：握手阶段仍是 HTTP，但 FastAPI 的 `Depends` 不适用于 WS 端点；WS 无法自定义请求头（浏览器限制），只能用 query 参数或 `Sec-WebSocket-Protocol` 子协议
5. **分层架构**：为什么认证模块不能依赖业务层；依赖倒置在 FastAPI `Depends` 上的体现
6. **迁移范式**：为什么"新建表"和"给已有表加列"在 SQLite 上的处理方式完全不同；`PRAGMA table_info` 做列探测的原理
7. **开关式重构（Branch by Abstraction）**：在改动面很大的重构中保留旧行为开关，使任何时刻都能回退——这是本次最重要的工程实践

---

## 4. 验证方式

1. `pytest tests/test_auth.py tests/test_api.py tests/test_session.py -q` 全绿
2. 冒烟：
   - 未登录访问受保护端点 → 401
   - 用户 A 创建的会话，用户 B 的列表里看不到、按 id 直取 → 404
   - `AUTH_ENABLED=false` → 行为与改造前完全一致（这是回归底线）
3. WebSocket：不带 token 或带他人 token 连接 → 被 `close(4001)` 拒绝
4. `python run.py lint` 通过（L2 行已登记 `backend.auth`）

---

## 修改记录

### 修改记录 2026-08-29（需求评审）

- **原方案**：一开始考虑把认证塞进 `backend/security.py`，因为它名字里就有 security。
- **问题本质**：`security.py` 的 `check_*` 系列是**内容启发式检查**（检查回答里有没有 prompt 注入特征），而认证是**访问控制**。两者同名会制造"改内容检查时要读认证代码"的认知负担，且 CHARTER 已明确 `security.check_output()` "仅监控不阻断、非安全边界"——把真正的边界（认证）放进一个自称"非边界"的模块，语义上是矛盾的。
- **用户判断点**：用户确认"偏工程项目"的定位，意味着模块职责单一性优先于文件数量最小化。
- **修改后的方案**：新建 `backend/auth.py` 作为 L2 独立模块，`security.py` 保持原有职责不变。
