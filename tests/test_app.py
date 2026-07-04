from pathlib import Path
from typing import Any

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


class FakeToolLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, list[dict], list[dict] | None]] = []

    def complete_message(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((system_prompt, messages, tools))
        return self.responses.pop(0)


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


def write_skill(root: Path, dirname: str, *, name: str, description: str, body: str) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


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


async def test_app_injects_agents_and_skills_without_full_skill_body(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    write_skill(
        defaults / "skills",
        "writer",
        name="writer",
        description="Writes concise docs",
        body="SECRET FULL BODY",
    )
    fake_llm = FakeToolLLM([{"role": "assistant", "content": "assistant reply"}])
    sender = FakeSender()
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
        content=[TextPart("hello")],
    )

    await app.handle_message(message)

    system_prompt, _, tools = fake_llm.calls[0]
    assert "system prompt" in system_prompt
    assert "- writer: Writes concise docs" in system_prompt
    assert "SECRET FULL BODY" not in system_prompt
    assert tools is not None
    assert tools[0]["function"]["name"] == "read_skill"


async def test_app_runs_read_skill_tool_loop_and_persists_full_chain(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    write_skill(
        defaults / "skills",
        "writer",
        name="writer",
        description="Writes concise docs",
        body="# Writer\n\nUse short sentences.",
    )
    fake_llm = FakeToolLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_skill", "arguments": '{"name": "writer"}'},
                    }
                ],
            },
            {"role": "assistant", "content": "I loaded the writer skill."},
        ]
    )
    sender = FakeSender()
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
        content=[TextPart("use the writer skill")],
    )

    reply = await app.handle_message(message)

    assert reply == "I loaded the writer skill."
    assert sender.sent[0]["text"] == "I loaded the writer skill."
    assert len(fake_llm.calls) == 2
    assert fake_llm.calls[1][1][-1]["role"] == "tool"
    assert "Use short sentences." in fake_llm.calls[1][1][-1]["content"]
    history_path = tmp_path / "groups" / "chat-1" / "conversations" / "chat-1" / "history.jsonl"
    assert history_path.read_text(encoding="utf-8").splitlines() == [
        '{"role": "user", "content": "use the writer skill"}',
        (
            '{"role": "assistant", "content": null, "tool_calls": '
            '[{"id": "call-1", "type": "function", "function": '
            '{"name": "read_skill", "arguments": "{\\"name\\": \\"writer\\"}"}}]}'
        ),
        (
            '{"role": "tool", "tool_call_id": "call-1", "content": '
            '"---\\nname: writer\\ndescription: Writes concise docs\\n---\\n\\n# Writer\\n\\nUse short sentences.\\n"}'
        ),
        '{"role": "assistant", "content": "I loaded the writer skill."}',
    ]
