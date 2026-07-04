from __future__ import annotations

import json
from pathlib import Path
from typing import Any


Message = dict[str, Any]


class Conversation:
    def __init__(self, path: Path, *, max_messages: int = 40) -> None:
        self.path = path
        self.max_messages = max_messages
        self.history_path = path / "history.jsonl"

    def append(self, message: Message) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        line = json.dumps(message, ensure_ascii=False)
        with self.history_path.open("a", encoding="utf-8") as history:
            history.write(f"{line}\n")

    def get_full_history(self) -> list[Message]:
        if not self.history_path.exists():
            return []

        messages: list[Message] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"History line must be an object: {self.history_path}")
                messages.append(value)
        return messages

    def get_context(self, max_messages: int | None = None) -> list[Message]:
        limit = self.max_messages if max_messages is None else max_messages
        if limit <= 0:
            return []

        groups = _group_messages(self.get_full_history())
        selected: list[list[Message]] = []
        selected_count = 0

        for group in reversed(groups):
            group_count = len(group)
            if selected and selected_count + group_count > limit:
                if _is_tool_exchange(group):
                    selected.append(group)
                break
            selected.append(group)
            selected_count += group_count
            if selected_count >= limit:
                break

        context = [message for group in reversed(selected) for message in group]
        while context and context[0].get("role") == "tool":
            context.pop(0)
        return context


def _group_messages(messages: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    index = 0

    while index < len(messages):
        message = messages[index]
        group = [message]
        index += 1

        if message.get("role") == "assistant" and message.get("tool_calls"):
            while index < len(messages) and messages[index].get("role") == "tool":
                group.append(messages[index])
                index += 1

        groups.append(group)

    return groups


def _is_tool_exchange(group: list[Message]) -> bool:
    first = group[0] if group else {}
    return first.get("role") == "assistant" and bool(first.get("tool_calls"))
