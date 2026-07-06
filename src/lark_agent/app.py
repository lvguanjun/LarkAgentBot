from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from lark_agent.commands import ManagementCommandHandler
from lark_agent.config import AppConfig
from lark_agent.conversation import Conversation, Message
from lark_agent.images import build_user_message, expand_images_for_llm
from lark_agent.llm_client import LLMClient
from lark_agent.mcp.config import MCPConfig
from lark_agent.mcp.manager import MCPManager
from lark_agent.project import Project, ProjectStore
from lark_agent.router import MessageRouter
from lark_agent.tools import BuiltinTools, ToolDispatcher
from lark_agent.transport.base import (
    CardStreamer,
    ImageDownloader,
    IncomingMessage,
    MessageReactor,
    MessageSender,
    SendResult,
    StreamingCardState,
)


logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
STREAM_THROTTLE_INTERVAL_MS = 400
CARD_CONTENT_MAX_BYTES = 28_000

EMOJI_PROCESSING = "Typing"
EMOJI_DONE = "DONE"


class MissingThreadIdError(RuntimeError):
    """Raised when a new topic reply succeeds without returning a thread id."""


class BotApp:
    def __init__(
        self,
        config: AppConfig,
        *,
        sender: MessageSender,
        llm_client: LLMClient,
        router: MessageRouter | None = None,
        project_store: ProjectStore | None = None,
        mcp_manager_factory: Any | None = None,
        image_downloader: ImageDownloader | None = None,
        reactor: MessageReactor | None = None,
        card_streamer: CardStreamer | None = None,
    ) -> None:
        self.config = config
        self.sender = sender
        self.llm_client = llm_client
        self.router = router or MessageRouter(config.lark.bot_id)
        self.project_store = project_store or ProjectStore(
            config.data_dir,
            max_messages=config.conversation.max_messages,
        )
        self.mcp_manager_factory = mcp_manager_factory or (lambda mcp_config: MCPManager(mcp_config))
        self.command_handler = ManagementCommandHandler(config)
        self.image_downloader = image_downloader
        self.reactor = reactor
        self.card_streamer = card_streamer

    async def handle_message(self, message: IncomingMessage) -> str | None:
        if not self.router.should_respond(message):
            return None

        project = self.project_store.get_project(_project_key(message))
        existing_thread_id = self.router.get_existing_thread_id(message)
        user_text = self.router.normalized_text_content(message)
        if self.router.is_command(message):
            command_thread_id = existing_thread_id or "unthreaded"
            reply = self.command_handler.handle(message, project, command_thread_id, text=user_text)
            await self.sender.send_text(
                message.chat_id,
                reply,
                root_id=message.root_id,
                reply_to_message_id=message.message_id,
                reply_in_thread=existing_thread_id is not None,
            )
            return reply

        reaction_id = await _safe_add_reaction(self.reactor, message.message_id, EMOJI_PROCESSING)

        conversation = project.get_conversation(existing_thread_id) if existing_thread_id else None
        skills_registry = project.get_skills_registry()
        builtin_tools = BuiltinTools(skills_registry)
        mcp_manager = self._create_mcp_manager(project.get_mcp_config())

        user_message = await build_user_message(
            message_id=message.message_id,
            parts=self.router.normalized_content_parts(message),
            project_path=project.path,
            image_downloader=self.image_downloader,
        )
        turn_messages: list[Message] = [user_message]
        system_prompt = _build_system_prompt(
            project.get_agents_md(),
            skills_registry.get_system_prompt_fragment(),
        )

        try:
            if mcp_manager is not None:
                await mcp_manager.start()
            tool_dispatcher = ToolDispatcher(builtin_tools, mcp_manager)
            tools = tool_dispatcher.get_tools_for_llm()

            if self.card_streamer is not None:
                reply, send_result = await self._handle_streaming_reply(
                    message, project, conversation, turn_messages, system_prompt,
                    tools, tool_dispatcher,
                )
            else:
                reply, send_result = await self._handle_text_reply(
                    message, project, conversation, turn_messages, system_prompt,
                    tools, tool_dispatcher,
                )
        finally:
            if mcp_manager is not None:
                await mcp_manager.shutdown()

        final_thread_id = existing_thread_id or send_result.thread_id
        if final_thread_id is None:
            raise MissingThreadIdError(
                f"Feishu reply to message {message.message_id!r} did not return thread_id"
            )

        final_conversation = conversation or project.get_conversation(final_thread_id)
        for turn_message in turn_messages:
            final_conversation.append(turn_message)

        self.router.mark_thread_activated(message.chat_id, final_thread_id)

        await _safe_remove_reaction(self.reactor, message.message_id, reaction_id)
        await _safe_add_reaction(self.reactor, message.message_id, EMOJI_DONE)

        return reply

    async def _handle_text_reply(
        self,
        message: IncomingMessage,
        project: Project,
        conversation: Conversation | None,
        turn_messages: list[Message],
        system_prompt: str,
        tools: list[dict[str, Any]],
        tool_dispatcher: ToolDispatcher,
    ) -> tuple[str, SendResult]:
        reply = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            assistant_message = await self.llm_client.complete_message(
                system_prompt,
                _conversation_context(conversation, turn_messages, project_path=project.path),
                tools=tools,
            )
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                reply = _message_text(assistant_message)
                turn_messages.append({"role": "assistant", "content": reply})
                break

            turn_messages.append(assistant_message)
            for tool_call in tool_calls:
                result = await tool_dispatcher.call_tool(
                    _tool_call_name(tool_call),
                    _tool_call_arguments(tool_call),
                )
                turn_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tool_call_id(tool_call),
                        "content": result,
                    }
                )
        else:
            reply = "Error: tool loop exceeded maximum iterations"
            turn_messages.append({"role": "assistant", "content": reply})

        send_result = await self.sender.send_text(
            message.chat_id,
            reply,
            root_id=message.root_id,
            reply_to_message_id=message.message_id,
            reply_in_thread=True,
        )
        return reply, send_result

    async def _handle_streaming_reply(
        self,
        message: IncomingMessage,
        project: Project,
        conversation: Conversation | None,
        turn_messages: list[Message],
        system_prompt: str,
        tools: list[dict[str, Any]],
        tool_dispatcher: ToolDispatcher,
    ) -> tuple[str, SendResult]:
        assert self.card_streamer is not None

        card = await self.card_streamer.create_streaming_card()
        send_result = await self.card_streamer.send_card(
            message.chat_id,
            card.card_id,
            reply_to_message_id=message.message_id,
            reply_in_thread=True,
        )

        accumulated_text = ""
        throttle = StreamThrottle(STREAM_THROTTLE_INTERVAL_MS)

        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                iteration_text = ""
                final_tool_calls: list[dict[str, Any]] = []

                async for chunk in self.llm_client.stream_message(
                    system_prompt,
                    _conversation_context(conversation, turn_messages, project_path=project.path),
                    tools=tools,
                ):
                    if chunk.delta_text:
                        iteration_text += chunk.delta_text
                        if throttle.should_update():
                            display = accumulated_text + iteration_text
                            await self._update_card_safe(card, display)

                    if chunk.accumulated_tool_calls:
                        final_tool_calls = chunk.accumulated_tool_calls

                accumulated_text += iteration_text

                if not final_tool_calls:
                    turn_messages.append({"role": "assistant", "content": accumulated_text})
                    break

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": iteration_text or None,
                    "tool_calls": final_tool_calls,
                }
                turn_messages.append(assistant_msg)

                for tool_call in final_tool_calls:
                    tool_name = _tool_call_name(tool_call)
                    status_text = f"\n\n> 🔧 正在调用: {tool_name}"
                    await self._update_card_safe(card, accumulated_text + status_text)

                    result = await tool_dispatcher.call_tool(
                        tool_name,
                        _tool_call_arguments(tool_call),
                    )
                    turn_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": _tool_call_id(tool_call),
                            "content": result,
                        }
                    )
            else:
                accumulated_text += "\n\nError: tool loop exceeded maximum iterations"
                turn_messages.append({"role": "assistant", "content": accumulated_text})

            await self._update_card_safe(card, accumulated_text)
        finally:
            await self.card_streamer.close_streaming(card.card_id, card.next_sequence())

        return accumulated_text, send_result

    async def _update_card_safe(self, card: StreamingCardState, text: str) -> None:
        assert self.card_streamer is not None
        content = repair_markdown(text)
        if len(content.encode("utf-8")) > CARD_CONTENT_MAX_BYTES:
            content = _truncate_utf8(content, CARD_CONTENT_MAX_BYTES)
            content += "\n\n⚠️ 内容过长已截断"
        await self.card_streamer.update_card_content(
            card.card_id, card.element_id, content, card.next_sequence()
        )

    def _create_mcp_manager(self, mcp_config: MCPConfig) -> Any | None:
        if mcp_config.is_empty:
            return None
        return self.mcp_manager_factory(mcp_config)


