from __future__ import annotations

import json
import logging
from typing import Any

from lark_agent.transport.base import (
    ChatType,
    CodeBlockPart,
    ContentPart,
    DividerPart,
    EmojiPart,
    FilePart,
    ImagePart,
    IncomingMessage,
    LinkPart,
    LocationPart,
    MediaPart,
    MentionPart,
    StickerPart,
    SummaryPart,
    TextPart,
)


logger = logging.getLogger(__name__)


class LarkMessageEventAdapter:
    def to_incoming_message(self, event: Any) -> IncomingMessage | None:
        data = getattr(event, "event", None)
        message = getattr(data, "message", None)
        if message is None:
            return None

        chat_type = _normalize_chat_type(_string_attr(message, "chat_type"))
        if chat_type is None:
            return None

        message_id = _string_attr(message, "message_id")
        chat_id = _string_attr(message, "chat_id")
        sender_id = _sender_id(getattr(data, "sender", None))
        if not message_id or not chat_id or not sender_id:
            return None

        parts = self._content_parts(message)
        if parts is None:
            return None

        root_id = _string_attr(message, "root_id") or None
        return IncomingMessage(
            message_id=message_id,
            chat_id=chat_id,
            chat_type=chat_type,
            sender_id=sender_id,
            content=parts,
            mentions=_mention_ids(getattr(message, "mentions", None)),
            root_id=root_id,
            raw_event=event,
        )

    def dedupe_key(self, event: Any) -> str | None:
        header = getattr(event, "header", None)
        event_id = _string_attr(header, "event_id")
        if event_id:
            return event_id

        uuid = _string_attr(event, "uuid")
        if uuid:
            return uuid

        data = getattr(event, "event", None)
        message = getattr(data, "message", None)
        message_id = _string_attr(message, "message_id")
        return message_id or None

    def _content_parts(self, message: Any) -> list[ContentPart] | None:
        message_type = _string_attr(message, "message_type")
        parsed = _parse_json_object(_string_attr(message, "content"))
        if parsed is None:
            return None

        if message_type == "text":
            text = parsed.get("text")
            return [TextPart(text)] if isinstance(text, str) else None
        if message_type == "image":
            file_key = _image_key(parsed)
            return [ImagePart(file_key=file_key)] if file_key else _summary_if_readable(message_type, parsed)
        if message_type == "post":
            parts = _flatten_post_content(parsed)
            return parts or None
        if message_type in {"file", "folder"}:
            file_key = _first_string(parsed, ("file_key",))
            file_name = _first_string(parsed, ("file_name", "name"))
            if file_key:
                return [FilePart(file_key=file_key, file_name=file_name, kind=message_type)]
            return _summary_if_readable(message_type, parsed)
        if message_type == "audio":
            file_key = _first_string(parsed, ("file_key",))
            if file_key:
                return [
                    MediaPart(
                        file_key=file_key,
                        duration=_int_value(parsed.get("duration")),
                        kind="audio",
                    )
                ]
            return _summary_if_readable(message_type, parsed)
        if message_type == "media":
            file_key = _first_string(parsed, ("file_key",))
            if file_key:
                return [
                    MediaPart(
                        file_key=file_key,
                        image_key=_first_string(parsed, ("image_key",)),
                        file_name=_first_string(parsed, ("file_name", "name")),
                        duration=_int_value(parsed.get("duration")),
                        kind="media",
                    )
                ]
            return _summary_if_readable(message_type, parsed)
        if message_type == "sticker":
            file_key = _first_string(parsed, ("file_key",))
            return [StickerPart(file_key=file_key)] if file_key else _summary_if_readable(message_type, parsed)
        if message_type == "interactive":
            parts = _flatten_interactive_content(parsed)
            return parts or [_summary_part(message_type, parsed)]
        if message_type == "hongbao":
            text = _first_string(parsed, ("text",))
            return [TextPart(text)] if text else [_summary_part(message_type, parsed)]
        if message_type in {
            "share_calendar_event",
            "calendar",
            "general_calendar",
            "share_chat",
            "share_user",
            "system",
            "video_chat",
            "todo",
            "vote",
            "merge_forward",
        }:
            return [_business_summary_part(message_type, parsed)]
        if message_type == "location":
            return [
                LocationPart(
                    name=_first_string(parsed, ("name",)),
                    longitude=_first_string(parsed, ("longitude",)),
                    latitude=_first_string(parsed, ("latitude",)),
                )
            ]
        return None


def _normalize_chat_type(value: str) -> ChatType | None:
    if value == "group":
        return "group"
    if value in {"p2p", "private"}:
        return "p2p"
    return None


def _string_attr(obj: Any, name: str) -> str:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else ""


def _sender_id(sender: Any) -> str:
    ids = getattr(sender, "sender_id", None)
    for name in ("open_id", "user_id", "union_id"):
        value = _string_attr(ids, name)
        if value:
            return value
    return ""


