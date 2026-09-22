"""分层门禁的有效性自测（v8.10）。

存在理由：`python -m importlinter.cli lint` 形式**从不执行检查**（importlinter/cli.py
无 `__main__` 守卫，只导入即以 0 退出），而 run.py 与 CI 一直用的就是它——门禁空转了
若干版本却全程绿灯。这类"配置写了 = 已强制"的缺口无法靠契约本身暴露，只能反向钉：
先证明一个已知越层的样本会让门禁变红，才有资格说本仓库的绿是有效的绿。
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("importlinter", reason="dev 依赖 import-linter 未安装")

ROOT = str(Path(__file__).resolve().parents[1])

LINT_ENTRY = (
    "from importlinter.cli import lint_imports_command;"
    "lint_imports_command.main(prog_name='lint-imports')"
)


def _run_lint(cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", LINT_ENTRY],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_repo_contract_kept_and_actually_analyzed():
    """本仓库契约通过，且进程真的分析过文件（空转的输出里不会有 Analyzed）。"""
    proc = _run_lint(ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Analyzed" in proc.stdout, "门禁疑似空转（未分析任何文件）"
    assert "KEPT" in proc.stdout


def test_gate_goes_red_on_known_violation(tmp_path):
    """故意越层的样本必须让门禁变红——否则上一个用例的绿毫无意义。"""
    (tmp_path / "viol").mkdir()
    (tmp_path / "viol" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "viol" / "high.py").write_text("VALUE = 1\n", encoding="utf-8")
    # 低层 import 高层：契约声明 high 在上、low 在下，此 import 为越层
    (tmp_path / "viol" / "low.py").write_text(
        "from viol.high import VALUE\n", encoding="utf-8"
    )
    (tmp_path / ".importlinter").write_text(
        textwrap.dedent(
            """\
            [importlinter]
            root_package = viol

            [importlinter:contract:selftest]
            name = 自测分层契约
            type = layers
            layers =
                viol.high
                viol.low
            """
        ),
        encoding="utf-8",
    )
    proc = _run_lint(str(tmp_path))
    assert proc.returncode != 0, "门禁无法识别已知越层，说明它没有在检查"
    assert "not allowed to import" in proc.stdout
