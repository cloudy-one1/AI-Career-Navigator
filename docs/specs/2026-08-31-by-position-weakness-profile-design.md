# 能力画像按岗位分组（设计文档）

- 日期：2026-08-31
- 状态：已批准，待评审
- 范围：让「能力诊断 → 长期记忆」页的「能力画像（历史累积）」支持按目标岗位分组查看

## 1. 背景与问题

当前 `GET /api/weakness-profile` 把用户**所有历史面试**的薄弱点按维度（STAR 完整性、量化程度、专业深度……）做全局平均聚合，单次面试多次练习也混在一起。

用户实际场景：**针对同一个岗位会面试多次**，希望按岗位分别看能力画像，而不是把所有岗位的练习揉成一坨。

本期目标：把能力画从「全局唯一」升级为「可按岗位切换」，并保持「全部岗位」总览；切换时整页（画像 + 下方薄弱点图谱/明细）口径一致。

## 2. 目标

- 能力画像支持按岗位分组查看，默认「全部岗位」总览。
- 分组切换器（横向 chips）位于画像卡内标题下方。
- 切换某岗位后，下方薄弱点图谱/明细同步按该岗位过滤。
- 样本量过少时给出提示，避免被单场面试误读。

## 3. 非目标（YAGNI）

- **不引导**「未关联岗位的会话」回填岗位库——只做分组展示，不在本期改变面试开练流程。
- **不做**跨岗位横向对比图（形态 C/多卡并排已否）。
- **不动** `weakness_memory` 表（v6.5 的全局 EMA 衰减画像），那是一条独立的长期记忆维度，本期保持原样。
- 不做岗位画像的跨账号共享（本项目已认证下线，单用户本机范畴）。

## 4. 分组口径（已定）

每个 `weakness_profile` 记录通过 `session_id` 关联 `sessions`，取 `position_id` / `jd_text`：

| 条件 | 组 key | 组显示名 |
|------|--------|----------|
| `sessions.position_id` 非空 | `pos:<position_id>` | `positions.title` |
| `position_id` 为空且 `jd_text` 非空 | `jd:<jd_text 完整文本>` | `自定义JD：` + `jd_text` 前 18 字 |
| 两者皆空 | `none` | `未指定岗位` |

- **始终保留「全部岗位」**：等价于今天的全局聚合（key=`all` 或不传 `group`），作为默认选中态。
- 相同 `jd_text` 文本即同一组，无需额外哈希（文本本身即稳定 key）。
- 分组顺序：全部岗位在前，其余按 `session_count` 降序；组名过长时前端 chips 内省略号、悬浮显示全称。

## 5. 架构与数据流

```
weakness_profile (按 session_id 记录各维度分)
      │  JOIN
      ▼
sessions (position_id, jd_text)  ── position_id → positions(title)
      │
      ├─ GET /api/weakness-profile/groups   → 分组清单 [{key,name,session_count}]
      ├─ GET /api/weakness-profile?group=    → 该组按 dimension 聚合
      └─ GET /api/weakness-profile/points?group= → 该组薄弱点明细（图谱/明细数据源）

前端 memoryGraph.js：
  画像卡顶部 chips（全部岗位 + 各分组）
      └─ 选中 → 重拉画像 + 重拉 points（同一 group）
```

- **不新增表、无 DB 迁移**：`weakness_profile` 已有 `session_id`；`sessions` 的 `position_id` 列在 v7.0 老库迁移中已确保存在，`jd_text` 字段一直存在。所有分组在查询层 JOIN 计算。
- 老库会话 `position_id` 为空属正常现象（v7.0 前的会话），落入「自定义JD」或「未指定岗位」组，不产生报错。

## 6. 后端改动

### 6.1 `backend/db.py`

新增/修改：

- `async def get_weakness_profile_groups() -> list[dict]`
  - 查 `SELECT wp.session_id, s.position_id, s.jd_text FROM weakness_profile wp JOIN sessions s ON wp.session_id = s.id`。
  - 一次 `SELECT id, title FROM positions` 做 `position_id → title` 映射缓存。
  - 按第 4 节口径在 Python 层分组，按 `session_id` 去重统计 `session_count`。
  - 返回 `[{key, name, session_count}]`，「全部岗位」不在此列表（由前端前置）。

