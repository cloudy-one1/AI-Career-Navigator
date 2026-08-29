"""
resume_parser.py 测试：parse_resume / parse_pdf / parse_docx。
"""

import pytest
from backend import resume_parser


SAMPLE_TXT = """
张三
Python 后端开发工程师
13800000000 | zhangsan@example.com

教育经历：
北京大学，计算机科学与技术，本科，2020-2024

工作经验：
阿里巴巴 | Python 后端开发 | 2024-至今
- 负责电商推荐系统的后端 API 开发
- 优化数据库查询，将 QPS 提升 40%
"""


class TestParseResume:
    """parse_resume() — 按文件名自动分派解析器"""

    def test_txt_file_parsed(self):
        """filename=.txt → 直接返回文本"""
        result = resume_parser.parse_resume(SAMPLE_TXT, "resume.txt")
        assert "张三" in result
        assert "Python" in result
        assert "北京大学" in result

    def test_txt_uppercase_extension(self):
        result = resume_parser.parse_resume(SAMPLE_TXT, "RESUME.TXT")
        assert "张三" in result

    def test_empty_txt(self):
        result = resume_parser.parse_resume("", "empty.txt")
        assert result == ""

    def test_string_passed_as_bytes_handled(self):
        """str 类型不调用 .decode()，直接返回"""
        result = resume_parser.parse_resume("我是一名软件工程师", "cv.txt")
        assert "软件工程师" in result

    def test_unknown_extension_treated_as_txt(self):
        """未知扩展名当作纯文本处理"""
        result = resume_parser.parse_resume(SAMPLE_TXT, "resume.dat")
        assert "张三" in result

    def test_none_filename_treated_as_txt(self):
        """filename=None 应处理为纯文本"""
        result = resume_parser.parse_resume("hello world", None)
        assert "hello world" in result


class TestPDFDetection:
    """parse_resume PDF 分支（传入 bytes）"""

    def test_pdf_bytes_header(self):
        """PDF 以 %PDF- 开头"""
        fake_pdf = b"%PDF-1.4\nsome content here"
        result = resume_parser.parse_resume(fake_pdf, "resume.pdf")
        # PDF 二进制解析会提取文本或返回空
        assert isinstance(result, str)

    def test_binary_not_pdf_not_docx(self):
        """非 PDF/DOCX 的二进制默认当文本处理"""
        result = resume_parser.parse_resume(b"\x01\x02\x03\x04", "data.bin")
        assert isinstance(result, str)


class TestDOCXDetection:
    """parse_resume DOCX 分支（传入 bytes）"""

    def test_docx_bytes_header(self):
        """DOCX 以 PK 开头（ZIP）"""
        fake_docx = b"PK\x03\x04some zip content"
        result = resume_parser.parse_resume(fake_docx, "resume.docx")
        assert isinstance(result, str)


# ===== v6.5: PDF 文本两阶段修复（借鉴 interviewerAgent internal/extract/pdf.go）=====


class TestNumberedItemDetection:
    """_is_numbered_item — Phase 1 硬断信号之一"""

    @pytest.mark.parametrize("s", ["1. 完成xx", "2、负责yy", "3) 测试zz", "（4) 描述ww", "① 首先", "⑫ 最后"])
    def test_numbered_items(self, s):
        assert resume_parser._is_numbered_item(s)

    @pytest.mark.parametrize("s", ["QPS 提升", "ab", "xx", "3.5xx", "2024年", "（）"])
    def test_non_numbered_lines(self, s):
        assert not resume_parser._is_numbered_item(s)

    def test_short_line_never_numbered(self):
        """<3 字符不判定（防 "1." 单独成行误判）"""
        assert not resume_parser._is_numbered_item("1.")


class TestCapsHeadingDetection:
    """_is_caps_heading — Phase 1 硬断信号之二"""

    def test_all_caps_heading(self):
        assert resume_parser._is_caps_heading("EDUCATION")
        assert resume_parser._is_caps_heading("WORK EXPERIENCE")

    def test_short_acronym_not_heading(self):
        """<6 字母的缩写不判定（API/SQL/CV 不能当标题）"""
        assert not resume_parser._is_caps_heading("API")
        assert not resume_parser._is_caps_heading("SQL DB")

    def test_chinese_line_not_heading(self):
        assert not resume_parser._is_caps_heading("工作经历")

    def test_mixed_case_not_heading(self):
        assert not resume_parser._is_caps_heading("Education")


