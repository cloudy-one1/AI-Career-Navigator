"""文档台账门禁（v8.24）——把 CONTRIBUTING"文档里的数字必须实测后写入"变成机器执行。

历史事故（v8.23 审查发现）：
- HTTP 端点数在 README / architecture.md / API.md 三处齐声写 59，实际 63；
- pytest 用例数四个文档四个口径（1098 / 1134 / 1219 / 1234），无一互引；
- API.md 自己的表格都列了 62 行，v8.22 新增端点没登记。

明细永远比台账新，靠人肉维护台账必然漂移。本文件把台账钉回明细：
路由数用 AST 现数（零依赖、毫秒级），用例数用 --collect-only 子进程现数
（约 6s，一次付费）。数字变了测试就红——要么更新文档，要么承认口径变了。
"""
import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
_HTTP_DECORATORS = {"get", "post", "put", "delete", "patch"}
# 容忍文档里的零碎修饰（如 architecture.md 的 "63 个 `/api` HTTP 端点"）
_HTTP_ENDPOINT_CLAIM = re.compile(r"(\d+)\s*个[^。\n]{0,30}?HTTP\s*端点")


def _count_routes() -> tuple[int, int, int]:
    """AST 现数 backend/routers/ 的 @router.get/post/put/delete/patch 与 websocket。"""
    http = ws = routers = 0
    for f in (ROOT / "backend" / "routers").glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        file_http = file_ws = 0
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                    attr, obj = d.func.attr, d.func.value
                    if attr in _HTTP_DECORATORS and isinstance(obj, ast.Name) and obj.id == "router":
                        file_http += 1
                    elif attr == "websocket":
                        file_ws += 1
        if file_http or file_ws:
            routers += 1
        http += file_http
        ws += file_ws
    return http, ws, routers


def _count_collected() -> int:
    """pytest --collect-only 现数用例总数（子进程，避开运行中套件的自身干扰）。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "tests/", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    m = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    assert m, f"--collect-only 未能给出用例数（exit={proc.returncode}）：{proc.stderr[-400:]}"
    return int(m.group(1))


def _doc(root_relative: str) -> str:
    return (ROOT / root_relative).read_text(encoding="utf-8")


class TestEndpointCounts:
    """三份文档声明的端点数必须与 backend/routers 逐一对齐。"""

    def test_api_md(self):
        text = _doc("docs/API.md")
        m = _HTTP_ENDPOINT_CLAIM.search(text)
        assert m, "API.md 头部应包含『N 个 HTTP 端点』声明"
        http, ws, routers = _count_routes()
        assert int(m.group(1)) == http, f"API.md 端点数 {m.group(1)} != 实际 {http}"
        m_ws = re.search(r"(\d+)\s*个\s*WebSocket", text)
        assert m_ws and int(m_ws.group(1)) == ws
        m_r = re.search(r"只计\s*(\d+)\s*个\s*router", text)
        assert m_r, "API.md 应注明 router 计数口径"
        assert int(m_r.group(1)) == routers, f"API.md router 数 {m_r.group(1)} != 实际 {routers}"

    def test_readme_docs_table(self):
        text = _doc("README.md")
        m = _HTTP_ENDPOINT_CLAIM.search(text)
        assert m, "README 文档表应包含端点数声明"
        assert int(m.group(1)) == _count_routes()[0]

    def test_architecture_md(self):
        text = _doc("docs/architecture.md")
        m = _HTTP_ENDPOINT_CLAIM.search(text)
        assert m, "architecture.md 应包含端点数声明"
        assert int(m.group(1)) == _count_routes()[0]


class TestTestCaseCounts:
    """测试规模台账：README 徽章是下限，testing.md 是实数（随套件增长需同步）。"""

    def test_readme_badge_is_floor(self):
        assert _count_collected() >= 1000, "README 徽章 'tests-1000+' 的下限不再成立"

    def test_testing_md_matches_collection(self):
        text = _doc("docs/testing.md")
        m = re.search(r"(\d+)\s*个\s*pytest\s*用例", text)
        assert m, "testing.md 应包含『N 个 pytest 用例』实数声明"
        actual = _count_collected()
        assert int(m.group(1)) == actual, (
            f"testing.md 用例数 {m.group(1)} != 实测 {actual}——新增用例后请同步台账"
            "（口径：pytest --collect-only 实数，写入时注明实测日期）")