- `async def get_weakness_profile(group: str | None = None) -> list[dict]`
  - `group` 为空或 `'all'` → 走现有 `get_global_weakness_profile()` 逻辑（行为不变）。
  - 否则解析 group，JOIN `sessions` 后用**参数化** WHERE 过滤：
    - `pos:<id>` → `s.position_id = ?`
    - `jd:<text>` → `s.jd_text = ?`
    - `none` → `s.position_id IS NULL AND (s.jd_text IS NULL OR s.jd_text = '')`
  - `GROUP BY dimension ORDER BY historical_avg ASC`（与现有口径一致），字段：`dimension, historical_avg, avg_weight, session_count, open_count`。

- `async def list_weakness_points(include_resolved=False, limit=None, group=None)`
  - 现有逻辑基础上，当 `group` 非 `None`/`all` 时，JOIN `sessions` 并加上述同构 WHERE 过滤（保持「优先复习最要命短板」的 `ORDER BY avg_score ASC, weight DESC` 口径）。

约束：SQL 中 `position_id` / `jd_text` 一律用 `?` 占位参数，禁止字符串拼接（防注入，因 `jd_text` 是用户输入内容）。

### 6.2 `backend/routers/diagnostics.py`

- 新增 `GET /api/weakness-profile/groups` → `{status:"ok", groups:[...]}`，**注册顺序必须在 `/api/weakness-profile/{session_id}` 之前**（否则 `groups` 会被当成 session_id 吃掉）。
- 修改 `GET /api/weakness-profile`：新增可选 `group: str | None = Query(None)`，转发到 `get_weakness_profile(group)`。
- 修改 `GET /api/weakness-profile/points`：新增可选 `group: str | None = Query(None)`，转发到 `list_weakness_points(..., group=group)`。
- 现有 `/{session_id}` 路由不受影响。

## 7. 前端改动 `frontend/src/js/memoryGraph.js`

- 画像卡（`#weakness-profile`）标题下新增一排**横向可横滑 chips**：`全部岗位` + 各分组（由 `/groups` 填充），选中态高亮。
- 新增模块级状态 `currentGroup`（默认 `null` = 全部）。
- `loadWeaknessProfile()` 改为带 `group` 请求：全部 → 现有接口；分组 → `?group=<key>`。
- 画像卡渲染维度条逻辑不变；前端缓存 `/groups` 返回的每个组 `session_count`，当当前组的 `session_count ≤ 1` 时，卡片角标加「样本较少，仅供参考」。（画像接口 `get_weakness_profile` 也返回同字段，二者口径一致，前端以 `/groups` 为准即可。）
- `loadMemory()`（下方图谱/明细数据源）改为带同一 `group` 请求，使整页口径一致。
- chips 点击 → 更新 `currentGroup` → 重拉画像 + 重拉图谱/明细。

## 8. 边界与错误处理

- 无任何面试 → 画像卡与图谱均走现有空态。
- `/groups` 拉取失败 → 画像卡降级为「加载失败」提示，不阻塞下方图谱（图谱仍可用全部口径）。
- 分组画像拉取失败 → 仅画像区显示「加载失败」，图谱/明细保持可用。
- 组名超长 → chips 内 `text-overflow: ellipsis`，`title` 悬浮显示全称。
- 老库 `position_id` 为空 → 正常落入对应组，无报错。

## 9. 测试

- 后端 `tests/test_profile_service.py`（或并入诊断域测试）：
  - position 分组：两个不同岗位各有多场面试 → 分组正确、session_count 去重正确。
  - JD 文本分组：无 position_id 但相同 jd_text → 归同组；不同 jd_text → 不同组。
  - 未指定分组：position_id 与 jd_text 皆空 → 归 `none`。
  - 全部聚合：不传 group → 与现有 `get_global_weakness_profile` 行为一致。
  - 样本量计数：单场会话的组 session_count=1。
  - SQL 注入：group 含特殊字符不报错（参数化验证）。
- 前端：以手动验证为主（vitest 不强相关），关注 chips 切换、联动、空态、样本量角标。

## 10. 验收标准

1. 「长期记忆」页画像卡顶部出现岗位 chips，默认「全部岗位」。
2. 点击某岗位 → 画像与下方图谱/明细均只显示该岗位数据。
3. 同岗位多次面试聚合为该岗位画像；不同岗位互不干扰。
4. 单场会话的岗位画像标注「样本较少，仅供参考」。
5. 后端无新增表、无迁移；老库数据可正常分组。
6. 全部接口测试通过。
