import base64
import json
from pathlib import Path
from typing import Any

import pytest

from lark_agent.app import BotApp, MissingThreadIdError, StreamThrottle, repair_markdown
from lark_agent.config import AppConfig, ConversationConfig, LLMConfig, LarkConfig
from lark_agent.conversation import Conversation
from lark_agent.llm_client import LLMClient, StreamChunk
from lark_agent.mcp.config import MCPConfig, MCPServerConfig
from lark_agent.transport.base import (
    DownloadedImage,
    EmojiPart,
    ImagePart,
    IncomingMessage,
    MentionPart,
    SendResult,
    StreamingCardState,
    TextPart,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-bytes"


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
    def __init__(self, *, thread_id: str | None = "omt-new") -> None:
        self.thread_id = thread_id
        self.sent: list[dict] = []

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        root_id: str | None = None,
        reply_to_message_id: str | None = None,
        reply_in_thread: bool = False,
    ) -> SendResult:
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "root_id": root_id,
                "reply_to_message_id": reply_to_message_id,
                "reply_in_thread": reply_in_thread,
            }
        )
        return SendResult(message_id="sent-1", root_id=root_id, thread_id=self.thread_id)


class FakeImageDownloader:
    def __init__(self, images: dict[str, DownloadedImage] | None = None) -> None:
        self.images = images or {}
        self.calls: list[tuple[str, str]] = []

    async def download_image(self, message_id: str, file_key: str) -> DownloadedImage:
        self.calls.append((message_id, file_key))
        image = self.images.get(file_key)
        if image is None:
            raise RuntimeError(f"missing image: {file_key}")
        return image


class FakeMCPManager:
    def __init__(self, config: MCPConfig, *, fail: bool = False) -> None:
        self.config = config
        self.fail = fail
        self.started = False
        self.shutdown_called = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def start(self) -> None:
        self.started = True

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "mcp__demo__lookup",
                    "description": "Lookup value",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append((name, args))
        if self.fail:
            return "Error: MCP tool failed"
        return f"MCP result for {args['query']}"

    async def shutdown(self) -> None:
        self.shutdown_called = True


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


def skills_root(project_root: Path) -> Path:
    return project_root / ".agents" / "skills"


def mcp_config_root(project_root: Path) -> Path:
    return project_root / ".agents"


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
        thread_id="omt-1",
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
            "reply_in_thread": True,
        }
    ]
    assert fake_llm.calls == [
        ("system prompt", [{"role": "user", "content": "hello"}]),
    ]
    history_path = tmp_path / "groups" / "chat-1" / "conversations" / "omt-1" / "history.jsonl"
    assert history_path.read_text(encoding="utf-8").splitlines() == [
        '{"role": "user", "content": "hello"}',
        '{"role": "assistant", "content": "assistant reply"}',
    ]


async def test_group_message_without_thread_persists_under_created_topic(tmp_path: Path) -> None:
    fake_llm = FakeLLM("assistant reply")
    sender = FakeSender(thread_id="omt-created")
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
        mentions=["bot-1"],
        content=[TextPart("hello")],
    )

    reply = await app.handle_message(message)

    assert reply == "assistant reply"
    assert sender.sent == [
        {
            "chat_id": "chat-1",
            "text": "assistant reply",
            "root_id": None,
            "reply_to_message_id": "msg-1",
            "reply_in_thread": True,
        }
    ]
    history_path = tmp_path / "groups" / "chat-1" / "conversations" / "omt-created" / "history.jsonl"
    assert history_path.read_text(encoding="utf-8").splitlines() == [
        '{"role": "user", "content": "hello"}',
        '{"role": "assistant", "content": "assistant reply"}',
    ]
    assert not (tmp_path / "groups" / "chat-1" / "conversations" / "main").exists()
    assert not (tmp_path / "groups" / "chat-1" / "conversations" / "msg-1").exists()