def _mention_ids(mentions: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for mention in mentions or []:
        ids = getattr(mention, "id", None)
        for name in ("open_id", "user_id", "union_id"):
            value = _string_attr(ids, name)
            if value and value not in seen:
                values.append(value)
                seen.add(value)
    return values


def _parse_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        logger.warning("Failed to parse Feishu message content JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def _image_key(content: dict[str, Any]) -> str:
    for name in ("image_key", "file_key"):
        value = content.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _flatten_post_content(content: dict[str, Any]) -> list[ContentPart]:
    source: Any = content.get("content")
    if source is None:
        for value in content.values():
            if isinstance(value, dict) and "content" in value:
                source = value["content"]
                break
    if source is None:
        source = content

    parts: list[ContentPart] = []
    _flatten_rich_content(source, parts)
    return parts


def _flatten_interactive_content(content: dict[str, Any]) -> list[ContentPart]:
    parts: list[ContentPart] = []
    title = _first_string(content, ("title",))
    if title:
        parts.append(TextPart(title))
        parts.append(TextPart("\n"))
    _flatten_rich_content(content.get("elements"), parts)
    if parts and isinstance(parts[-1], TextPart) and parts[-1].text == "\n":
        parts.pop()
    return parts


def _flatten_rich_content(node: Any, parts: list[ContentPart]) -> None:
    if _is_row_list(node):
        for index, row in enumerate(node):
            _flatten_rich_node(row, parts)
            if index < len(node) - 1:
                parts.append(TextPart("\n"))
        return
    _flatten_rich_node(node, parts)


def _flatten_rich_node(node: Any, parts: list[ContentPart]) -> None:
    if isinstance(node, list):
        for item in node:
            _flatten_rich_node(item, parts)
        return
    if not isinstance(node, dict):
        return

    tag = node.get("tag")
    if tag == "text":
        text = _first_string(node, ("text", "name", "user_name", "user_id"))
        if text:
            parts.append(TextPart(text))
        return
    if tag == "a":
        text = _first_string(node, ("text", "name", "href"))
        href = _first_string(node, ("href",))
        if text or href:
            parts.append(LinkPart(text=text, href=href))
        return
    if tag == "at":
        user_id = _first_string(node, ("user_id",))
        user_name = _first_string(node, ("user_name", "name", "text"))
        if user_id or user_name:
            parts.append(MentionPart(user_id=user_id, user_name=user_name))
        return
    if tag in {"img", "image"}:
        file_key = _image_key(node)
        if file_key:
            parts.append(ImagePart(file_key=file_key))
        return
    if tag == "media":
        file_key = _first_string(node, ("file_key",))
        if file_key:
            parts.append(
                MediaPart(
                    file_key=file_key,
                    image_key=_first_string(node, ("image_key",)),
                    file_name=_first_string(node, ("file_name", "name")),
                    duration=_int_value(node.get("duration")),
                    kind="media",
                )
            )
        return
    if tag == "emotion":
        emoji_type = _first_string(node, ("emoji_type", "text", "name"))
        if emoji_type:
            parts.append(EmojiPart(emoji_type=emoji_type))
        return
    if tag == "hr":
        parts.append(DividerPart())
        return
    if tag == "code_block":
        text = _first_string(node, ("text",))
        if text:
            parts.append(CodeBlockPart(language=_first_string(node, ("language",)), text=text))
        return

    for name in ("content", "children", "elements"):
        if name in node:
            _flatten_rich_content(node[name], parts)
            return

    if isinstance(tag, str) and tag:
        parts.append(_summary_part(tag, node))


def _business_summary_part(message_type: str, content: dict[str, Any]) -> SummaryPart:
    if message_type == "todo":
        fields = _string_fields(content, exclude={"summary"})
        summary = content.get("summary")
        summary_parts = _flatten_post_content(summary) if isinstance(summary, dict) else []
        title = "".join(_summary_text_value(part) for part in summary_parts).strip()
        return SummaryPart(kind=message_type, title=title, fields=fields)
    if message_type == "system":
        return SummaryPart(
            kind=message_type,
            title=_render_system_template(content),
            fields=_string_fields(content, exclude={"template"}),
        )
    title = _first_string(content, ("summary", "topic", "content", "text"))
    return SummaryPart(kind=message_type, title=title, fields=_string_fields(content))


def _summary_part(kind: str, content: dict[str, Any]) -> SummaryPart:
    title = _first_string(content, ("text", "title", "placeholder", "name", "content"))
    return SummaryPart(kind=kind, title=title, fields=_string_fields(content, exclude={"tag", "text", "title"}))


def _summary_if_readable(kind: str, content: dict[str, Any]) -> list[SummaryPart] | None:
    summary = _summary_part(kind, content)
    return [summary] if summary.title or summary.fields else None


def _summary_text_value(part: ContentPart) -> str:
    if isinstance(part, TextPart):
        return part.text
    if isinstance(part, LinkPart):
        return part.text or part.href
    if isinstance(part, MentionPart):
        return part.display_text
    if isinstance(part, EmojiPart):
        return part.emoji_type
    return ""


def _render_system_template(content: dict[str, Any]) -> str:
    template = _first_string(content, ("template",))
    if not template:
        return ""
    rendered = template
    for key, value in content.items():
        if key == "template":
            continue
        rendered = rendered.replace("{" + key + "}", _field_value(value))
    return rendered


def _first_string(values: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = values.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _is_row_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, list) for item in value)


def _string_fields(content: dict[str, Any], *, exclude: set[str] | None = None) -> dict[str, str]:
    excluded = exclude or set()
    fields: dict[str, str] = {}
    for key, value in content.items():
        if key in excluded:
            continue
        rendered = _field_value(value)
        if rendered:
            fields[key] = rendered
    return fields


def _field_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    if isinstance(value, list):
        return ", ".join(item for item in (_field_value(item) for item in value) if item)
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text:
            return text
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return ""