class StreamThrottle:
    def __init__(self, interval_ms: int = 400) -> None:
        self._interval = interval_ms / 1000
        self._last_update = 0.0

    def should_update(self) -> bool:
        now = time.monotonic()
        if now - self._last_update >= self._interval:
            self._last_update = now
            return True
        return False


_CODE_FENCE_RE = re.compile(r"^(`{3,})", re.MULTILINE)


def repair_markdown(text: str) -> str:
    fences = _CODE_FENCE_RE.findall(text)
    if len(fences) % 2 != 0:
        text += "\n```"
    return text


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def _build_system_prompt(agents_md: str, skills_fragment: str) -> str:
    parts = [part.strip() for part in (agents_md, skills_fragment) if part.strip()]
    return "\n\n".join(parts)


def _project_key(message: IncomingMessage) -> str:
    if message.chat_type == "p2p":
        return message.sender_id
    return message.chat_id


def _conversation_context(
    conversation: Conversation | None,
    turn_messages: list[Message],
    *,
    project_path: Path,
) -> list[Message]:
    previous_messages = conversation.get_context() if conversation is not None else []
    return expand_images_for_llm([*previous_messages, *turn_messages], project_path=project_path)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _tool_call_id(tool_call: dict[str, Any]) -> str:
    value = tool_call.get("id")
    return value if isinstance(value, str) else ""


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""


def _tool_call_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return {}

    arguments = function.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str) or not arguments.strip():
        return {}

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _safe_add_reaction(
    reactor: MessageReactor | None, message_id: str, emoji_type: str
) -> str | None:
    if reactor is None:
        return None
    try:
        return await reactor.add_reaction(message_id, emoji_type)
    except Exception:
        logger.warning("Failed to add reaction %s to %s", emoji_type, message_id, exc_info=True)
        return None


async def _safe_remove_reaction(
    reactor: MessageReactor | None, message_id: str, reaction_id: str | None
) -> None:
    if reactor is None or reaction_id is None:
        return
    try:
        await reactor.remove_reaction(message_id, reaction_id)
    except Exception:
        logger.warning("Failed to remove reaction %s from %s", reaction_id, message_id, exc_info=True)
