from __future__ import annotations

from lark_agent.transport.base import IncomingMessage


MAIN_THREAD_ID = "main"


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
        text = message.text_content().lstrip()
        if message.chat_type == "p2p":
            return text.startswith("/")
        return self.is_bot_mentioned(message) and text.startswith("/")
