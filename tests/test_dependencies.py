"""依赖声明完整性检查（v8.10）。

存在理由：`resume_parser.parse_pdf` 曾 `from PyPDF2 import PdfReader`，而 PyPDF2 既不在
requirements.txt、也不是任何已声明包的传递依赖 —— 于是按 README 步骤装出的干净环境
（CI / Docker / 评委本机）里 PDF 简历解析必然失败，而本机装了 PyPDF2 所以全程无感。
"本机绿、干净环境红"这类问题只有把声明与实际 import 对齐断言才能挡住。
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

# 直接声明在 requirements.txt 中、但 import 名与包名不同的三方库
ALIASES = {
    "docx": "python-docx",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "playwright_stealth": "playwright-stealth",
}

# 允许经由已声明包间接引入的传递依赖（附来源，避免被当成"可以随便 import"）
TRANSITIVE = {
    "starlette": "fastapi",
    "anyio": "fastapi / httpx",
    "sniffio": "anyio",
    "h11": "uvicorn / httpx",
    "httpcore": "httpx",
    "certifi": "httpx",
    "idna": "httpx",
    "typing_extensions": "pydantic / fastapi",
    "pydantic_core": "pydantic",
    "annotated_types": "pydantic",
    "pdfminer": "pdfplumber",
    "pypdfium2": "pdfplumber",
    "PIL": "pdfplumber",
    "jinja2": "fastapi 模板响应",
    "click": "uvicorn / slowapi",
    "colorama": "click",
    "websockets": "声明包同名",
}


def _norm(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _declared() -> set[str]:
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        for sep in (">=", "==", "<=", "~=", ">", "<", "["):
            line = line.split(sep)[0]
        names.add(_norm(line))
    return names


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_backend_has_no_undeclared_runtime_import():
    declared = _declared()
    offenders = []
    for py in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        for mod in _top_level_imports(py):
            if mod in sys.stdlib_module_names or mod == "backend":
                continue
            dist = _norm(ALIASES.get(mod, mod))
            if dist in declared or mod in TRANSITIVE:
                continue
            offenders.append(f"{py.relative_to(ROOT)}: import {mod}")
    assert not offenders, (
        "以下 import 未在 requirements.txt 声明，干净环境会 ImportError："
        + "; ".join(offenders)
    )


def test_declared_pdf_dependency_is_the_one_actually_used():
    """钉住 v8.10 修复：解析 PDF 用声明过的 pdfplumber，不再用未声明的 PyPDF2。

    按 AST 里的真实 import 判断，而不是全文搜字符串 —— 解释性注释里提到 PyPDF2 是正常的。
    """
    mods = _top_level_imports(BACKEND / "resume_parser.py")
    assert "pdfplumber" in mods, "parse_pdf 应 import requirements 中声明的 pdfplumber"
    assert "PyPDF2" not in mods and "pypdf" not in mods, (
        "PyPDF2 未被声明，重新出现即回到干净环境必崩的状态"
    )


def test_pdfplumber_is_importable():
    """声明了就要能装能 import：CI 只装 requirements，这条即等价于干净环境自检。"""
    pytest.importorskip("pdfplumber")
    import pdfplumber  # noqa: F401


def _constraints() -> dict[str, str]:
    pins = {}
    for line in (ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or "==" not in line:
            continue
        name, _, version = line.partition("==")
        pins[_norm(name)] = version.strip()
    return pins


def test_constraints_cover_every_declared_package():
    """v8.13：requirements 声明的每个包都必须被 constraints.txt 钉住。

    存在理由：constraints 的全部意义是"装到什么版本 = 被评审过的决定"——
    requirements 新增声明而忘记同步 constraints 时，新包的版本回到每天在漂的
    状态，锁定静默失效。删掉 constraints 里任何一条被声明包的本测试即变红。
    """
    pins = _constraints()
    assert pins, "constraints.txt 为空或格式损坏（应全部为 name==version）"
    missing = sorted(_declared() - set(pins))
    assert not missing, (
        "以下 requirements.txt 声明的包没有被 constraints.txt 钉住，"
        f"新装环境的版本将脱离评审: {missing}"
    )


def test_constraints_are_exact_pins():
    """必须是 == 精确钉版：范围约束（>= / >=,<）会让解析结果继续漂，锁定名存实亡。"""
    for line in (ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        assert "==" in line, f"constraints.txt 中出现非精确钉版行: {line!r}"
        version_part = line.split("==", 1)[1]
        assert not any(op in version_part for op in (">", "<", ",", "*")), (
            f"constraints.txt 的钉版行带了范围或通配后缀: {line!r}"
        )
