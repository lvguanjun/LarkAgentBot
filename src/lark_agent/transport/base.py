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


@dataclass(frozen=True)
class DownloadedImage:
    data: bytes
    mime_type: str = ""
    file_name: str = ""


@dataclass(frozen=True)
class MentionPart:
    user_id: str
    user_name: str = ""
    type: Literal["mention"] = "mention"

    @property
    def display_text(self) -> str:
        return self.user_name or self.user_id


@dataclass(frozen=True)
class FilePart:
    file_key: str
    file_name: str = ""
    kind: Literal["file", "folder"] = "file"
    type: Literal["file"] = "file"


@dataclass(frozen=True)
class MediaPart:
    file_key: str
    image_key: str = ""
    file_name: str = ""
    duration: int | None = None
    kind: Literal["audio", "media"] = "media"
    type: Literal["media"] = "media"


@dataclass(frozen=True)
class StickerPart:
    file_key: str
    type: Literal["sticker"] = "sticker"


@dataclass(frozen=True)
class LinkPart:
    text: str
    href: str = ""
    type: Literal["link"] = "link"


@dataclass(frozen=True)
class CodeBlockPart:
    language: str
    text: str
    type: Literal["code_block"] = "code_block"


@dataclass(frozen=True)
class DividerPart:
    text: str = "---"
    type: Literal["divider"] = "divider"


@dataclass(frozen=True)
class EmojiPart:
    emoji_type: str
    type: Literal["emoji"] = "emoji"


@dataclass(frozen=True)
class LocationPart:
    name: str = ""
    longitude: str = ""
    latitude: str = ""
    type: Literal["location"] = "location"


@dataclass(frozen=True)
class SummaryPart:
    kind: str
    title: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    type: Literal["summary"] = "summary"


ContentPart: TypeAlias = (
    TextPart
    | ImagePart
    | MentionPart
    | FilePart
    | MediaPart
    | StickerPart
    | LinkPart
    | CodeBlockPart
    | DividerPart
    | EmojiPart
    | LocationPart
    | SummaryPart
)


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    chat_id: str
    chat_type: ChatType
    sender_id: str
    content: list[ContentPart]
    mentions: list[str] = field(default_factory=list)
    root_id: str | None = None
    thread_id: str | None = None
    raw_event: Any = None

    def text_content(self) -> str:
        return "".join(content_part_text(part) for part in self.content).strip()

    def to_openai_message(self) -> dict[str, str]:
        return {"role": "user", "content": self.text_content()}


def content_part_text(part: ContentPart) -> str:
    if isinstance(part, TextPart):
        return part.text
    if isinstance(part, MentionPart):
        return part.display_text
    if isinstance(part, ImagePart):
        return part.alt_text
    if isinstance(part, FilePart):
        label = "文件夹" if part.kind == "folder" else "文件"
        fields = _projection_fields((("name", part.file_name), ("file_key", part.file_key)))
        return f"[用户发送了一个{label}{fields}]"
    if isinstance(part, MediaPart):
        label = "音频" if part.kind == "audio" else "视频"
        fields = _projection_fields(
            (
                ("name", part.file_name),
                ("duration", f"{part.duration}ms" if part.duration is not None else ""),
                ("file_key", part.file_key),
                ("image_key", part.image_key),
            )
        )
        return f"[用户发送了一段{label}{fields}]"
    if isinstance(part, StickerPart):
        fields = _projection_fields((("file_key", part.file_key),))
        return f"[用户发送了一个表情包{fields}]"
    if isinstance(part, LinkPart):
        if part.text and part.href:
            return f"{part.text} ({part.href})"
        return part.text or part.href
    if isinstance(part, CodeBlockPart):
        language = f" {part.language}" if part.language else ""
        return f"\n[代码块{language}]\n{part.text}\n"
    if isinstance(part, DividerPart):
        return f"\n{part.text}\n"
    if isinstance(part, EmojiPart):
        return f"[表情: {part.emoji_type}]"
    if isinstance(part, LocationPart):
        fields = _projection_fields(
            (("name", part.name), ("longitude", part.longitude), ("latitude", part.latitude))
        )
        return f"[位置{fields}]"
    if isinstance(part, SummaryPart):
        title = f": {part.title}" if part.title else ""
        fields = _projection_fields(part.fields.items())
        return f"[{part.kind}{title}{fields}]"
    return ""


def _projection_fields(fields: Any) -> str:
    values = [f"{key}={value}" for key, value in fields if value != ""]
    return f": {', '.join(values)}" if values else ""


class MessageSender(Protocol):
    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        root_id: str | None = None,
        reply_to_message_id: str | None = None,
        reply_in_thread: bool = False,
    ) -> "SendResult":
        ...


@dataclass(frozen=True)
class SendResult:
    message_id: str | None = None
    root_id: str | None = None
    thread_id: str | None = None


class MessageReactor(Protocol):
    async def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        """Add an emoji reaction. Returns reaction_id for later removal."""
        ...

    async def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        ...


@dataclass
class StreamingCardState:
    card_id: str
    element_id: str = "md_main"
    sequence: int = 0

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence


class CardStreamer(Protocol):
    async def create_streaming_card(self) -> StreamingCardState:
        ...

    async def send_card(
        self,
        chat_id: str,
        card_id: str,
        *,
        reply_to_message_id: str | None = None,
        reply_in_thread: bool = False,
    ) -> SendResult:
        ...

    async def update_card_content(
        self, card_id: str, element_id: str, content: str, sequence: int
    ) -> None:
        ...

    async def close_streaming(self, card_id: str, sequence: int) -> None:
        ...


class ImageDownloader(Protocol):
    async def download_image(self, message_id: str, file_key: str) -> DownloadedImage:
        ...
