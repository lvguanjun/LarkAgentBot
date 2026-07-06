from __future__ import annotations

import re

from lark_agent.transport.base import (
    ContentPart,
    IncomingMessage,
    MentionPart,
    TextPart,
    content_part_text,
)

LEADING_MENTION_TOKEN_RE = re.compile(r"^(?:\s*@_user_\d+\s*)+")


class MessageRouter:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self._activated_threads: set[tuple[str, str]] = set()

    def should_respond(self, message: IncomingMessage) -> bool:
        if message.chat_type == "p2p":
            return True
        if self.is_bot_mentioned(message):
            return True
        return bool(
            message.thread_id and self.is_thread_activated(message.chat_id, message.thread_id)
        )

    def is_bot_mentioned(self, message: IncomingMessage) -> bool:
        return bool(self.bot_id) and self.bot_id in message.mentions

    def mark_thread_activated(self, chat_id: str, thread_id: str) -> None:
        self._activated_threads.add((chat_id, thread_id))

    def is_thread_activated(self, chat_id: str, thread_id: str) -> bool:
        return (chat_id, thread_id) in self._activated_threads

    def get_existing_thread_id(self, message: IncomingMessage) -> str | None:
        return message.thread_id

    def is_command(self, message: IncomingMessage) -> bool:
        text = self.normalized_text_content(message).lstrip()
        if message.chat_type == "p2p":
            return text.startswith("/")
        return self.is_bot_mentioned(message) and text.startswith("/")

    def normalized_text_content(self, message: IncomingMessage) -> str:
        return "".join(
            content_part_text(part) for part in self.normalized_content_parts(message)
        ).strip()

    def normalized_content_parts(self, message: IncomingMessage) -> list[ContentPart]:
        if message.chat_type != "group" or not self.is_bot_mentioned(message):
            return list(message.content)

        parts: list[ContentPart] = []
        dropping_leading_mentions = True
        for part in message.content:
            if dropping_leading_mentions:
                if isinstance(part, MentionPart):
                    continue
                if isinstance(part, TextPart):
                    text = _strip_leading_mention_tokens(part.text)
                    if not text:
                        continue
                    dropping_leading_mentions = False
                    parts.append(TextPart(text))
                    continue

                dropping_leading_mentions = False

            parts.append(part)

        return parts


def _strip_leading_mention_tokens(text: str) -> str:
    return LEADING_MENTION_TOKEN_RE.sub("", text).lstrip()
