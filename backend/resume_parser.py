"""
简历解析器：支持 PDF、DOCX、TXT 三种格式。

v6.2 新增：简历解析阶段前置产出追问点（deepDivePoints / vaguePoints），
借鉴 GrillMind —— 让面试官的追问在开问之前就有数据支撑，而非临场泛泛而问。
追问点提取是**可选增强**：LLM 不可用/解析失败时返回空结构，不影响简历解析主流程。
"""

import io
import logging

from .resume_anchors import merge_anchor_sources

logger = logging.getLogger(__name__)

# ===== v6.2: 简历前置追问点提取 =====

RESUME_POINTS_SYSTEM_PROMPT = """你是一位资深技术面试官，擅长从简历中预判"该问什么"。
请阅读候选人简历，输出两类追问线索，供后续面试提问使用。

【deep_dive_points｜值得深挖的点】
候选人**写了但细节不足**的内容：能体现真实水平、需要当面试探真伪与深度的点。
例如："提到将接口 P99 从 800ms 降到 200ms，但未说明优化手段"、"写了'负责架构设计'，需核实设计边界与决策权"。
要点：必须锚定简历里的具体名词/数字/项目名，越具体越好。

【vague_points｜可疑或模糊的点】
表述含糊、存在包装嫌疑、或缺少关键约束的内容。
例如："项目时间跨度与成果量级不匹配"、"堆砌技术名词但无落地场景"、"职责描述只有'参与'而无个人贡献"。
要点：指出模糊之处，不要凭常识编造简历中不存在的信息。

【anchors｜锚点类型分类（v6.3）】
把上面两类点按"该往哪个方向追问"归入五类，每类的追问方向完全不同：
- tech_choice（技术选型）：提到了具体技术/框架/工具。追问方向：为什么选它不选别的、原理、限制、踩坑。
- metric（量化数据）：出现了数字、百分比、性能指标。**简历中出现的每个数字都是高价值追问点**。追问方向：怎么测的、AB 还是前后对比、峰值、置信度。
- architecture（架构设计）：描述了系统/架构/重构/从0到1。追问方向：怎么设计的、为什么、瓶颈、老架构问题、迁移。
- business_decision（业务决策）：涉及业务判断/主导/优先级/指标归因。追问方向：为什么做、谁发起、优先级、归因、自然增长多少。
- team（团队管理）：涉及带人/跨团队协作/推广。追问方向：怎么组建分工、跨团队难点、怎么推动。

输出严格 JSON：
{"deep_dive_points": ["深挖点1"],
 "vague_points": ["模糊点1"],
 "anchors": {"tech_choice": ["点了"], "metric": ["点了"], "architecture": [], "business_decision": [], "team": []}}

约束：
1. deep 与 vague 两类合计不超过 8 条，每类不超过 5 条；anchors 每类不超过 3 条；
2. anchors 中的条目**必须来自** deep_dive_points / vague_points 的原文，不要另写新点；
3. 每条控制在 40 字以内，只写"该问什么 + 为什么可疑"，不要写完整问题；
4. **严禁编造简历中不存在的项目、公司或数字** —— 只依据简历原文，信息不足就少输出；
5. 若简历内容过少无法提取，返回空数组，不要凑数；anchors 无法确定类别时留空数组（宁缺勿错分）。"""

RESUME_POINTS_USER_PROMPT = """请提取以下简历的追问线索。

【候选人简历】
{resume}
{jd}
只输出 JSON，不要任何额外文字。"""

_MAX_POINTS_PER_TYPE = 5
_MAX_POINT_LEN = 80
# 简历正文过短时没有可提取的线索，直接跳过（省一次 LLM 调用，也避免模型凑数编造）
MIN_RESUME_CHARS = 50


def _clean_points(items, limit: int = _MAX_POINTS_PER_TYPE) -> list[str]:
    """清洗 LLM 产出的追问点列表：去空、去重、截断保序。"""
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for x in items:
        s = str(x).strip().lstrip("-•·").strip()
        if not s or len(s) > _MAX_POINT_LEN:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def extract_interview_points(resume_text: str, llm_client=None, jd_text: str = "") -> dict:
    """
    v6.2: 简历解析阶段前置产出追问点（借鉴 GrillMind 的 deepDivePoints/vaguePoints）。
    v6.3: 追加 anchors —— 把追问点按五类锚点分类（技术选型/量化数据/架构设计/业务决策/团队管理），
          每类绑定一条追问方向。二分法只能定位"哪里值得问"，五分类才回答"该往哪个方向问"。

    返回 {"deep_dive_points": [...], "vague_points": [...], "anchors": {五类}}。
    设计要点：
      - 纯离线解析（PDF/DOCX 文本提取）之外的一次轻量 LLM 调用，与 resume_text 解耦；
      - 失败一律降级为空结构（{}），不阻断简历上传与面试创建；
      - anchors 若模型未产出/格式不符，用 resume_anchors 的关键词规则对 deep/vague 兜底分类，
        保证下游拿到的始终是完整的五类结构；
      - 由调用方（main.py）决定何时调用，模块本身不 import L3/L4。
    """
    if not resume_text or not resume_text.strip() or llm_client is None:
        return {}
    if len(resume_text.strip()) < MIN_RESUME_CHARS:
        logger.debug("简历正文过短，跳过追问点提取")
        return {}

    jd_block = f"\n【岗位描述】\n{jd_text[:1000]}" if jd_text and jd_text.strip() else ""
    try:
        raw = llm_client.chat_json(
            RESUME_POINTS_SYSTEM_PROMPT,
            RESUME_POINTS_USER_PROMPT.format(resume=resume_text[:4000], jd=jd_block),
            0.3,
            1200,      # v6.3: 输出多了一层 anchors，token 上限相应上调
            "parse",   # v6.2: 任务级模型绑定（简历解析）
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"简历追问点提取失败，降级为空: {e}")
        return {}

    if not isinstance(raw, dict):
        return {}

    deep = _clean_points(raw.get("deep_dive_points"))
    vague = _clean_points(raw.get("vague_points"))
    if not deep and not vague:
        return {}

    points = {
        "deep_dive_points": deep,
        "vague_points": vague,
        # v6.3: LLM 未产出 anchors 时，由规则分类补齐（路径 2 兜底）
        "anchors": merge_anchor_sources(raw.get("anchors"), deep + vague),
    }
    logger.info(
        f"简历追问点提取完成: 深挖 {len(deep)} 条 / 模糊 {len(vague)} 条 / "
        f"锚点分类 {sum(len(v) for v in points['anchors'].values())} 条"
    )
    return points


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
