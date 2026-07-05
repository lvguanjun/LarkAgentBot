from __future__ import annotations

import json
from typing import Any

from lark_agent.commands import ManagementCommandHandler
from lark_agent.config import AppConfig
from lark_agent.conversation import Conversation, Message
from lark_agent.llm_client import LLMClient
from lark_agent.mcp import MCPConfig, MCPManager
from lark_agent.project import ProjectStore
from lark_agent.router import MessageRouter
from lark_agent.tools import BuiltinTools, ToolDispatcher
from lark_agent.transport.base import IncomingMessage, MessageSender


MAX_TOOL_ITERATIONS = 5


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

        conversation = project.get_conversation(existing_thread_id) if existing_thread_id else None
        skills_registry = project.get_skills_registry()
        builtin_tools = BuiltinTools(skills_registry)
        mcp_manager = self._create_mcp_manager(project.get_mcp_config())

        turn_messages: list[Message] = [{"role": "user", "content": user_text}]
        system_prompt = _build_system_prompt(
            project.get_agents_md(),
            skills_registry.get_system_prompt_fragment(),
        )
        reply = ""

        try:
            if mcp_manager is not None:
                await mcp_manager.start()
            tool_dispatcher = ToolDispatcher(builtin_tools, mcp_manager)
            tools = tool_dispatcher.get_tools_for_llm()

            for _ in range(MAX_TOOL_ITERATIONS):
                assistant_message = await self.llm_client.complete_message(
                    system_prompt,
                    _conversation_context(conversation, turn_messages),
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
        finally:
            if mcp_manager is not None:
                await mcp_manager.shutdown()

        send_result = await self.sender.send_text(
            message.chat_id,
            reply,
            root_id=message.root_id,
            reply_to_message_id=message.message_id,
            reply_in_thread=True,
        )
        final_thread_id = existing_thread_id or send_result.thread_id
        if final_thread_id is None:
            raise MissingThreadIdError(
                f"Feishu reply to message {message.message_id!r} did not return thread_id"
            )

        final_conversation = conversation or project.get_conversation(final_thread_id)
        for turn_message in turn_messages:
            final_conversation.append(turn_message)

        self.router.mark_thread_activated(message.chat_id, final_thread_id)

        return reply

    def _create_mcp_manager(self, mcp_config: MCPConfig) -> Any | None:
        if mcp_config.is_empty:
            return None
        return self.mcp_manager_factory(mcp_config)


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
) -> list[Message]:
    previous_messages = conversation.get_context() if conversation is not None else []
    return [*previous_messages, *turn_messages]


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