async def test_p2p_message_without_thread_uses_sender_project_and_created_topic(
    tmp_path: Path,
) -> None:
    fake_llm = FakeLLM("assistant reply")
    sender = FakeSender(thread_id="omt-p2p")
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-p2p",
        chat_type="p2p",
        sender_id="sender-open",
        content=[TextPart("hello")],
    )

    await app.handle_message(message)

    assert sender.sent[0]["reply_in_thread"] is True
    history_path = tmp_path / "groups" / "sender-open" / "conversations" / "omt-p2p" / "history.jsonl"
    assert history_path.read_text(encoding="utf-8").splitlines() == [
        '{"role": "user", "content": "hello"}',
        '{"role": "assistant", "content": "assistant reply"}',
    ]
    assert not (tmp_path / "groups" / "chat-p2p").exists()
    assert not (tmp_path / "groups" / "sender-open" / "conversations" / "chat-p2p").exists()


async def test_new_topic_missing_thread_id_fails_closed_without_history(tmp_path: Path) -> None:
    fake_llm = FakeLLM("assistant reply")
    sender = FakeSender(thread_id=None)
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
        mentions=["bot-1"],
        content=[TextPart("hello")],
    )

    with pytest.raises(MissingThreadIdError, match="did not return thread_id"):
        await app.handle_message(message)

    assert sender.sent[0]["reply_in_thread"] is True
    assert not (tmp_path / "groups" / "chat-1" / "conversations").exists()


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


async def test_app_handles_help_command_without_llm_or_history(tmp_path: Path) -> None:
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

    reply = await app.handle_message(message)

    assert reply is not None
    assert "/config" in reply
    assert sender.sent == [
        {
            "chat_id": "chat-1",
            "text": reply,
            "root_id": None,
            "reply_to_message_id": "msg-1",
            "reply_in_thread": False,
        }
    ]
    assert fake_llm.calls == []
    history_path = tmp_path / "groups" / "user-1" / "conversations" / "unthreaded" / "history.jsonl"
    assert not history_path.exists()


async def test_group_management_command_requires_mention(tmp_path: Path) -> None:
    sender = FakeSender()
    fake_llm = FakeLLM("assistant reply")
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
    )
    unmentioned = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        mentions=[],
        content=[TextPart("/help")],
    )
    mentioned = IncomingMessage(
        message_id="msg-2",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        mentions=["bot-1"],
        content=[TextPart("@_user_1 /help")],
    )

    assert await app.handle_message(unmentioned) is None
    reply = await app.handle_message(mentioned)

    assert reply is not None
    assert "/reset" in reply
    assert len(sender.sent) == 1
    assert sender.sent[0]["reply_to_message_id"] == "msg-2"
    assert fake_llm.calls == []


async def test_app_strips_leading_group_post_mention_before_llm(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    fake_llm = FakeLLM("assistant reply")
    sender = FakeSender()
    image_downloader = FakeImageDownloader(
        {"img-1": DownloadedImage(data=PNG_BYTES, mime_type="image/png", file_name="image.png")}
    )
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        image_downloader=image_downloader,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="group",
        sender_id="user-1",
        mentions=["bot-1"],
        content=[
            MentionPart(user_id="@_user_1", user_name="MiMi"),
            TextPart(" "),
            ImagePart(file_key="img-1"),
            TextPart("这张图说了啥，"),
            EmojiPart(emoji_type="Lark_Emoji_Glance_0"),
        ],
    )

    await app.handle_message(message)

    expected_url = f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"
    assert fake_llm.calls == [
        (
            "system prompt",
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": expected_url}},
                        {"type": "text", "text": "这张图说了啥，[表情: Lark_Emoji_Glance_0]"},
                    ],
                }
            ],
        ),
    ]
    assert image_downloader.calls == [("msg-1", "img-1")]
    history_path = tmp_path / "groups" / "chat-1" / "conversations" / "omt-new" / "history.jsonl"
    history_text = history_path.read_text(encoding="utf-8")
    assert "data:image/" not in history_text
    history = [json.loads(line) for line in history_text.splitlines()]
    assert history[0]["content"][0]["type"] == "image_ref"
    assert (tmp_path / "groups" / "chat-1" / history[0]["content"][0]["image_ref"]["path"]).exists()


