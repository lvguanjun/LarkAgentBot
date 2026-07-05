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
