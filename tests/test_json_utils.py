"""
safe_json_extract 四级容错测试（v6.0，对标 career-copilot safeJsonParse）。

覆盖：L1 直接解析 / L2 提取配平 {} 块（围栏、前后缀文本）/ L3 字符级修复
（字符串内裸换行、未转义引号、截断补括号）/ L4 宽松解析（尾逗号、单引号、字面量）。
"""

from backend.llm_client import safe_json_extract


class TestL1Direct:
    def test_direct_object(self):
        assert safe_json_extract('{"a": 1}') == {"a": 1}

    def test_direct_list(self):
        assert safe_json_extract('[1, 2]') == [1, 2]

    def test_none_and_empty(self):
        assert safe_json_extract(None) is None
        assert safe_json_extract("") is None
        assert safe_json_extract("   ") is None

    def test_dict_passthrough(self):
        assert safe_json_extract({"a": 1}) == {"a": 1}


class TestL2BalancedExtract:
    def test_markdown_fence(self):
        raw = '```json\n{"a": 1, "b": "x"}\n```'
        assert safe_json_extract(raw) == {"a": 1, "b": "x"}

    def test_prefix_suffix_text(self):
        raw = '好的，以下是结果：{"a": 1} 请查收。'
        assert safe_json_extract(raw) == {"a": 1}

    def test_nested_braces_in_strings(self):
        raw = '前言 {"s": "包含 } 和 { 的文本", "n": 2} 后缀'
        assert safe_json_extract(raw) == {"s": "包含 } 和 { 的文本", "n": 2}


class TestL3Repair:
    def test_truncated_object_closed(self):
        raw = '{"a": 1, "b": {"c": [1, 2'
        data = safe_json_extract(raw)
        assert data is not None
        assert data["a"] == 1
        assert data["b"]["c"] == [1, 2]

    def test_truncated_string_closed(self):
        raw = '{"a": "未闭合的字符'
        data = safe_json_extract(raw)
        assert data is not None
        assert data["a"].startswith("未闭合")

    def test_raw_newline_inside_string(self):
        raw = '{"a": "第一行\n第二行"}'
        data = safe_json_extract(raw)
        assert data == {"a": "第一行\n第二行"}

    def test_unescaped_quotes_inside_string(self):
        raw = '{"quote": "他说"你好"然后离开了", "n": 1}'
        data = safe_json_extract(raw)
        assert data is not None
        assert "你好" in data["quote"]
        assert data["n"] == 1

    def test_tab_inside_string(self):
        raw = '{"a": "列1\t列2"}'
        data = safe_json_extract(raw)
        assert data == {"a": "列1\t列2"}


class TestL4Loose:
    def test_trailing_comma(self):
        assert safe_json_extract('{"a": 1, "b": [1, 2,]}') == {"a": 1, "b": [1, 2]}

    def test_single_quoted_values(self):
        assert safe_json_extract("{'a': 'x', 'n': 1}") == {"a": "x", "n": 1}

    def test_python_literals(self):
        assert safe_json_extract('{"t": True, "f": False, "z": None}') == {
            "t": True, "f": False, "z": None,
        }

    def test_js_undefined(self):
        assert safe_json_extract('{"u": undefined}') == {"u": None}

    def test_apostrophe_not_mangled(self):
        # 正文撇号不应被单引号转换破坏（it's 出现在双引号字符串内）
        data = safe_json_extract('{"a": "it\'s ok", "n": 1,}')
        assert data == {"a": "it's ok", "n": 1}


class TestHopeless:
    def test_no_braces_returns_none(self):
        assert safe_json_extract("完全不是 JSON 的文本") is None

    def test_garbage_returns_none(self):
        assert safe_json_extract("{这不是json") is None
