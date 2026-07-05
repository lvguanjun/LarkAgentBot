from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from lark_agent.config import AppConfig, ConversationConfig, LLMConfig, LarkConfig
from lark_agent.main import validate_lark_config
from lark_agent.transport.base import ImagePart, TextPart
from lark_agent.transport.lark import (
    LarkMessageEventAdapter,
    LarkMessageSender,
    LarkSendError,
    LarkWebSocketBotRunner,
    TTLSeenCache,
)


class FakeMessageApi:
    def __init__(self, *, response: Any | None = None) -> None:
        self.response = response or FakeResponse()
        self.replies: list[Any] = []
        self.creates: list[Any] = []

    async def areply(self, request: Any) -> Any:
        self.replies.append(request)
        return self.response

    async def acreate(self, request: Any) -> Any:
        self.creates.append(request)
        return self.response


class FakeResponse:
    def __init__(self, *, ok: bool = True, code: int = 0, msg: str = "ok") -> None:
        self.ok = ok
        self.code = code
        self.msg = msg

    def success(self) -> bool:
        return self.ok

    def get_log_id(self) -> str:
        return "log-1"


class FakeLarkClient:
    def __init__(self, message_api: FakeMessageApi) -> None:
        self.im = SimpleNamespace(v1=SimpleNamespace(message=message_api))


class FakeBotApp:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail = False

    async def handle_message(self, message: Any) -> str | None:
        self.messages.append(message)
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("boom")
        return "ok"


def make_event(
    *,
    event_id: str | None = "event-1",
    message_id: str | None = "msg-1",
    chat_type: str = "group",
    message_type: str = "text",
    content: dict[str, Any] | str | None = None,
    root_id: str | None = "root-1",
) -> Any:
    if content is None:
        content = {"text": "hello"}
    content_value = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    header = SimpleNamespace(event_id=event_id) if event_id is not None else None
    message = SimpleNamespace(
        message_id=message_id,
        chat_id="chat-1",
        chat_type=chat_type,
        message_type=message_type,
        content=content_value,
        root_id=root_id,
        mentions=[
            SimpleNamespace(
                id=SimpleNamespace(open_id="bot-open", user_id="bot-user", union_id="bot-union")
            )
        ],
    )
    sender = SimpleNamespace(sender_id=SimpleNamespace(open_id="sender-open"))
    return SimpleNamespace(
        header=header,
        uuid=None,
        event=SimpleNamespace(sender=sender, message=message),
    )


def test_adapter_converts_text_message() -> None:
    event = make_event()

    message = LarkMessageEventAdapter().to_incoming_message(event)

    assert message is not None
    assert message.message_id == "msg-1"
    assert message.chat_id == "chat-1"
    assert message.chat_type == "group"
    assert message.sender_id == "sender-open"
    assert message.root_id == "root-1"
    assert message.mentions == ["bot-open", "bot-user", "bot-union"]
    assert message.content == [TextPart("hello")]
    assert message.raw_event is event


def test_adapter_converts_post_message_in_order() -> None:
    event = make_event(
        message_type="post",
        content={
            "zh_cn": {
                "title": "ignored",
                "content": [
                    [
                        {"tag": "text", "text": "look "},
                        {"tag": "img", "image_key": "img-1"},
                        {"tag": "a", "text": "link", "href": "https://example.test"},
                    ]
                ],
            }
        },
    )

    message = LarkMessageEventAdapter().to_incoming_message(event)

    assert message is not None
    assert message.content == [
        TextPart("look "),
        ImagePart(file_key="img-1"),
        TextPart("link"),
    ]


def test_adapter_converts_image_message() -> None:
    event = make_event(message_type="image", content={"image_key": "img-1"})

    message = LarkMessageEventAdapter().to_incoming_message(event)

    assert message is not None
    assert message.content == [ImagePart(file_key="img-1")]


def test_adapter_ignores_unknown_chat_type_and_message_type() -> None:
    adapter = LarkMessageEventAdapter()

    assert adapter.to_incoming_message(make_event(chat_type="unknown")) is None
    assert adapter.to_incoming_message(make_event(message_type="audio", content={"file_key": "f"})) is None


