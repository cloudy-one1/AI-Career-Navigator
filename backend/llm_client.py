"""
LLM 调用封装：OpenAI 兼容接口 + 流式输出支持。
v2.1: 多 AI 后端可切换（DeepSeek / Qwen / 智谱 / OpenAI）。
v6.0: Provider 注册表自动探测（AI_PROVIDER=auto）+ LLM 输出 JSON 四级容错提取
      （对标 career-copilot 的 PROVIDER_REGISTRY / safeJsonParse）。
"""

import json
import logging
import re
from openai import OpenAI, AsyncOpenAI
from .config import config, validate_api_key

logger = logging.getLogger(__name__)

# v6.0: Key 校验下沉到 config 层（注册表所在层，供 AI_PROVIDER_RESOLVED 自动探测复用）；
# 此处保留别名，兼容既有调用方与测试（from backend.llm_client import _api_key_issue）。
_api_key_issue = validate_api_key


# ===== v6.0: LLM 输出 JSON 四级容错提取 =====
# 对标 career-copilot safeJsonParse：
#   L1 直接解析 → L2 提取首个配平 {} 块 → L3 字符级修复 → L4 宽松解析

def _extract_balanced_json(s: str) -> str | None:
    """从 s 中提取第一个字符串感知、深度配平的 {...} 块；未配平（截断）返回 None。"""
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _repair_json_text(s: str) -> str:
    """L3 字符级修复：转义字符串内未转义引号与裸换行/制表符，闭合截断的括号。

    引号判定启发式：字符串内部的 `"` 若其后第一个非空白字符不是 , } ] : 或结尾，
    则视为未转义的字符串内引号（如 `"他说"你好"然后"`），转义之。
    """
    n = len(s)
    out: list[str] = []
    i = 0
    in_str = False
    esc = False
    stack: list[str] = []  # 字符串外未闭合的 } ]
    while i < n:
        ch = s[i]
        if in_str:
            if esc:
                esc = False
                out.append(ch)
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                if i + 1 < n:
                    out.append(s[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if ch == '"':
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                if j >= n or s[j] in ",}]:)":
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')  # 字符串内未转义引号
                i += 1
                continue
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                pass
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
            i += 1
            continue
        # 字符串外
        if ch == '"':
            in_str = True
            esc = False
            out.append(ch)
        elif ch == "{":
            stack.append("}")
            out.append(ch)
        elif ch == "[":
            stack.append("]")
            out.append(ch)
        elif ch == "}":
            if stack and stack[-1] == "}":
                stack.pop()
            out.append(ch)
        elif ch == "]":
            if stack and stack[-1] == "]":
                stack.pop()
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    if in_str:
        out.append('"')  # 截断在字符串中 → 补闭合引号
    while stack:
        out.append(stack.pop())  # 截断在结构中 → 逆序补闭合括号
    return "".join(out)


_LOOSE_VALUE_QUOTE_RE = re.compile(r"([{,:\[]\s*)'((?:[^'\\]|\\.)*)'")
_LOOSE_LITERAL_RE = re.compile(r"\b(True|False|None|undefined)\b")
_LOOSE_LITERAL_MAP = {"True": "true", "False": "false", "None": "null", "undefined": "null"}


def _loose_json(s: str) -> str:
    """L4 宽松解析：去尾逗号、值位单引号转双引号、Python/JS 字面量转 JSON 字面量。"""
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # 仅转换"值位置"的单引号串（前导为 { , : [ ），避免误伤正文中的 it's 等撇号
    s = _LOOSE_VALUE_QUOTE_RE.sub(r'\1"\2"', s)
    s = _LOOSE_LITERAL_RE.sub(lambda m: _LOOSE_LITERAL_MAP[m.group(1)], s)
    return s


def safe_json_extract(raw) -> dict | list | None:
    """LLM 输出 JSON 四级容错提取（L1 直接解析 → L2 提取{}块 → L3 修复 → L4 宽松）。

    返回解析出的 dict/list；四级全部失败返回 None。
    全项目所有"解析 LLM 输出"的入口统一走本函数（chat_json / diagnosis_engine 等）。
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    s = str(raw).strip()
    if not s:
        return None

    # L1: 直接解析
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass

    # L2: 提取首个配平 {} 块（兼容 markdown 围栏 / 前后缀说明文字）
    block = _extract_balanced_json(s)
    if block:
        try:
            return json.loads(block)
        except (json.JSONDecodeError, ValueError):
            pass

    # L3: 字符级修复后解析（截断时取首个 { 到结尾，闭合括号）
    start = s.find("{")
    if start == -1:
        return None
    candidate = block if block else s[start:]
    repaired = _repair_json_text(candidate)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        pass

    # L4: 宽松解析（尾逗号 / 单引号 / 字面量）
    try:
        return json.loads(_loose_json(repaired))
    except (json.JSONDecodeError, ValueError):
        return None


class _Candidate:
    """fallback 候选：独立的 provider/model 及其专属 OpenAI 客户端。"""

    __slots__ = ("provider", "model", "client", "async_client")

    def __init__(self, provider, model, client, async_client):
        self.provider = provider
        self.model = model
        self.client = client                # 同步 OpenAI 客户端
        self.async_client = async_client    # 异步 AsyncOpenAI 客户端


class LLMClient:
    """LLM 客户端，封装 OpenAI 兼容接口调用，支持多后端切换 + 模型 fallback 降级。"""

    def __init__(self, provider: str | None = None):
        """
        provider: 后端标识，None 则使用环境变量 AI_PROVIDER。
        支持: deepseek / qwen / zhipu / openai / auto
        v6.0: "auto"（或未知值）时按 AI_PROVIDERS 注册顺序自动探测第一个 Key 有效的后端。
        """
        self.provider = provider or config.AI_PROVIDER
        self._init_client()

    def _init_client(self):
        """根据当前 provider 初始化 OpenAI 客户端，并构建 fallback 候选池。

        v3.2: 同时构建 AsyncOpenAI 客户端，供 WebSocket 主流程直接 async for 流式消费。
        v4.3: 在 self._candidates 中预构建有序 fallback 候选（各自独立 api_key/base_url/model），
              主候选（当前 provider/model）始终在首位；配置 LLM_FALLBACK_CHAIN 时追加备用候选。
              候选数受 LLM_FALLBACK_MAX_RETRIES 限制。全局单例语义不变：fallback 仅临时读取
              self._candidates[i]，绝不重赋值 self.provider，不影响其它会话。
        v6.0: provider 为 auto/未知值时，经 config.AI_PROVIDER_RESOLVED 自动探测
              （注册表顺序遍历，取第一个 Key 有效的后端），显式指定不受影响。
        """
        if self.provider not in config.AI_PROVIDERS:
            self.provider = config.AI_PROVIDER_RESOLVED

        self.api_key = config.LLM_API_KEY
        self.base_url = config.LLM_BASE_URL
        self.model = config.LLM_MODEL

        # 主客户端（兼容 self.client / self.async_client 直连用法）
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

        # 候选池：主候选始终首位；LLM_FALLBACK_CHAIN 解析出的备用候选追加其后（去重）
        chain = config.LLM_FALLBACK_CHAIN
        candidates = [{
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
        }]
        for c in chain:
            if not any(c["provider"] == x["provider"] and c["model"] == x["model"] for x in candidates):
                candidates.append(c)
        max_retries = config.LLM_FALLBACK_MAX_RETRIES
        if max_retries > 0:
            candidates = candidates[:max_retries]

        self._candidates = []
        for c in candidates:
            # v5.0 健壮性：fallback 候选若 key 缺失/占位，直接跳过——
            # fallback 的意义是「主候选有效即可，备用缺失应降级而非致命」，
            # 否则单条 .env 未配置的备用 provider 会让整个模块初始化崩溃（连带所有测试 collection 失败）。
            issue = _api_key_issue(c["api_key"])
            if issue:
                logger.warning(
                    f"LLM 跳过无效 fallback 候选 {c['provider']}:{c['model']}（{issue}），仅主候选可用"
                )
                continue
            self._candidates.append(_Candidate(
                provider=c["provider"],
                model=c["model"],
                client=OpenAI(api_key=c["api_key"], base_url=c["base_url"]),
                async_client=AsyncOpenAI(api_key=c["api_key"], base_url=c["base_url"]),
            ))

        provider_info = config.AI_PROVIDERS.get(self.provider, {})
        self._api_key_env = provider_info.get("api_key_env", "DEEPSEEK_API_KEY")
        provider_name = provider_info.get("name", self.provider)
        issue = _api_key_issue(self.api_key)
        if issue:
            logger.warning(f"LLM {issue}，请在 .env 中设置 {self._api_key_env}（provider={provider_name}）")
        logger.info(
            f"LLM 客户端初始化: provider={provider_name}, model={self.model}, "
            f"base_url={self.base_url}, fallback 候选数={len(self._candidates) - 1}"
        )

    # ===== v4.3: fallback 内部机制 =====
    @staticmethod
    def _is_error_content(content: str | None) -> bool:
        """判定模型返回内容是否为软失败（我们约定的 {"error":...} 形态）。

        用于 chat_json 的 success_pred：当主候选返回不可用内容（空 / error JSON）时触发降级。
        兼容 ```json 围栏包裹。
        """
        if not content:
            return True
        s = content.strip()
        if not s:
            return True
        if s.startswith("```"):
            lines = s.strip("`").split("\n")
            if lines and lines[0].strip().lower() in ("json", "jsonc"):
                lines = lines[1:]
            s = "\n".join(lines).strip()
            if not s:
                return True
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return False
        return isinstance(data, dict) and "error" in data

    def _call_with_fallback(self, *, messages, temperature, max_tokens,
                            response_format=None, success_pred=None) -> str:
        """非流式调用，按候选池顺序尝试直至 success_pred 判定成功或穷尽。

        success_pred(content) -> bool: 返回 True 表示该候选结果可用（默认：非 error 软失败）。
        异常型失败一律降级；软失败（success_pred=False）也降级；候选数天然限制防无限循环。
        """
        if success_pred is None:
            def success_pred(c):
                return not self._is_error_content(c)

        last_err = None
        for idx, cand in enumerate(self._candidates):
            try:
                kwargs = {
                    "model": cand.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format:
                    kwargs["response_format"] = response_format
                resp = cand.client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content
                if content is None:
                    content = ""
                if success_pred(content):
                    logger.info(f"LLM 调用成功 [候选 {idx}] provider={cand.provider}, model={cand.model}")
                    return content
                logger.warning(
                    f"LLM 候选 {idx} ({cand.provider}:{cand.model}) 结果不可用(软失败),降级下一候选"
                )
                last_err = "软失败(结果不可用)"
            except Exception as e:  # noqa: BLE001
                logger.error(f"LLM 候选 {idx} ({cand.provider}:{cand.model}) 调用失败: {e},降级下一候选")
                last_err = e
        logger.error(f"所有 LLM 候选(共 {len(self._candidates)})均失败,最后错误: {last_err}")
        return json.dumps({"error": f"所有模型均调用失败: {last_err}"})

    async def _stream_with_fallback(self, *, messages, temperature, max_tokens):
        """异步流式调用，逐候选尝试（_call_with_fallback 的异步生成器版本）。

        - 候选在「尚未产出任何 chunk 即抛异常」时无缝切换下一候选。
        - 候选已产出部分内容后抛异常：无法撤回，停止并 yield 单个 error chunk（不拼接备用结果）。
        - 软失败（内容本身为 error JSON）在流式下无预知能力，按正常内容推送（与现有行为一致）。
        """
        last_err = None
        for idx, cand in enumerate(self._candidates):
            yielded = False
            try:
                stream = await cand.async_client.chat.completions.create(
                    model=cand.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yielded = True
                        yield delta.content
                return  # 正常结束（可能 0 chunk）
            except Exception as e:  # noqa: BLE001
                logger.error(f"流式 LLM 候选 {idx} ({cand.provider}:{cand.model}) 失败: {e}")
                last_err = e
                if not yielded:
                    continue
                logger.error("流式候选已产出部分内容后失败,停止并不拼接备用结果")
                yield json.dumps({"error": f"流式中途失败: {last_err}"})
                return
        yield json.dumps({"error": f"所有模型流式调用均失败: {last_err}"})

    def switch_provider(self, provider: str):
        """运行时切换 AI 后端。

        v6.0: 支持 "auto"（重新按注册表自动探测）；切换到显式后端时若其 Key
        无效则告警（注册表校验），但仍允许切换（由调用方决定是否容忍）。
        """
        if provider != "auto" and provider not in config.AI_PROVIDERS:
            logger.warning(f"未知 provider: {provider}，保持当前 {self.provider}")
            return False
        if provider != "auto":
            issue = config.provider_key_issue(provider)
            if issue:
                logger.warning(f"切换到 {provider} 后 {issue}，请检查对应环境变量")
        self.provider = provider
        self._init_client()
        return True

    def get_provider_info(self) -> dict:
        """获取当前后端信息。"""
        info = config.AI_PROVIDERS.get(self.provider, {})
        return {
            "provider": self.provider,
            "name": info.get("name", self.provider),
            "model": self.model,
            "available_models": info.get("models", []),
            "fallback_count": max(len(self._candidates) - 1, 0),
        }

    @staticmethod
    def list_providers() -> list[dict]:
        """列出所有可用的 AI 后端。"""
        return [
            {
                "id": pid,
                "name": info["name"],
                "default_model": info["default_model"],
                "models": info["models"],
            }
            for pid, info in config.AI_PROVIDERS.items()
        ]

    def chat(self, system_prompt: str, user_prompt: str,
             temperature: float = 0.7, max_tokens: int = 2048,
             response_format: dict | None = None) -> str:
        """发送聊天请求，返回完整文本（内部自动 fallback 降级）。"""
        issue = _api_key_issue(self.api_key)
        if issue:
            logger.warning(f"LLM {issue}，请在 .env 中设置 {self._api_key_env}")
            return json.dumps({"error": f"{issue}，请在 .env 中设置 {self._api_key_env}"})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._call_with_fallback(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    def chat_json(self, system_prompt: str, user_prompt: str,
                  temperature: float = 0.3, max_tokens: int = 2048) -> dict:
        """发送聊天请求，确保返回 JSON dict（解析失败自动 fallback 下一候选）。

        v6.0: 候选结果可用性判定与最终解析均改走 safe_json_extract 四级容错：
        轻微畸形的 JSON（围栏/截断/尾逗号/单引号）可被就地修复，无需浪费一次候选降级。
        """

        def _is_valid_json(content: str) -> bool:
            if self._is_error_content(content):
                return False
            return isinstance(safe_json_extract(content), dict)

        raw = self._call_with_fallback(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            success_pred=_is_valid_json,
        )
        data = safe_json_extract(raw)
        if isinstance(data, dict):
            return data
        logger.warning(f"LLM 返回内容四级容错后仍无法解析为 JSON 对象: {str(raw)[:200]}")
        return {"error": "JSON 解析失败", "raw": str(raw)[:1000]}

    def chat_stream(self, system_prompt: str, user_prompt: str,
                    temperature: float = 0.7, max_tokens: int = 2048):
        """
        同步流式聊天请求，返回一个生成器，逐 chunk yield 文本（内部自动 fallback 降级）。
        保留用于非异步上下文；WebSocket 主流程改用 chat_stream_async。
        """
        issue = _api_key_issue(self.api_key)
        if issue:
            logger.warning(f"LLM {issue}，请在 .env 中设置 {self._api_key_env}")
            yield json.dumps({"error": f"{issue}，请在 .env 中设置 {self._api_key_env}"})
            return

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_err = None
        for idx, cand in enumerate(self._candidates):
            yielded = False
            try:
                stream = cand.client.chat.completions.create(
                    model=cand.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yielded = True
                        yield delta.content
                return
            except Exception as e:  # noqa: BLE001
                logger.error(f"同步流式候选 {idx} ({cand.provider}:{cand.model}) 失败: {e}")
                last_err = e
                if not yielded:
                    continue
                yield json.dumps({"error": f"流式中途失败: {last_err}"})
                return
        yield json.dumps({"error": f"所有模型流式调用均失败: {last_err}"})

    async def chat_stream_async(self, system_prompt: str, user_prompt: str,
                                temperature: float = 0.7, max_tokens: int = 2048):
        """
        异步流式聊天请求，直接 async for 消费 AsyncOpenAI 的流式响应（内部自动 fallback 降级）。
        v3.2: 取代原"同步 chat_stream + 线程池 + asyncio.Queue 桥接"方案，
        无阻塞、无跨线程桥接，彻底消除 worker 线程 .result() 在队列满时的泄漏风险。
        """
        issue = _api_key_issue(self.api_key)
        if issue:
            logger.warning(f"LLM {issue}，请在 .env 中设置 {self._api_key_env}")
            yield json.dumps({"error": f"{issue}，请在 .env 中设置 {self._api_key_env}"})
            return

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        async for chunk in self._stream_with_fallback(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk


# 全局单例
llm_client = LLMClient()
