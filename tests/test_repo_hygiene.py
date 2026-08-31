"""仓库卫生回归（v7.2.2 新增）—— 临时脚本误提交是反复发作的老毛病。

历史事实：_commit.py（v6.2 期）与 _tmp_convert/（v4.0 期）曾被误提交进仓库，
各自靠一次专门的 chore 提交清理；.gitignore 的临时文件条目此前也是"出事一次
补一条"的一次性清单。本轮治本：

  1) .gitignore 通用化：根目录 `_` 前缀文件/目录一律视为临时产物（`/_*`）；
  2) 本测试把"根目录无临时文件/散落测试脚本/运行产物"钉进 CI 全量测试——
     今后任何误提交都会在 push 阶段红灯，而不是靠事后人肉发现。

约定：AI 会话产生的临时脚本一律放根目录并用 `_` 前缀命名（如 _scratch.py），
用完即删；确需长期保留的辅助脚本应给正式名字放进正式位置（如
tests/fixtures/generate_golden_samples.py）。
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 目前无豁免；确需在根目录保留 `_` 前缀跟踪文件时在此登记并写明原因
ALLOWED_ROOT_UNDERSCORE: set[str] = set()


def _tracked_files() -> list[str]:
    """git ls-files 的原始跟踪清单（Windows 下 git 会对非 ASCII 路径转义，但不影响根目录判断）。"""
    out = subprocess.run(
        ["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, check=True,
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
