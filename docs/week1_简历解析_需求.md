# Week1 需求文档：简历解析模块（resume_parser）

> 模块定位：上游输入模块，为问题生成 / 诊断引擎提供简历纯文本。

## 一、模块目标

将用户上传的简历文件解析为纯文本，支持 **PDF / DOCX / TXT** 三种常见格式，解析失败时返回可读的错误说明而非崩溃。

## 二、当前实现状态（骨架已就绪）

文件：`backend/resume_parser.py`，已实现：

- `parse_pdf(file_bytes)`：用 `PyPDF2.PdfReader` 逐页抽取文本并拼接。
- `parse_docx(file_bytes)`：用 `python-docx` 的 `Document` 遍历 `paragraphs` 抽取文本。
- `parse_resume(file_bytes, filename)`：按扩展名分派；`.txt` 直接 `decode('utf-8', errors='replace')`；不支持的格式返回 `[不支持的文件格式: ext]`；各解析器异常均被捕获并返回 `[XX 解析失败: e]` 字符串（不抛异常）。

## 三、技术方案

- **按扩展名分派**：`filename.lower().rsplit(".", 1)[-1]` 取扩展名路由到对应解析器。
- **二进制流处理**：接收 `bytes`，用 `io.BytesIO` 包裹后交给库解析，避免落盘。
- **失败兜底**：每个解析器 try/except 返回带原因的错误字符串，调用方（如 `main.py`）需识别这类 `[...]` 错误串并提示用户，而不是直接当文本喂给 LLM。
- **文本清洗**：`strip()` 去除首尾空白；空段落跳过。

## 四、涉及的知识点

- `PyPDF2` 的 PDF 文本抽取与局限性（扫描件/图片型 PDF 无法提取）。
- `python-docx` 的段落遍历与结构抽取。
- Python 二进制流 `io.BytesIO`、编码（`utf-8` + `errors='replace'`）。
- 防御式解析：异常捕获与用户可读的错误反馈。

## 五、待完善 / 优化点（后续迭代）

- [ ] 确认 `PyPDF2` / `python-docx` 已写入 `requirements.txt` 并安装（当前 `chat_json` 依赖见 `llm_client`）。
- [ ] 扫描件/图片型 PDF 无法抽取文本，需提示用户转为可文本化格式或接入 OCR（属范围外，需批准）。
- [ ] 长文本统一截断策略，与下游 `question_gen` / `diagnosis_engine` 的截断长度对齐。
- [ ] `.doc`（旧版二进制格式）目前走 docx 分支会失败，需单独处理或明确不支持。
- [ ] 解析结果结构化为 `{text, error}` 而非混用错误字符串，降低调用方判断成本。
