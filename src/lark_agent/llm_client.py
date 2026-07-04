from __future__ import annotations

import inspect
from typing import Any, Protocol

from lark_agent.config import LLMConfig


class TextCompletionClient(Protocol):
    def complete(self, system_prompt: str, messages: list[dict[str, Any]]) -> str: ...


class LLMClient:
    def __init__(
        self,
        config: LLMConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._client = client

    @classmethod
    def from_config(cls, config: LLMConfig) -> "LLMClient":
        return cls(config)

    async def complete(self, system_prompt: str, messages: list[dict[str, Any]]) -> str:
        message = await self.complete_message(system_prompt, messages)
        content = message.get("content")
        return content if isinstance(content, str) else ""

    async def complete_message(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self._client is not None and hasattr(self._client, "complete_message"):
            result = self._client.complete_message(system_prompt, messages, tools=tools)
            if inspect.isawaitable(result):
                result = await result
            return _normalize_assistant_message(result)

        if self._client is not None and hasattr(self._client, "complete"):
            result = self._client.complete(system_prompt, messages)
            if inspect.isawaitable(result):
                result = await result
            return {"role": "assistant", "content": str(result)}

        client = self._client or self._build_openai_client()
        api_messages: list[dict[str, Any]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = tools

        completion = await client.chat.completions.create(**kwargs)
        return _normalize_assistant_message(completion.choices[0].message)

    def _build_openai_client(self) -> Any:
        from openai import AsyncOpenAI

        kwargs: dict[str, str] = {}
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return AsyncOpenAI(**kwargs)


def _normalize_assistant_message(message: Any) -> dict[str, Any]:
    if isinstance(message, str):
        return {"role": "assistant", "content": message}

    if isinstance(message, dict):
        normalized = dict(message)
    elif hasattr(message, "model_dump"):
        normalized = message.model_dump(exclude_none=True)
    else:
        normalized = {
            "content": getattr(message, "content", ""),
            "tool_calls": getattr(message, "tool_calls", None),
        }

    normalized["role"] = "assistant"
    if "content" not in normalized:
        normalized["content"] = None if normalized.get("tool_calls") else ""
    if normalized.get("tool_calls") is None:
        normalized.pop("tool_calls", None)
    return normalized
