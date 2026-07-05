from __future__ import annotations

import re

from lark_agent.transport.base import IncomingMessage, MentionPart, TextPart, content_part_text


MAIN_THREAD_ID = "main"
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
        if message.root_id and self.is_thread_activated(message.chat_id, message.root_id):
            return True
        return False

    def is_bot_mentioned(self, message: IncomingMessage) -> bool:
        return bool(self.bot_id) and self.bot_id in message.mentions

    def mark_thread_activated(self, chat_id: str, thread_id: str) -> None:
        self._activated_threads.add((chat_id, thread_id))

    def is_thread_activated(self, chat_id: str, thread_id: str) -> bool:
        return (chat_id, thread_id) in self._activated_threads

    def get_thread_id(self, message: IncomingMessage) -> str:
        if message.root_id:
            return message.root_id
        if message.chat_type == "p2p":
            return message.chat_id
        return MAIN_THREAD_ID

    def is_command(self, message: IncomingMessage) -> bool:
        text = self.normalized_text_content(message).lstrip()
        if message.chat_type == "p2p":
            return text.startswith("/")
        return self.is_bot_mentioned(message) and text.startswith("/")

    def normalized_text_content(self, message: IncomingMessage) -> str:
        if message.chat_type != "group" or not self.is_bot_mentioned(message):
            return message.text_content()

        parts: list[str] = []
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
                    parts.append(text)
                    continue

                dropping_leading_mentions = False

            if isinstance(part, TextPart):
                parts.append(part.text)
            elif isinstance(part, MentionPart):
                parts.append(part.display_text)
            else:
                parts.append(content_part_text(part))

        return "".join(parts).strip()


def _strip_leading_mention_tokens(text: str) -> str:
    return LEADING_MENTION_TOKEN_RE.sub("", text).lstrip()
