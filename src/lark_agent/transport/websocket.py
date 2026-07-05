from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from lark_agent.app import BotApp
from lark_agent.transport.base import ChatType, ImagePart, IncomingMessage, TextPart


logger = logging.getLogger(__name__)


class LarkSendError(RuntimeError):
    """Raised when the Feishu message API rejects a send request."""


class LarkMessageSender:
    def __init__(self, client: Any) -> None:
        self._message_api = client.im.v1.message

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        root_id: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> None:
        content = json.dumps({"text": text}, ensure_ascii=False)
        if reply_to_message_id:
            body = (
                ReplyMessageRequestBody.builder()
                .content(content)
                .msg_type("text")
                .reply_in_thread(root_id is not None)
                .build()
            )
            request = (
                ReplyMessageRequest.builder()
                .message_id(reply_to_message_id)
                .request_body(body)
                .build()
            )
            response = await self._message_api.areply(request)
            _raise_for_failed_response(response, "reply")
            return

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(content)
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        response = await self._message_api.acreate(request)
        _raise_for_failed_response(response, "create")


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


class TTLSeenCache:
    def __init__(self, *, ttl_seconds: float = 600, max_size: int = 4096) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()

    def seen_or_mark(self, key: str) -> bool:
        now = time.monotonic()
        self._prune(now)
        if key in self._seen:
            self._seen.move_to_end(key)
            return True

        self._seen[key] = now
        while len(self._seen) > self.max_size:
            self._seen.popitem(last=False)
        return False

    def _prune(self, now: float) -> None:
        expired_before = now - self.ttl_seconds
        while self._seen:
            _, created_at = next(iter(self._seen.items()))
            if created_at > expired_before:
                break
            self._seen.popitem(last=False)


class LarkWebSocketBotRunner:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        app: BotApp,
        encrypt_key: str = "",
        verification_token: str = "",
        adapter: LarkMessageEventAdapter | None = None,
        dedupe_cache: TTLSeenCache | None = None,
        event_handler_factory: Callable[[Callable[[Any], None]], Any] | None = None,
        ws_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.app = app
        self.encrypt_key = encrypt_key
        self.verification_token = verification_token
        self.adapter = adapter or LarkMessageEventAdapter()
        self.dedupe_cache = dedupe_cache or TTLSeenCache()
        self._event_handler_factory = event_handler_factory
        self._ws_client_factory = ws_client_factory or lark.ws.Client
        self._tasks: set[asyncio.Task[Any]] = set()

    def build_event_handler(self) -> Any:
        if self._event_handler_factory is not None:
            return self._event_handler_factory(self.handle_event)

        return (
            lark.EventDispatcherHandler.builder(self.encrypt_key, self.verification_token)
            .register_p2_im_message_receive_v1(self.handle_event)
            .build()
        )

    def start(self) -> None:
        client = self._ws_client_factory(
            self.app_id,
            self.app_secret,
            event_handler=self.build_event_handler(),
        )
        client.start()

    def handle_event(self, event: Any) -> None:
        try:
            dedupe_key = self.adapter.dedupe_key(event)
            if dedupe_key is None:
                logger.warning("Skipping Feishu event without stable dedupe key")
                return
            if self.dedupe_cache.seen_or_mark(dedupe_key):
                logger.info("Skipping duplicate Feishu event: %s", dedupe_key)
                return

            message = self.adapter.to_incoming_message(event)
            if message is None:
                return

            loop = asyncio.get_running_loop()
            task = loop.create_task(self.app.handle_message(message))
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)
        except Exception:
            logger.exception("Failed to schedule Feishu message event")

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("Feishu message task was cancelled")
        except Exception:
            logger.exception("Feishu message task failed")


def _raise_for_failed_response(response: Any, action: str) -> None:
    success = getattr(response, "success", None)
    if not callable(success) or success():
        return

    code = getattr(response, "code", None)
    message = getattr(response, "msg", None) or "unknown error"
    log_id = response.get_log_id() if callable(getattr(response, "get_log_id", None)) else None
    suffix = f", log_id={log_id}" if log_id else ""
    raise LarkSendError(f"Feishu message {action} failed: code={code}, msg={message}{suffix}")


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
