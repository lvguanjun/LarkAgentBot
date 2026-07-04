from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias


ChatType: TypeAlias = Literal["group", "p2p"]


@dataclass(frozen=True)
class TextPart:
    text: str
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class ImagePart:
    file_key: str
    alt_text: str = "[用户发送了一张图片]"
    type: Literal["image"] = "image"


ContentPart: TypeAlias = TextPart | ImagePart


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    chat_id: str
    chat_type: ChatType
    sender_id: str
    content: list[ContentPart]
    mentions: list[str] = field(default_factory=list)
    root_id: str | None = None
    raw_event: Any = None

    def text_content(self) -> str:
        parts: list[str] = []
        for part in self.content:
            if isinstance(part, TextPart):
                parts.append(part.text)
            else:
                parts.append(part.alt_text)
        return "".join(parts).strip()

    def to_openai_message(self) -> dict[str, str]:
        return {"role": "user", "content": self.text_content()}


class MessageSender(Protocol):
    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        root_id: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> None:
        ...
