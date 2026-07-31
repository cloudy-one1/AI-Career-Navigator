"""
LLM 调用封装：OpenAI 兼容接口 + 流式输出支持。
v2.1: 多 AI 后端可切换（DeepSeek / Qwen / 智谱 / OpenAI）。
"""

import json
import logging
from openai import OpenAI
from backend.config import config

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM 客户端，封装 OpenAI 兼容接口调用，支持多后端切换。"""

    def __init__(self, provider: str | None = None):
        """
        provider: 后端标识，None 则使用环境变量 AI_PROVIDER。
        支持: deepseek / qwen / zhipu / openai
        """
        self.provider = provider or config.AI_PROVIDER
        self._init_client()

    def _init_client(self):
        """根据当前 provider 初始化 OpenAI 客户端。"""
        self.api_key = config.LLM_API_KEY
        self.base_url = config.LLM_BASE_URL
        self.model = config.LLM_MODEL

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        provider_info = config.AI_PROVIDERS.get(self.provider, {})
        provider_name = provider_info.get("name", self.provider)
        logger.info(f"LLM 客户端初始化: provider={provider_name}, model={self.model}, base_url={self.base_url}")

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
        """发送聊天请求，返回完整文本。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        try:
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            logger.info(f"LLM 调用成功，provider={self.provider}, model={self.model}, tokens={response.usage}")
            return content
        except Exception as e:
            logger.error(f"LLM 调用失败 [{self.provider}]: {e}")
            return json.dumps({"error": f"LLM 调用失败: {str(e)}"})

    def chat_json(self, system_prompt: str, user_prompt: str,
                  temperature: float = 0.3, max_tokens: int = 2048) -> dict:
        """发送聊天请求，确保返回 JSON dict。"""
        raw = self.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"LLM 返回非 JSON 内容，尝试手动提取: {raw[:200]}")
            return {"error": "JSON 解析失败", "raw": raw[:1000]}

    def chat_stream(self, system_prompt: str, user_prompt: str,
                    temperature: float = 0.7, max_tokens: int = 2048):
        """
        流式聊天请求，返回一个生成器，逐 chunk yield 文本。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"流式调用失败 [{self.provider}]: {e}")
            yield json.dumps({"error": f"{e}"})


# 全局单例
llm_client = LLMClient()