class TestRejoinBrokenLines:
    """Phase 1：软换行拼接"""

    def test_soft_wrapped_chinese_joined(self):
        text = "负责电商推荐系统\n的后端 API 开发\n与性能优化"
        out = resume_parser._rejoin_broken_lines(text)
        assert out == "负责电商推荐系统的后端 API 开发与性能优化"

    def test_ascii_words_get_space(self):
        text = "Python\nBackend\nEngineer"
        out = resume_parser._rejoin_broken_lines(text)
        assert out == "Python Backend Engineer"

    def test_numbered_item_keeps_own_line(self):
        text = "职责如下\n1. 负责服务开发\n2、负责稳定性建设"
        out = resume_parser._rejoin_broken_lines(text)
        lines = [ln for ln in out.split("\n") if ln]
        assert len(lines) == 3

    def test_blank_lines_preserved(self):
        text = "第一段\n\n第二段"
        out = resume_parser._rejoin_broken_lines(text)
        assert "\n\n" in out

    def test_caps_heading_keeps_own_line(self):
        text = "个人技能\nEDUCATION\n北京大学"
        out = resume_parser._rejoin_broken_lines(text)
        assert "EDUCATION" in out.split("\n")


class TestRestoreStructure:
    """Phase 2：结构断行复原"""

    def test_chinese_header_gets_blank_lines(self):
        text = "基本信息张三后端工程师教育背景北京大学"
        out = resume_parser._restore_structure(text)
        assert "\n教育背景\n" in out

    def test_bullet_dot_gets_newline(self):
        text = "成果如下·优化QPS·降低延迟"
        out = resume_parser._restore_structure(text)
        assert "\n·优化QPS" in out

    def test_dash_before_cjk_gets_newline(self):
        text = "工作内容- 负责网关开发- 负责限流"
        out = resume_parser._restore_structure(text)
        assert "\n- 负责网关开发" in out

    def test_date_range_not_broken(self):
        """2023-09 这类日期区间不含 CJK，不受 '-' 规则影响"""
        text = "2023-09 至 2024-06 某公司"
        out = resume_parser._restore_structure(text)
        assert "2023-09" in out
        assert "\n09" not in out

    def test_embedded_numbered_item_gets_newline(self):
        text = "完成了两件事。1.重构网关。2.上线灰度。"
        out = resume_parser._restore_structure(text)
        assert "\n1.重构网关" in out
        assert "\n2.上线灰度" in out

    def test_decimal_not_treated_as_item(self):
        """3.14 / 3.5 这类小数不触发断行"""
        text = "圆周率是3.14这个数字"
        out = resume_parser._split_embedded_numbered_items(text)
        assert "\n" not in out

    def test_collapse_extra_blank_lines(self):
        text = "a\n\n\n\nb"
        out = resume_parser._restore_structure(text)
        assert "\n\n\n" not in out


class TestRepairPdfText:
    """端到端：parse_pdf 输出的粘连文本被修复"""

    def test_glued_resume_repaired(self):
        glued = ("张三 后端工程师13800000000"
                 "工作经历某某公司 后端开发- 负责网关开发- 优化QPS提升40%")
        out = resume_parser._repair_pdf_text(glued)
        assert "\n工作经历\n" in out
        assert "\n- 负责网关开发" in out
        assert "\n- 优化QPS" in out

    def test_already_clean_text_unchanged_semantically(self):
        clean = "张三\n\n工作经历\n某某公司"
        out = resume_parser._repair_pdf_text(clean)
        assert "张三" in out and "工作经历" in out and "某某公司" in out

    def test_empty_text_passthrough(self):
        assert resume_parser._repair_pdf_text("") == ""
        assert resume_parser._repair_pdf_text("   ") == "   "