async def test_app_rehydrates_history_image_refs_for_followup(tmp_path: Path) -> None:
    first_llm = FakeLLM("first reply")
    sender = FakeSender(thread_id="omt-thread")
    image_downloader = FakeImageDownloader(
        {"img-1": DownloadedImage(data=PNG_BYTES, mime_type="image/png", file_name="image.png")}
    )
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=first_llm),
        image_downloader=image_downloader,
    )
    await app.handle_message(
        IncomingMessage(
            message_id="msg-1",
            chat_id="chat-1",
            chat_type="p2p",
            sender_id="user-1",
            content=[TextPart("look "), ImagePart(file_key="img-1")],
        )
    )

    second_llm = FakeLLM("second reply")
    app.llm_client = LLMClient(LLMConfig(model="fake"), client=second_llm)
    await app.handle_message(
        IncomingMessage(
            message_id="msg-2",
            chat_id="chat-1",
            chat_type="p2p",
            sender_id="user-1",
            thread_id="omt-thread",
            content=[TextPart("刚才那张图呢？")],
        )
    )

    expected_url = f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"
    assert second_llm.calls[0][1] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look "},
                {"type": "image_url", "image_url": {"url": expected_url}},
            ],
        },
        {"role": "assistant", "content": "first reply"},
        {"role": "user", "content": "刚才那张图呢？"},
    ]


async def test_image_download_failure_degrades_to_text_placeholder(tmp_path: Path) -> None:
    fake_llm = FakeLLM("assistant reply")
    image_downloader = FakeImageDownloader()
    app = BotApp(
        make_config(tmp_path),
        sender=FakeSender(),
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        image_downloader=image_downloader,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("look "), ImagePart(file_key="missing")],
    )

    await app.handle_message(message)

    assert fake_llm.calls[0][1] == [
        {"role": "user", "content": "look [用户发送了一张图片，但图片下载失败]"}
    ]
    history_path = tmp_path / "groups" / "user-1" / "conversations" / "omt-new" / "history.jsonl"
    assert "image_ref" not in history_path.read_text(encoding="utf-8")


async def test_management_command_does_not_download_images(tmp_path: Path) -> None:
    fake_llm = FakeLLM("assistant reply")
    image_downloader = FakeImageDownloader(
        {"img-1": DownloadedImage(data=PNG_BYTES, mime_type="image/png")}
    )
    app = BotApp(
        make_config(tmp_path),
        sender=FakeSender(),
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        image_downloader=image_downloader,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("/help "), ImagePart(file_key="img-1")],
    )

    await app.handle_message(message)

    assert image_downloader.calls == []
    assert fake_llm.calls == []


async def test_config_command_redacts_sensitive_values(tmp_path: Path) -> None:
    config = AppConfig(
        data_dir=tmp_path,
        lark=LarkConfig(app_id="app-id-secret", app_secret="app-secret-value", bot_id="bot-1"),
        llm=LLMConfig(model="fake", api_key="sk-secret-value", base_url="https://llm.example"),
        conversation=ConversationConfig(max_messages=7),
    )
    sender = FakeSender()
    fake_llm = FakeLLM("assistant reply")
    app = BotApp(
        config,
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("/config")],
    )

    reply = await app.handle_message(message)

    assert reply is not None
    assert "llm.model: fake" in reply
    assert "conversation.max_messages: 7" in reply
    assert "llm.api_key: configured" in reply
    assert "lark.app_secret: configured" in reply
    assert "app-secret-value" not in reply
    assert "sk-secret-value" not in reply
    assert "app-id-secret" not in reply
    assert "https://llm.example" not in reply
    assert fake_llm.calls == []


async def test_skill_list_command_reports_empty_skills(tmp_path: Path) -> None:
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
        content=[TextPart("/skill list")],
    )

    reply = await app.handle_message(message)

    assert reply is not None
    assert "No skills configured." in reply
    assert fake_llm.calls == []


async def test_skill_list_command_reports_skills_and_discovery_errors(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    write_skill(skills_root(defaults), "writer", name="writer", description="Writes concise docs", body="body")
    invalid_dir = skills_root(defaults) / "broken"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "SKILL.md").write_text("---\nname: broken\n---\n\n# Broken\n", encoding="utf-8")
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
        content=[TextPart("/skill list")],
    )

    reply = await app.handle_message(message)

    assert reply is not None
    assert "- writer: Writes concise docs" in reply
    assert "Skill discovery errors:" in reply
    assert "description" in reply
    assert fake_llm.calls == []


