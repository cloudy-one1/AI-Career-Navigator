"""仓库卫生回归（v7.2.2 新增）—— 临时脚本误提交是反复发作的老毛病。

历史事实：_commit.py（v6.2 期）与 _tmp_convert/（v4.0 期）曾被误提交进仓库，
各自靠一次专门的 chore 提交清理；.gitignore 的临时文件条目此前也是"出事一次
补一条"的一次性清单。本轮治本：

  1) .gitignore 通用化：根目录 `_` 前缀文件/目录一律视为临时产物（`/_*`）；
  2) 本测试把"根目录无临时文件/散落测试脚本/运行产物"钉进 CI 全量测试——
     今后任何误提交都会在 push 阶段红灯，而不是靠事后人肉发现。

v8.4 增补第 4 条**根目录白名单**：前三条都是黑名单（禁 `_` 前缀 / 禁散落
test_*.py / 禁运行产物），拦不住"任意新散落文件"——v8.4 整理时根目录就躺着
`({`、`b.textContent)` 两个畸形文件、`upload_*.jpg` 两张对话附件、一份立项报告
docx 和一份竞品学习报告，全都"不违反任何一条黑名单"。黑名单只能针对已知模式，
白名单才能回答"这个文件凭什么在根目录"。

约定：AI 会话产生的临时脚本一律放根目录并用 `_` 前缀命名（如 _scratch.py），
用完即删；确需长期保留的辅助脚本应给正式名字放进正式位置（如
tests/fixtures/generate_golden_samples.py）。
**v8.8 对外文档范围调整**：CHANGELOG.md 与 CHARTER.md 已恢复跟踪——版本迭代叙事
与架构/决策记录是标准开源仓库的对外要素；README.md 承担快速开始与对外说明。
docs/（过程性资料）与 CODEBUDDY.md（AI 协作索引，只服务本机会话）仍停止跟踪
（.gitignore 已排除，文件保留在本地）。因此第 5 条的链接检查对 CHANGELOG / CHARTER
同样生效：它们不得链向未跟踪文件（涉及的 CODEBUDDY.md 已改为纯文本提及）。
"""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 目前无豁免；确需在根目录保留 `_` 前缀跟踪文件时在此登记并写明原因
ALLOWED_ROOT_UNDERSCORE: set[str] = set()

# 根目录白名单（v8.4）：凡是 git 跟踪的顶层条目，名字必须落在这两个集合之一。
# 新增工程文件/目录时在此登记并写明用途——登记成本 > 随手一放的收益，正是本条的目的。
ALLOWED_ROOT_FILES: set[str] = {
    ".dockerignore",      # 容器构建忽略清单
    ".env.example",       # 环境变量模板（真实 .env 不入库）
    ".gitattributes",     # 跨平台换行符统一为 LF
    ".gitignore",
    ".importlinter",      # 分层依赖契约（L1-L4）
    "CHANGELOG.md",       # [v8.8] 版本迭代叙事（对外可见，标准开源要素）
    "CHARTER.md",         # [v8.8] 不变宪章：产品命题 / 架构约束 / 决策记录 / 已知局限
    "Dockerfile",
    "LICENSE",
    "README.md",
    "docker-compose.yml",
    "requirements.txt",
    "run.py",             # 一键启动 + lint 子命令
}
ALLOWED_ROOT_DIRS: set[str] = {
    ".github",    # CI 工作流
    "backend",    # 后端
    "data",       # 运行时数据（整体 gitignore，列此仅为语义完整）
    "docs",       # 本地文档（整体 gitignore；留在白名单内是为了保住恢复跟踪这条路）
    "frontend",   # 前端
    "tests",      # 测试
}


def _tracked_files() -> list[str]:
    """git 跟踪清单（真实路径，非转义形式）。

    `core.quotepath=false` 是必需的：默认 git 会把非 ASCII 路径输出成八进制转义
    （`"docs/\\344\\272\\247...md"`），做字符串比对时会误判"文件未跟踪"。
    """
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=str(ROOT), capture_output=True, text=True, check=True,
        encoding="utf-8",
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def test_no_temp_files_tracked_at_root():
    """根目录不允许出现 `_` 前缀的跟踪文件（临时脚本/临时产物约定）。"""
    bad = [f for f in _tracked_files()
           if "/" not in f and f.startswith("_") and f not in ALLOWED_ROOT_UNDERSCORE]
    assert not bad, (
        f"根目录存在误提交的临时文件: {bad}。"
        "处理：删除或移入正式位置；git 历史里已有两次专门清理同类问题的提交，勿再复发。"
    )


def test_no_adhoc_test_scripts_at_root():
    """根目录不允许跟踪 test_*.py——测试一律进 tests/，避免 pytest 从根目录误收集。"""
    bad = [f for f in _tracked_files()
           if "/" not in f and f.startswith("test_") and f.endswith(".py")]
    assert not bad, f"根目录存在散落的测试脚本: {bad}（应移入 tests/）"


def test_no_runtime_artifacts_tracked():
    """运行产物（日志/数据库）不得入库——gitignore 之外的兜底断言。"""
    bad = [f for f in _tracked_files() if f.endswith((".log", ".db", ".sqlite3"))]
    assert not bad, f"跟踪了运行产物: {bad}"


def test_root_directory_whitelist():
    """根目录跟踪条目必须在白名单内——黑名单拦不住「任意新散落文件」。

    取每个跟踪路径的第一段即顶层条目（文件=自身，目录=目录名），与白名单求差。
    路径已从 `_tracked_files()` 拿到真实形式（非八进制转义）。
    """
    top_level = {f.split("/")[0] for f in _tracked_files()}
    allowed = ALLOWED_ROOT_FILES | ALLOWED_ROOT_DIRS
    bad = sorted(top_level - allowed)
    assert not bad, (
        f"根目录出现白名单外的跟踪条目: {bad}。"
        "处理：docs/ 与 CODEBUDDY.md 属本地资料，不得 git add；临时脚本用 `_` 前缀并尽快删除，"
        "确属工程文件的在 tests/test_repo_hygiene.py 的 ALLOWED_ROOT_FILES / "
        "ALLOWED_ROOT_DIRS 登记并写明用途。v8.4 整理时根目录曾散落畸形文件、"
        "对话附件与两份文档——黑名单三条全不违反，正是补这条白名单的原因。"
    )


def test_markdown_links_point_to_tracked_files():
    """被跟踪的 Markdown 里，相对链接的目标必须也被跟踪——否则推到远端就是 404。

    背景：过程性资料（docs/archive/、docs/research/、演示材料）退出
    git 索引后**仍留在本地工作区**——链接到它们在本机一切正常，坏链接只在 GitHub
    上暴露，靠人眼看不出来。本条把"公开文档不得链到未公开文件"钉进 CI。

    只查相对链接：外链（http/mailto）与页内锚点（#xxx）不在此列。
    """
    tracked = set(_tracked_files())
    bad = []
    for md in sorted(f for f in tracked if f.endswith(".md")):
        path = ROOT / md
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            raw = match.group(1).strip()
            if raw.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = raw.split("#")[0]
            if not target:
                continue
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(md), target)
            ).replace(os.sep, "/")
            if resolved not in tracked:
                bad.append((md, target))
    assert not bad, (
        f"以下 Markdown 链接指向未被跟踪的文件（推到 GitHub 会 404）: "
        f"{['%s -> %s' % (s, d) for s, d in bad]}。"
        "处理：目标属过程性资料的，改用纯文本写文件名并注明「本地文档，未入库」；"
        "确需公开的，把对应路径从 .gitignore 移除并 git add。"
    )
