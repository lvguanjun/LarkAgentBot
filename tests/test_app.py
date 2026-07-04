from pathlib import Path

from lark_agent.app import BotApp
from lark_agent.config import AppConfig, ConversationConfig, LLMConfig, LarkConfig
from lark_agent.llm_client import LLMClient
from lark_agent.transport.base import ImagePart, IncomingMessage, TextPart


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system_prompt: str, messages: list[dict]) -> str:
        self.calls.append((system_prompt, messages))
        return self.reply


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        root_id: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> None:
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "root_id": root_id,
                "reply_to_message_id": reply_to_message_id,
            }
        )


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data_dir=tmp_path,
        lark=LarkConfig(bot_id="bot-1"),
        llm=LLMConfig(model="fake"),
        conversation=ConversationConfig(max_messages=20),
    )


async def test_app_handles_text_message_end_to_end(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    fake_llm = FakeLLM("assistant reply")
    sender = FakeSender()
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        root_id="root-1",
        mentions=["bot-1"],
        content=[TextPart("hello")],
    )

    reply = await app.handle_message(message)

    assert reply == "assistant reply"
    assert sender.sent == [
        {
            "chat_id": "chat-1",
            "text": "assistant reply",
            "root_id": "root-1",
            "reply_to_message_id": "msg-1",
        }
    ]
    assert fake_llm.calls == [
        ("system prompt", [{"role": "user", "content": "hello"}]),
    ]
    history_path = tmp_path / "groups" / "chat-1" / "conversations" / "root-1" / "history.jsonl"
    assert history_path.read_text(encoding="utf-8").splitlines() == [
        '{"role": "user", "content": "hello"}',
        '{"role": "assistant", "content": "assistant reply"}',
    ]


async def test_app_ignores_unmentioned_group_message(tmp_path: Path) -> None:
    sender = FakeSender()
    fake_llm = FakeLLM("assistant reply")
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        mentions=[],
        content=[TextPart("hello")],
    )

    assert await app.handle_message(message) is None
    assert sender.sent == []
    assert fake_llm.calls == []


async def test_app_skips_management_command_boundary(tmp_path: Path) -> None:
    sender = FakeSender()
    fake_llm = FakeLLM("assistant reply")
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("/help")],
    )

    assert await app.handle_message(message) is None
    assert sender.sent == []
    assert fake_llm.calls == []


def test_image_part_is_downgraded_to_text_placeholder() -> None:
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("look "), ImagePart(file_key="file-1")],
    )

    assert message.to_openai_message() == {
        "role": "user",
        "content": "look [用户发送了一张图片]",
    }
