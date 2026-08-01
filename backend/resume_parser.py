"""
简历解析器：支持 PDF、DOCX、TXT 三种格式。
"""

import io
import logging

logger = logging.getLogger(__name__)


def parse_pdf(file_bytes: bytes) -> str:
    """解析 PDF 文件，提取纯文本。"""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return f"[PDF 解析失败: {e}]"


def parse_docx(file_bytes: bytes) -> str:
    """解析 DOCX 文件，提取纯文本。"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.error(f"DOCX 解析失败: {e}")
        return f"[DOCX 解析失败: {e}]"


def parse_resume(file_bytes: bytes | str, filename: str) -> str:
    """
    根据文件扩展名分派解析器。
    返回解析出的纯文本，解析失败则返回错误信息。
    """
    # 内联文本模式（已是 str），直接返回
    if isinstance(file_bytes, str):
        return file_bytes.strip()

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        return parse_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return parse_docx(file_bytes)
    elif ext == "txt":
        return file_bytes.decode("utf-8", errors="replace").strip()
    else:
        return f"[不支持的文件格式: {ext}]"
