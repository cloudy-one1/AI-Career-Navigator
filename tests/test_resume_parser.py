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
