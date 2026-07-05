from __future__ import annotations

import json
import logging
from typing import Any

from lark_agent.transport.base import ChatType, ImagePart, IncomingMessage, TextPart


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

    def _content_parts(self, message: Any) -> list[TextPart | ImagePart] | None:
        message_type = _string_attr(message, "message_type")
        parsed = _parse_json_object(_string_attr(message, "content"))
        if parsed is None:
            return None

        if message_type == "text":
            text = parsed.get("text")
            return [TextPart(text)] if isinstance(text, str) else None
        if message_type == "image":
            file_key = _image_key(parsed)
            return [ImagePart(file_key=file_key)] if file_key else None
        if message_type == "post":
            parts = _flatten_post_content(parsed)
            return parts or None
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


def _flatten_post_content(content: dict[str, Any]) -> list[TextPart | ImagePart]:
    source: Any = content.get("content")
    if source is None:
        for value in content.values():
            if isinstance(value, dict) and "content" in value:
                source = value["content"]
                break
    if source is None:
        source = content

    parts: list[TextPart | ImagePart] = []
    _flatten_post_node(source, parts)
    return parts


def _flatten_post_node(node: Any, parts: list[TextPart | ImagePart]) -> None:
    if isinstance(node, list):
        for item in node:
            _flatten_post_node(item, parts)
        return
    if not isinstance(node, dict):
        return

    tag = node.get("tag")
    if tag in {"text", "a", "at"}:
        text = _first_string(node, ("text", "name", "user_name", "user_id"))
        if text:
            parts.append(TextPart(text))
        return
    if tag in {"img", "image"}:
        file_key = _image_key(node)
        if file_key:
            parts.append(ImagePart(file_key=file_key))
        return

    for name in ("content", "children", "elements"):
        if name in node:
            _flatten_post_node(node[name], parts)


def _first_string(values: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = values.get(name)
        if isinstance(value, str) and value:
            return value
    return ""