def test_adapter_dedupe_key_prefers_event_id_then_message_id() -> None:
    adapter = LarkMessageEventAdapter()

    assert adapter.dedupe_key(make_event(event_id="event-1", message_id="msg-1")) == "event-1"
    assert adapter.dedupe_key(make_event(event_id=None, message_id="msg-1")) == "msg-1"
    assert adapter.dedupe_key(make_event(event_id=None, message_id=None)) is None


async def test_sender_replies_in_thread_when_reply_target_exists() -> None:
    message_api = FakeMessageApi()
    sender = LarkMessageSender(FakeLarkClient(message_api))

    await sender.send_text("chat-1", "你好", root_id="root-1", reply_to_message_id="msg-1")

    assert message_api.creates == []
    request = message_api.replies[0]
    assert request.message_id == "msg-1"
    assert request.body.msg_type == "text"
    assert request.body.reply_in_thread is True
    assert json.loads(request.body.content) == {"text": "你好"}


async def test_sender_creates_message_without_reply_target() -> None:
    message_api = FakeMessageApi()
    sender = LarkMessageSender(FakeLarkClient(message_api))

    await sender.send_text("chat-1", "hello")

    assert message_api.replies == []
    request = message_api.creates[0]
    assert request.queries == [("receive_id_type", "chat_id")]
    assert request.body.receive_id == "chat-1"
    assert request.body.msg_type == "text"
    assert json.loads(request.body.content) == {"text": "hello"}


async def test_sender_raises_clear_error_on_failed_response() -> None:
    message_api = FakeMessageApi(response=FakeResponse(ok=False, code=999, msg="bad request"))
    sender = LarkMessageSender(FakeLarkClient(message_api))

    with pytest.raises(LarkSendError, match="code=999"):
        await sender.send_text("chat-1", "hello")


async def test_runner_schedules_background_task_and_dedupes() -> None:
    app = FakeBotApp()
    runner = LarkWebSocketBotRunner(
        app_id="app",
        app_secret="secret",
        app=app,  # type: ignore[arg-type]
        dedupe_cache=TTLSeenCache(ttl_seconds=60),
    )
    event = make_event()

    runner.handle_event(event)
    runner.handle_event(event)

    assert len(app.messages) == 0
    await asyncio.wait_for(app.started.wait(), timeout=1)
    assert len(app.messages) == 1
    app.release.set()
    await asyncio.sleep(0)


async def test_runner_skips_event_without_stable_dedupe_key() -> None:
    app = FakeBotApp()
    runner = LarkWebSocketBotRunner(
        app_id="app",
        app_secret="secret",
        app=app,  # type: ignore[arg-type]
    )

    runner.handle_event(make_event(event_id=None, message_id=None))
    await asyncio.sleep(0)

    assert app.messages == []


async def test_runner_logs_background_errors_without_propagating() -> None:
    app = FakeBotApp()
    app.fail = True
    runner = LarkWebSocketBotRunner(
        app_id="app",
        app_secret="secret",
        app=app,  # type: ignore[arg-type]
    )

    runner.handle_event(make_event())
    await asyncio.wait_for(app.started.wait(), timeout=1)
    app.release.set()
    for _ in range(10):
        if not runner._tasks:
            break
        await asyncio.sleep(0)

    assert len(app.messages) == 1
    assert runner._tasks == set()


def test_runner_builds_registered_feishu_event_handler() -> None:
    runner = LarkWebSocketBotRunner(
        app_id="app",
        app_secret="secret",
        app=SimpleNamespace(handle_message=lambda message: None),  # type: ignore[arg-type]
    )

    handler = runner.build_event_handler()

    assert "p2.im.message.receive_v1" in handler._processorMap


def test_validate_lark_config_fails_fast_for_missing_credentials(tmp_path) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        lark=LarkConfig(app_id="app"),
        llm=LLMConfig(),
        conversation=ConversationConfig(),
    )

    with pytest.raises(ValueError, match="lark.app_secret, lark.bot_id"):
        validate_lark_config(config)
