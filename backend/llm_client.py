"""
LLM 调用封装：OpenAI 兼容接口 + 流式输出支持。
v2.1: 多 AI 后端可切换（DeepSeek / Qwen / 智谱 / OpenAI）。
"""

import json
import logging
from openai import OpenAI, AsyncOpenAI
from .config import config

logger = logging.getLogger(__name__)


def _api_key_issue(key: str) -> str | None:
    """校验 API Key 有效性。

    返回 None 表示正常，否则返回问题描述（中文）。
    识别三类无效 Key：空、含非 ASCII 字符（如中文占位符）、占位符模板。
    """
    if not key:
        return "API Key 未配置"
    if any(ord(c) > 127 for c in key):
        return "API Key 含非 ASCII 字符（如中文），请填写纯英文数字的真实 Key"
    if any(t in key for t in ("sk-xxxx", "sk-your-", "key-here", "替换", "your-key")):
        return "API Key 是占位符模板，请填写真实 Key"
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
        支持: deepseek / qwen / zhipu / openai
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
        """
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
        """运行时切换 AI 后端。"""
        if provider not in config.AI_PROVIDERS:
            logger.warning(f"未知 provider: {provider}，保持当前 {self.provider}")
            return False
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
        """发送聊天请求，确保返回 JSON dict（解析失败自动 fallback 下一候选）。"""

        def _is_valid_json(content: str) -> bool:
            if self._is_error_content(content):
                return False
            try:
                json.loads(content)
            except (json.JSONDecodeError, ValueError):
                return False
            return True

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
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"LLM 返回非 JSON 内容，尝试手动提取: {raw[:200]}")
            return {"error": "JSON 解析失败", "raw": raw[:1000]}

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
