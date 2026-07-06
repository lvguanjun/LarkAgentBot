from __future__ import annotations

import json
from typing import Any

from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from lark_agent.transport.base import SendResult


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
        reply_in_thread: bool = False,
    ) -> SendResult:
        content = json.dumps({"text": text}, ensure_ascii=False)
        if reply_to_message_id:
            body = (
                ReplyMessageRequestBody.builder()
                .content(content)
                .msg_type("text")
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
            _raise_for_failed_response(response, "reply")
            return _send_result(response)

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(content)
            .build()
        )
        request = (
            CreateMessageRequest.builder().receive_id_type("chat_id").request_body(body).build()
        )
        response = await self._message_api.acreate(request)
        _raise_for_failed_response(response, "create")
        return _send_result(response)


def _raise_for_failed_response(response: Any, action: str) -> None:
    success = getattr(response, "success", None)
    if not callable(success) or success():
        return

    code = getattr(response, "code", None)
    message = getattr(response, "msg", None) or "unknown error"
    log_id = response.get_log_id() if callable(getattr(response, "get_log_id", None)) else None
    suffix = f", log_id={log_id}" if log_id else ""
    raise LarkSendError(f"Feishu message {action} failed: code={code}, msg={message}{suffix}")


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
