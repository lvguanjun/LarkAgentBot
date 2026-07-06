from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Protocol

from lark_agent.config import LLMConfig


class TextCompletionClient(Protocol):
    def complete(self, system_prompt: str, messages: list[dict[str, Any]]) -> str: ...


@dataclass
class StreamChunk:
    delta_text: str = ""
    finish_reason: str | None = None
    accumulated_tool_calls: list[dict[str, Any]] = field(default_factory=list)


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

    async def stream_message(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        if self._client is not None and hasattr(self._client, "stream_message"):
            result = self._client.stream_message(system_prompt, messages, tools=tools)
            if inspect.isawaitable(result):
                result = await result
            async for chunk in result:
                yield chunk
            return

        if self._client is not None and not hasattr(self._client, "stream_message"):
            message = await self.complete_message(system_prompt, messages, tools=tools)
            tool_calls = message.get("tool_calls") or []
            yield StreamChunk(
                delta_text=message.get("content") or "",
                finish_reason="stop" if not tool_calls else "tool_calls",
                accumulated_tool_calls=tool_calls,
            )
            return

        client = self._client or self._build_openai_client()
        api_messages: list[dict[str, Any]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": api_messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        stream = await client.chat.completions.create(**kwargs)
        tool_calls_acc: list[dict[str, Any]] = []

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue

            delta = choice.delta
            delta_text = getattr(delta, "content", None) or ""
            delta_tool_calls = getattr(delta, "tool_calls", None)

            if delta_tool_calls:
                _merge_tool_call_deltas(tool_calls_acc, delta_tool_calls)

            yield StreamChunk(
                delta_text=delta_text,
                finish_reason=choice.finish_reason,
                accumulated_tool_calls=list(tool_calls_acc) if tool_calls_acc else [],
            )

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


def _merge_tool_call_deltas(accumulated: list[dict[str, Any]], deltas: Any) -> None:
    for delta_tc in deltas:
        index = getattr(delta_tc, "index", None)
        if index is None:
            continue

        while len(accumulated) <= index:
            accumulated.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})

        entry = accumulated[index]
        tc_id = getattr(delta_tc, "id", None)
        if isinstance(tc_id, str) and tc_id:
            entry["id"] = tc_id

        func = getattr(delta_tc, "function", None)
        if func is not None:
            name = getattr(func, "name", None)
            if isinstance(name, str) and name:
                entry["function"]["name"] += name
            args = getattr(func, "arguments", None)
            if isinstance(args, str):
                entry["function"]["arguments"] += args