async def test_mcp_list_command_redacts_env_values_and_does_not_start_manager(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    mcp_dir = mcp_config_root(defaults)
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "mcp.yaml").write_text(
        """
mcpServers:
  demo:
    command: python
    args: ["-m", "demo"]
    env:
      TOKEN: literal-token
""",
        encoding="utf-8",
    )
    sender = FakeSender()
    fake_llm = FakeLLM("assistant reply")
    managers: list[FakeMCPManager] = []

    def make_manager(config: MCPConfig) -> FakeMCPManager:
        manager = FakeMCPManager(config)
        managers.append(manager)
        return manager

    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        mcp_manager_factory=make_manager,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("/mcp list")],
    )

    reply = await app.handle_message(message)

    assert reply is not None
    assert "demo" in reply
    assert "args=2" in reply
    assert "env_keys=TOKEN" in reply
    assert "literal-token" not in reply
    assert managers == []
    assert fake_llm.calls == []


async def test_reset_command_clears_only_current_conversation(tmp_path: Path) -> None:
    current = Conversation(tmp_path / "groups" / "user-1" / "conversations" / "omt-reset")
    other = Conversation(tmp_path / "groups" / "user-1" / "conversations" / "root-2")
    current.append({"role": "user", "content": "current"})
    other.append({"role": "user", "content": "other"})
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
        thread_id="omt-reset",
        content=[TextPart("/reset")],
    )

    reply = await app.handle_message(message)

    assert reply == "Conversation reset for thread: omt-reset"
    assert current.get_full_history() == []
    assert other.get_full_history() == [{"role": "user", "content": "other"}]
    assert fake_llm.calls == []


async def test_unknown_management_command_points_to_help(tmp_path: Path) -> None:
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
        content=[TextPart("/unknown")],
    )

    reply = await app.handle_message(message)

    assert reply is not None
    assert "Unknown command: /unknown" in reply
    assert "Use /help" in reply
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
        skills_root(defaults),
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
        skills_root(defaults),
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
    history_path = tmp_path / "groups" / "user-1" / "conversations" / "omt-new" / "history.jsonl"
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


async def test_app_runs_mcp_tool_loop_and_persists_full_chain(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    mcp_dir = mcp_config_root(defaults)
    mcp_dir.mkdir()
    (mcp_dir / "mcp.yaml").write_text(
        """
mcpServers:
  demo:
    command: python
""",
        encoding="utf-8",
    )
    fake_llm = FakeToolLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-mcp-1",
                        "type": "function",
                        "function": {"name": "mcp__demo__lookup", "arguments": '{"query": "alpha"}'},
                    }
                ],
            },
            {"role": "assistant", "content": "MCP final answer"},
        ]
    )
    sender = FakeSender()
    managers: list[FakeMCPManager] = []

    def make_manager(config: MCPConfig) -> FakeMCPManager:
        manager = FakeMCPManager(config)
        managers.append(manager)
        return manager

    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        mcp_manager_factory=make_manager,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("use mcp")],
    )

    reply = await app.handle_message(message)

    assert reply == "MCP final answer"
    assert len(managers) == 1
    assert managers[0].config.servers == {"demo": MCPServerConfig(name="demo", command="python")}
    assert managers[0].started is True
    assert managers[0].shutdown_called is True
    assert managers[0].calls == [("mcp__demo__lookup", {"query": "alpha"})]
    assert fake_llm.calls[0][2] == [
        {
            "type": "function",
            "function": {
                "name": "mcp__demo__lookup",
                "description": "Lookup value",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]
    history_path = tmp_path / "groups" / "user-1" / "conversations" / "omt-new" / "history.jsonl"
    assert history_path.read_text(encoding="utf-8").splitlines() == [
        '{"role": "user", "content": "use mcp"}',
        (
            '{"role": "assistant", "content": null, "tool_calls": '
            '[{"id": "call-mcp-1", "type": "function", "function": '
            '{"name": "mcp__demo__lookup", "arguments": "{\\"query\\": \\"alpha\\"}"}}]}'
        ),
        '{"role": "tool", "tool_call_id": "call-mcp-1", "content": "MCP result for alpha"}',
        '{"role": "assistant", "content": "MCP final answer"}',
    ]


async def test_app_writes_mcp_tool_error_as_tool_result(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    mcp_dir = mcp_config_root(defaults)
    mcp_dir.mkdir()
    (mcp_dir / "mcp.yaml").write_text(
        """
mcpServers:
  demo:
    command: python
""",
        encoding="utf-8",
    )
    fake_llm = FakeToolLLM(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-mcp-1",
                        "type": "function",
                        "function": {"name": "mcp__demo__lookup", "arguments": '{"query": "alpha"}'},
                    }
                ],
            },
            {"role": "assistant", "content": "I saw the MCP error."},
        ]
    )
    sender = FakeSender()

    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        mcp_manager_factory=lambda config: FakeMCPManager(config, fail=True),
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("use mcp")],
    )

    reply = await app.handle_message(message)

    assert reply == "I saw the MCP error."
    assert fake_llm.calls[1][1][-1] == {
        "role": "tool",
        "tool_call_id": "call-mcp-1",
        "content": "Error: MCP tool failed",
    }


