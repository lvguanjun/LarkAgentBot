from __future__ import annotations

import json
import logging
from typing import Any

from lark_oapi.api.cardkit.v1 import (
    ContentCardElementRequest,
    ContentCardElementRequestBody,
    CreateCardRequest,
    CreateCardRequestBody,
    SettingsCardRequest,
    SettingsCardRequestBody,
)
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from lark_agent.transport.base import SendResult, StreamingCardState

logger = logging.getLogger(__name__)

CARD_ELEMENT_ID = "md_main"


class CardStreamError(RuntimeError):
    """Raised when a CardKit API call fails."""


class LarkCardStreamer:
    def __init__(self, client: Any) -> None:
        self._card_api = client.cardkit.v1.card
        self._card_element_api = client.cardkit.v1.card_element
        self._message_api = client.im.v1.message

    async def create_streaming_card(self) -> StreamingCardState:
        card_json = _build_streaming_card_json()
        body = (
            CreateCardRequestBody.builder()
            .type("card_json")
            .data(json.dumps(card_json, ensure_ascii=False))
            .build()
        )
        request = CreateCardRequest.builder().request_body(body).build()
        response = await self._card_api.acreate(request)
        _raise_for_card_error(response, "create card entity")

        data = getattr(response, "data", None)
        card_id = getattr(data, "card_id", None)
        if not isinstance(card_id, str) or not card_id:
            raise CardStreamError("CardKit create returned empty card_id")

        return StreamingCardState(card_id=card_id, element_id=CARD_ELEMENT_ID)

    async def send_card(
        self,
        chat_id: str,
        card_id: str,
        *,
        reply_to_message_id: str | None = None,
        reply_in_thread: bool = False,
    ) -> SendResult:
        card_content = json.dumps(
            {"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False
        )

        if reply_to_message_id:
            body = (
                ReplyMessageRequestBody.builder()
                .content(card_content)
                .msg_type("interactive")
                .reply_in_thread(reply_in_thread)
                .build()
            )
            request = (
                ReplyMessageRequest.builder()
                .message_id(reply_to_message_id)
                .request_body(body)
                .build()
            )
            response = await self._message_api.areply(request)
            _raise_for_message_error(response, "reply card")
            return _send_result(response)

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(card_content)
            .build()
        )
        request = (
            CreateMessageRequest.builder().receive_id_type("chat_id").request_body(body).build()
        )
        response = await self._message_api.acreate(request)
        _raise_for_message_error(response, "create card message")
        return _send_result(response)

    async def update_card_content(
        self, card_id: str, element_id: str, content: str, sequence: int
    ) -> None:
        body = ContentCardElementRequestBody.builder().content(content).sequence(sequence).build()
        request = (
            ContentCardElementRequest.builder()
            .card_id(card_id)
            .element_id(element_id)
            .request_body(body)
            .build()
        )
        response = await self._card_element_api.acontent(request)
        _raise_for_card_error(response, "update card content")

    async def close_streaming(self, card_id: str, sequence: int) -> None:
        settings = json.dumps({"config": {"streaming_mode": False}}, ensure_ascii=False)
        body = SettingsCardRequestBody.builder().settings(settings).sequence(sequence).build()
        request = SettingsCardRequest.builder().card_id(card_id).request_body(body).build()
        response = await self._card_api.asettings(request)
        _raise_for_card_error(response, "close streaming")


def _build_streaming_card_json() -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "streaming_mode": True,
            "summary": {"content": "[生成中]"},
            "streaming_config": {
                "print_frequency_ms": {"default": 50},
                "print_step": {"default": 2},
                "print_strategy": "fast",
            },
        },
        "body": {"elements": [{"tag": "markdown", "content": "", "element_id": CARD_ELEMENT_ID}]},
    }


def _raise_for_card_error(response: Any, action: str) -> None:
    success = getattr(response, "success", None)
    if callable(success) and success():
        return

    code = getattr(response, "code", None)
    message = getattr(response, "msg", None) or "unknown error"
    raise CardStreamError(f"CardKit {action} failed: code={code}, msg={message}")


def _raise_for_message_error(response: Any, action: str) -> None:
    success = getattr(response, "success", None)
    if callable(success) and success():
        return

    code = getattr(response, "code", None)
    message = getattr(response, "msg", None) or "unknown error"
    raise CardStreamError(f"Feishu message {action} failed: code={code}, msg={message}")


def _send_result(response: Any) -> SendResult:
    data = getattr(response, "data", None)
    return SendResult(
        message_id=_string_attr(data, "message_id"),
        root_id=_string_attr(data, "root_id"),
        thread_id=_string_attr(data, "thread_id"),
    )


def _string_attr(obj: Any, name: str) -> str | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) and value else None
