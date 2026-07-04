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
        if self._client is not None and hasattr(self._client, "complete"):
            result = self._client.complete(system_prompt, messages)
            if inspect.isawaitable(result):
                result = await result
            return str(result)

        client = self._client or self._build_openai_client()
        api_messages: list[dict[str, Any]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        completion = await client.chat.completions.create(
            model=self.config.model,
            messages=api_messages,
        )
        content = completion.choices[0].message.content
        return content or ""

    def _build_openai_client(self) -> Any:
        from openai import AsyncOpenAI

        kwargs: dict[str, str] = {}
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return AsyncOpenAI(**kwargs)