# --- Fakes for streaming / reactor / card tests ---


class FakeReactor:
    def __init__(self) -> None:
        self.reactions: list[tuple[str, str, str]] = []
        self.removals: list[tuple[str, str]] = []
        self._next_id = 0

    async def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        self._next_id += 1
        rid = f"reaction-{self._next_id}"
        self.reactions.append((message_id, emoji_type, rid))
        return rid

    async def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        self.removals.append((message_id, reaction_id))


class FakeCardStreamer:
    def __init__(self, *, thread_id: str = "omt-card") -> None:
        self.thread_id = thread_id
        self.cards_created: list[str] = []
        self.cards_sent: list[dict] = []
        self.updates: list[tuple[str, str, str, int]] = []
        self.closed: list[tuple[str, int]] = []
        self._card_counter = 0

    async def create_streaming_card(self) -> StreamingCardState:
        self._card_counter += 1
        card_id = f"card-{self._card_counter}"
        self.cards_created.append(card_id)
        return StreamingCardState(card_id=card_id)

    async def send_card(
        self,
        chat_id: str,
        card_id: str,
        *,
        reply_to_message_id: str | None = None,
        reply_in_thread: bool = False,
    ) -> SendResult:
        self.cards_sent.append({
            "chat_id": chat_id,
            "card_id": card_id,
            "reply_to_message_id": reply_to_message_id,
            "reply_in_thread": reply_in_thread,
        })
        return SendResult(message_id="card-msg-1", thread_id=self.thread_id)

    async def update_card_content(
        self, card_id: str, element_id: str, content: str, sequence: int
    ) -> None:
        self.updates.append((card_id, element_id, content, sequence))

    async def close_streaming(self, card_id: str, sequence: int) -> None:
        self.closed.append((card_id, sequence))


class FakeStreamingLLM:
    def __init__(self, chunks_per_call: list[list[StreamChunk]]) -> None:
        self._chunks_per_call = chunks_per_call
        self.calls: list[tuple[str, list[dict], list[dict] | None]] = []

    async def stream_message(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
    ):
        self.calls.append((system_prompt, messages, tools))
        chunks = self._chunks_per_call.pop(0)
        for chunk in chunks:
            yield chunk


# --- repair_markdown tests ---


def test_repair_markdown_closes_unclosed_code_fence() -> None:
    assert repair_markdown("hello\n```python\ncode") == "hello\n```python\ncode\n```"


def test_repair_markdown_leaves_closed_code_fence() -> None:
    text = "hello\n```python\ncode\n```"
    assert repair_markdown(text) == text


def test_repair_markdown_handles_no_fences() -> None:
    assert repair_markdown("just text") == "just text"


def test_repair_markdown_handles_multiple_unclosed() -> None:
    text = "a\n```\ncode1\n```\nb\n```\ncode2"
    assert repair_markdown(text) == text + "\n```"


# --- StreamThrottle tests ---


def test_stream_throttle_first_call_always_returns_true() -> None:
    throttle = StreamThrottle(1000)
    assert throttle.should_update() is True


def test_stream_throttle_subsequent_calls_within_interval_return_false() -> None:
    throttle = StreamThrottle(10_000)
    throttle.should_update()
    assert throttle.should_update() is False


# --- Streaming reply tests ---


