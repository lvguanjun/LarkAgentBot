from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from lark_agent.config import AppConfig, ConversationConfig, LLMConfig, LarkConfig
from lark_agent.main import build_runner, configure_logging, validate_lark_config
from lark_agent.transport.lark.bot_info import LarkBotInfo
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


IGNORED_LARK_EVENT_TYPES = (
    "im.chat.member.bot.added_v1",
    "im.chat.member.bot.deleted_v1",
    "im.message.reaction.created_v1",
    "im.message.reaction.deleted_v1",
    "drive.notice.comment_add_v1",
    "vc.meeting.participant_meeting_ended_v1",
    "minutes.minute.generated_v1",
)


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


def make_ignored_event(event_type: str = "im.chat.member.bot.added_v1") -> Any:
    return SimpleNamespace(
        header=SimpleNamespace(
            event_type=event_type,
            event_id="event-ignored",
        ),
        event=SimpleNamespace(
            chat_id="chat-1",
            operator_id=SimpleNamespace(open_id="operator-open"),
            name="agent",
            external=False,
        ),
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
    for event_type in IGNORED_LARK_EVENT_TYPES:
        assert f"p2.{event_type}" in handler._processorMap


@pytest.mark.parametrize("event_type", IGNORED_LARK_EVENT_TYPES)
def test_runner_dispatches_ignored_event_through_lark_handler(
    event_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FakeBotApp()
    runner = LarkWebSocketBotRunner(
        app_id="app",
        app_secret="secret",
        app=app,  # type: ignore[arg-type]
    )
    handler = runner.build_event_handler()
    payload = {
        "schema": "2.0",
        "header": {
            "event_id": "event-ignored",
            "event_type": event_type,
            "create_time": "1783255282055",
            "token": "",
            "app_id": "app",
            "tenant_key": "tenant",
        },
        "event": {
            "chat_id": "chat-1",
            "operator_id": {"open_id": "operator-open"},
            "external": False,
            "name": "agent",
        },
    }

    with caplog.at_level(logging.INFO, logger="lark_agent.transport.lark.runner"):
        handler._do_without_validation(json.dumps(payload).encode())

    assert app.messages == []
    assert "Ignoring Feishu event without business handler" in caplog.text


async def test_runner_logs_ignored_event_without_scheduling_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FakeBotApp()
    runner = LarkWebSocketBotRunner(
        app_id="app",
        app_secret="secret",
        app=app,  # type: ignore[arg-type]
    )

    with caplog.at_level(logging.INFO, logger="lark_agent.transport.lark.runner"):
        runner.handle_ignored_event(make_ignored_event())

    await asyncio.sleep(0)

    assert app.messages == []
    assert "Ignoring Feishu event without business handler" in caplog.text
    assert "event_type=im.chat.member.bot.added_v1" in caplog.text
    assert "event_id=event-ignored" in caplog.text
    assert "chat_id=chat-1" in caplog.text
    assert "operator_id=operator-open" in caplog.text


def test_validate_lark_config_fails_fast_for_missing_credentials(tmp_path) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        lark=LarkConfig(app_id="app"),
        llm=LLMConfig(),
        conversation=ConversationConfig(),
    )

    with pytest.raises(ValueError, match="lark.app_secret"):
        validate_lark_config(config)


def test_validate_lark_config_does_not_require_env_bot_id(tmp_path) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        lark=LarkConfig(app_id="app", app_secret="secret"),
        llm=LLMConfig(),
        conversation=ConversationConfig(),
    )

    validate_lark_config(config)


def test_build_runner_fetches_bot_open_id_for_router(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    fake_client = FakeLarkClient(FakeMessageApi())
    requested_clients: list[tuple[str, str]] = []

    class FakeClientBuilder:
        def __init__(self) -> None:
            self._app_id = ""
            self._app_secret = ""

        def app_id(self, app_id: str) -> "FakeClientBuilder":
            self._app_id = app_id
            return self

        def app_secret(self, app_secret: str) -> "FakeClientBuilder":
            self._app_secret = app_secret
            return self

        def build(self) -> FakeLarkClient:
            requested_clients.append((self._app_id, self._app_secret))
            return fake_client

    monkeypatch.setattr(
        "lark_agent.main.lark.Client.builder",
        lambda: FakeClientBuilder(),
    )
    monkeypatch.setattr(
        "lark_agent.main.fetch_lark_bot_info",
        lambda client: LarkBotInfo(
            activate_status=2,
            app_name="agent",
            avatar_url="",
            ip_white_list=(),
            open_id="ou_from_api",
        ),
    )

    config = AppConfig(
        data_dir=tmp_path,
        lark=LarkConfig(app_id="app", app_secret="secret", bot_id="stale-env-id"),
        llm=LLMConfig(model="fake"),
        conversation=ConversationConfig(),
    )

    runner = build_runner(config)

    assert requested_clients == [("app", "secret")]
    assert runner.app.config.lark.bot_id == "ou_from_api"
    assert runner.app.router.bot_id == "ou_from_api"


def test_configure_logging_emits_package_info(capsys: pytest.CaptureFixture[str]) -> None:
    package_logger = logging.getLogger("lark_agent")
    old_handlers = list(package_logger.handlers)
    old_level = package_logger.level
    old_propagate = package_logger.propagate
    for handler in old_handlers:
        package_logger.removeHandler(handler)

    try:
        configure_logging()
        logging.getLogger("lark_agent.transport.lark.runner").info("probe event log")

        captured = capsys.readouterr()

        assert "[lark_agent.transport.lark.runner]" in captured.err
        assert "probe event log" in captured.err
    finally:
        for handler in list(package_logger.handlers):
            package_logger.removeHandler(handler)
        for handler in old_handlers:
            package_logger.addHandler(handler)
        package_logger.setLevel(old_level)
        package_logger.propagate = old_propagate
