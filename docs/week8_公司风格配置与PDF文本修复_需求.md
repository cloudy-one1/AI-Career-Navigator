# Week8 需求文档：公司风格配置层 + PDF 文本两阶段修复（v6.5）

> 来源：对 [chenyongzhi1119/interviewerAgent](https://github.com/chenyongzhi1119/interviewerAgent) 的深度研读（见 [interviewerAgent-深度研读.md](interviewerAgent-深度研读.md)）。
> 该项目"产品包装 90 分、内核 40 分"——三大增强系统全部死于接线缺失，但有三处 P0 亮点值得抄。本模块落实其中两项。

## 一、模块目标

### 1. 公司风格配置层（P0-1，直接对标）

interviewerAgent 用 8 份 `companies/*.yaml` 撑起"8 家大厂面试风格"，**加文件即加公司、零改码**（`loadCompanies` 扫目录读 YAML）。其字段结构极简（15 行 Go struct）：`role_description`（人格层）+ `rounds[].instructions`（轮次行为层）+ `evaluation_rubric`（评估量表）。

我们项目目前的问题：轮次结构硬编码在 `config.INTERVIEW_ROUNDS / TRADITIONAL_ROUNDS`，面试官角色卡来自 `config.INTERVIEWER_STYLES`（7 种风格是"语气"维度），但**没有"目标公司"维度**——面字节和面腾讯应是两套评判标准与追问清单，而我们的面试官对任何公司都是同一套话术。

目标：新增 `backend/company_profiles.py`（L2 数据层），YAML 目录热加载；会话创建时选定（显式选择 > JD 关键词自动匹配 > 不启用）；公司人格注入面试官角色卡，轮次指令按轮次名关键词匹配注入，评估量表进报告。

### 2. PDF 文本两阶段修复（P0-2，直接可抄）

interviewerAgent 的 `internal/extract/pdf.go` 是其工程含量最高的文件：PDF 库吐出的文本被排版切碎/粘连后，做两阶段启发式修复——
- **Phase 1 逆操作（rejoin）**：只认两种硬断信号（编号列表项、≥6 字母的全大写标题），其余全部拼接，ASCII 单词间补空格；
- **Phase 2 复原（restore）**：中文章节词表前后插空行、`·` 前换行、`-`+CJK 换行（避开 `2023-09` 日期与负数）、嵌入正文中的编号项前换行（排除 `3.14`）。

我们的 `resume_parser.parse_pdf` 目前只做"逐页提取 + join"，无任何文本修复。目标：把这两组启发式移植为纯函数后处理，改善简历解析质量。

## 二、明确不抄的部分（范围纪律）

- **P0-3 多模态图片只注入首条消息**：不落地。经全文检索，本项目后端**无任何图片输入链路**（0 处 image/multimodal 匹配），没有可挂载的调用点。强行预埋就是 interviewerAgent 式死代码（其 `vision.go` + 后端 image 分支因前端改走 Tesseract 而全部不可达）。
- **动态难度 / Skill 状态机 / 薄弱点 EMA**：属研读报告 P1 改造项，非本轮范围。
- **其 YAML 内容不照抄**：它的轮次是"一面/二面/三面"，我们是 6 阶段/5 轮双模式——轮次指令改用**轮次名关键词匹配**而非轮次序号，同时兼容两种模式。

## 三、技术方案

### 1. company_profiles.py（L2，仅依赖 L1）

```
backend/company_profiles.py      # 加载/匹配/片段生成
backend/company_profiles/*.yaml  # 数据文件（初始 3 份：字节/腾讯/阿里）
```

YAML schema：
```yaml
name: bytedance
display_name: "字节跳动"
match_keywords: ["字节", "ByteDance", "抖音"]   # JD 自动匹配用
role_description: |          # 人格层：整场注入
  ...
rounds:                      # 轮次行为层：按轮次名关键词匹配
  - match: ["技术"]          # 命中轮次名子串即注入
    instructions: |
      ...
  - match: ["项目"]
    instructions: |
      ...
evaluation_rubric: |         # 评估量表：进报告
  ...
```

核心 API：
- `list_profiles()` / `get_profile(name)` / `reload()`
- `match_profile(jd_text)` —— 关键词命中数最高者，0 命中返回 None
- `company_role_block(profile)` —— 【目标公司面试风格】片段
- `company_round_block(profile, round_name)` —— 命中轮次指令片段
- 容错：pyyaml 缺失 / 目录不存在 / 单文件解析失败 → 该文件跳过并告警，注册表退化为空，**不阻断主流程**（与 v6.2 简历追问点提取同款"可选增强"哲学）

### 2. 集成点（最小侵入）

| 文件 | 改动 |
|---|---|
| `schemas.py` | `SessionCreateRequest` 加 `company_profile: str \| None`；响应加 `company_profile` |
| `main.py` | create_session：显式选择 > `match_profile(jd)` 自动匹配 > None；新增 `GET /api/company-profiles` |
| `session.py` | `InterviewSession(company_profile=...)`；`get_interviewer_role_prompt()` 前置公司人格 + 本轮公司指令（既有 v6.3 角色卡语义不动，公司块插在最前——公司是"外层人格"，风格卡是"内层语气"） |
| `report.py` | `build_report` 挂 `company_rubric`（session 有配置时输出该公司的评估量表段） |
| `interview.js` / `api.js` | Step 2 加"🏢 目标公司风格"下拉（选项来自新 API，默认"自动匹配（按 JD）"） |

### 3. resume_parser 修复函数

```
_repair_pdf_text(text)         # 两阶段主入口，parse_pdf 尾部调用
  ├─ _rejoin_broken_lines()    # Phase 1：逆拼接（空行/编号项/全大写标题为硬断信号）
  └─ _restore_structure()      # Phase 2：复原断行（章节词表/·/-+CJK/嵌入编号项）
```

全部纯函数，`should_break` / `is_numbered_item` / `is_caps_heading` 可单测。

## 四、涉及的知识点

- YAML 数据驱动配置 + 目录热加载（interviewerAgent 的核心可扩展机制）
- 提示词分层注入顺序：公司人格 > 轮次指令 > 风格角色卡 > 任务指令
- PDF 排版文本的启发式修复：PDF 无语义换行信息，"何时该断/该连"只能靠语言规则近似
- L2 分层纪律：新模块禁 import L3/L4；`.importlinter` 契约同步更新
- 关键词匹配的打分函数（命中数最高者胜出，平手取注册顺序首个）

## 五、验收标准

1. `pytest tests/test_company_profiles.py tests/test_resume_parser.py -q` 全绿
2. 3 份 YAML 能被加载；坏 YAML / 缺 pyyaml 时降级不崩
3. JD 含"字节"时自动匹配 bytedance；显式传 `company_profile="tencent"` 优先
4. 会话角色卡含【目标公司面试风格】段；行为轮命中"技术"关键词的公司指令
5. 报告含公司评估量表
6. `python run.py lint` 分层契约通过
7. 前端下拉可选"自动匹配/具体公司/不启用"