async def test_streaming_reply_creates_card_and_streams(tmp_path: Path) -> None:
    fake_llm = FakeStreamingLLM([
        [
            StreamChunk(delta_text="Hello "),
            StreamChunk(delta_text="world!"),
            StreamChunk(finish_reason="stop"),
        ],
    ])
    sender = FakeSender()
    card_streamer = FakeCardStreamer()
    reactor = FakeReactor()
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        reactor=reactor,
        card_streamer=card_streamer,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("hello")],
    )

    reply = await app.handle_message(message)

    assert reply == "Hello world!"
    assert card_streamer.cards_created == ["card-1"]
    assert card_streamer.cards_sent[0]["card_id"] == "card-1"
    assert card_streamer.cards_sent[0]["reply_in_thread"] is True
    assert len(card_streamer.closed) == 1
    assert card_streamer.closed[0][0] == "card-1"

    final_update = card_streamer.updates[-1]
    assert final_update[2] == "Hello world!"

    assert sender.sent == []


async def test_streaming_reply_emoji_lifecycle(tmp_path: Path) -> None:
    fake_llm = FakeStreamingLLM([
        [StreamChunk(delta_text="reply", finish_reason="stop")],
    ])
    reactor = FakeReactor()
    card_streamer = FakeCardStreamer()
    app = BotApp(
        make_config(tmp_path),
        sender=FakeSender(),
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        reactor=reactor,
        card_streamer=card_streamer,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("hello")],
    )

    await app.handle_message(message)

    assert reactor.reactions[0] == ("msg-1", "Typing", "reaction-1")
    assert reactor.removals == [("msg-1", "reaction-1")]
    assert reactor.reactions[1] == ("msg-1", "DONE", "reaction-2")


async def test_streaming_reply_with_tool_calls(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "AGENTS.md").write_text("system prompt", encoding="utf-8")
    write_skill(
        skills_root(defaults), "writer",
        name="writer", description="Writes docs", body="Use short sentences.",
    )

    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "read_skill", "arguments": '{"name": "writer"}'},
    }
    fake_llm = FakeStreamingLLM([
        [
            StreamChunk(delta_text="Let me check..."),
            StreamChunk(
                finish_reason="tool_calls",
                accumulated_tool_calls=[tool_call],
            ),
        ],
        [
            StreamChunk(delta_text=" Here is the skill content."),
            StreamChunk(finish_reason="stop"),
        ],
    ])
    card_streamer = FakeCardStreamer()
    app = BotApp(
        make_config(tmp_path),
        sender=FakeSender(),
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        card_streamer=card_streamer,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("use the writer skill")],
    )

    reply = await app.handle_message(message)

    assert reply == "Let me check... Here is the skill content."
    tool_status_updates = [u for u in card_streamer.updates if "正在调用" in u[2]]
    assert len(tool_status_updates) >= 1
    assert "read_skill" in tool_status_updates[0][2]

    final_update = card_streamer.updates[-1]
    assert "正在调用" not in final_update[2]

    history_path = tmp_path / "groups" / "user-1" / "conversations" / "omt-card" / "history.jsonl"
    history_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 4
    assert json.loads(history_lines[0])["role"] == "user"
    assert json.loads(history_lines[1])["role"] == "assistant"
    assert json.loads(history_lines[2])["role"] == "tool"
    assert json.loads(history_lines[3])["role"] == "assistant"


async def test_no_card_streamer_falls_back_to_text(tmp_path: Path) -> None:
    """When card_streamer is None but reactor is present, text path is used."""
    fake_llm = FakeLLM("text reply")
    reactor = FakeReactor()
    sender = FakeSender()
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=fake_llm),
        reactor=reactor,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("hello")],
    )

    reply = await app.handle_message(message)

    assert reply == "text reply"
    assert sender.sent[0]["text"] == "text reply"
    assert reactor.reactions[0][1] == "Typing"
    assert reactor.reactions[1][1] == "DONE"


async def test_command_does_not_trigger_reaction_or_card(tmp_path: Path) -> None:
    reactor = FakeReactor()
    card_streamer = FakeCardStreamer()
    sender = FakeSender()
    app = BotApp(
        make_config(tmp_path),
        sender=sender,
        llm_client=LLMClient(LLMConfig(model="fake"), client=FakeLLM("unused")),
        reactor=reactor,
        card_streamer=card_streamer,
    )
    message = IncomingMessage(
        message_id="msg-1",
        chat_id="chat-1",
        chat_type="p2p",
        sender_id="user-1",
        content=[TextPart("/help")],
    )

    await app.handle_message(message)

    assert reactor.reactions == []
    assert card_streamer.cards_created == []
    assert sender.sent[0]["text"] is not None
