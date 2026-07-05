from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import lark_oapi as lark

from lark_agent.app import BotApp
from lark_agent.transport.lark.adapter import LarkMessageEventAdapter
from lark_agent.transport.lark.dedupe import TTLSeenCache


logger = logging.getLogger(__name__)


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
            .register_p2_im_chat_member_bot_added_v1(self.handle_ignored_event)
            .register_p2_im_chat_member_bot_deleted_v1(self.handle_ignored_event)
            .register_p2_im_message_reaction_created_v1(self.handle_ignored_event)
            .register_p2_im_message_reaction_deleted_v1(self.handle_ignored_event)
            .register_p2_drive_notice_comment_add_v1(self.handle_ignored_event)
            .register_p2_vc_meeting_participant_meeting_ended_v1(self.handle_ignored_event)
            .register_p2_minutes_minute_generated_v1(self.handle_ignored_event)
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
            logger.info(
                "Received Feishu message event: %s",
                _format_event_log_fields(event),
            )
            dedupe_key = self.adapter.dedupe_key(event)
            if dedupe_key is None:
                logger.warning(
                    "Skipping Feishu message event without stable dedupe key: %s",
                    _format_event_log_fields(event),
                )
                return
            if self.dedupe_cache.seen_or_mark(dedupe_key):
                logger.info(
                    "Skipping duplicate Feishu message event: dedupe_key=%s %s",
                    dedupe_key,
                    _format_event_log_fields(event),
                )
                return

            message = self.adapter.to_incoming_message(event)
            if message is None:
                logger.info(
                    "Ignoring unsupported Feishu message event: %s",
                    _format_event_log_fields(event),
                )
                return

            loop = asyncio.get_running_loop()
            task = loop.create_task(self.app.handle_message(message))
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)
        except Exception:
            logger.exception("Failed to schedule Feishu message event")

    def handle_ignored_event(self, event: Any) -> None:
        logger.info(
            "Ignoring Feishu event without business handler: %s",
            _format_event_log_fields(event),
        )

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("Feishu message task was cancelled")
        except Exception:
            logger.exception("Feishu message task failed")


def _format_event_log_fields(event: Any) -> str:
    header = getattr(event, "header", None)
    data = getattr(event, "event", None)
    message = getattr(data, "message", None)
    fields = {
        "event_type": _string_attr(header, "event_type"),
        "event_id": _string_attr(header, "event_id") or _string_attr(event, "uuid"),
        "message_id": _string_attr(message, "message_id"),
        "chat_id": _string_attr(message, "chat_id") or _string_attr(data, "chat_id"),
        "sender_id": _id_fields(getattr(getattr(data, "sender", None), "sender_id", None)),
        "operator_id": _id_fields(getattr(data, "operator_id", None)),
    }
    return " ".join(f"{name}={value}" for name, value in fields.items() if value)


def _string_attr(obj: Any, name: str) -> str:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else ""


def _id_fields(value: Any) -> str:
    for name in ("open_id", "user_id", "union_id"):
        id_value = _string_attr(value, name)
        if id_value:
            return id_value
    return ""
