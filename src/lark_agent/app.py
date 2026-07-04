from __future__ import annotations

import json
from typing import Any

from lark_agent.config import AppConfig
from lark_agent.llm_client import LLMClient
from lark_agent.project import ProjectStore
from lark_agent.router import MessageRouter
from lark_agent.tools import BuiltinTools
from lark_agent.transport.base import IncomingMessage, MessageSender


MAX_TOOL_ITERATIONS = 5


class BotApp:
    def __init__(
        self,
        config: AppConfig,
        *,
        sender: MessageSender,
        llm_client: LLMClient,
        router: MessageRouter | None = None,
        project_store: ProjectStore | None = None,
    ) -> None:
        self.config = config
        self.sender = sender
        self.llm_client = llm_client
        self.router = router or MessageRouter(config.lark.bot_id)
        self.project_store = project_store or ProjectStore(
            config.data_dir,
            max_messages=config.conversation.max_messages,
        )

    async def handle_message(self, message: IncomingMessage) -> str | None:
        if not self.router.should_respond(message):
            return None
        if self.router.is_command(message):
            return None

        project = self.project_store.get_project(message.chat_id)
        thread_id = self.router.get_thread_id(message)
        conversation = project.get_conversation(thread_id)
        skills_registry = project.get_skills_registry()
        builtin_tools = BuiltinTools(skills_registry)
        tools = builtin_tools.get_tools_for_llm()

        conversation.append(message.to_openai_message())
        system_prompt = _build_system_prompt(
            project.get_agents_md(),
            skills_registry.get_system_prompt_fragment(),
        )
        reply = ""

        for _ in range(MAX_TOOL_ITERATIONS):
            assistant_message = await self.llm_client.complete_message(
                system_prompt,
                conversation.get_context(),
                tools=tools,
            )
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                reply = _message_text(assistant_message)
                conversation.append({"role": "assistant", "content": reply})
                break

            conversation.append(assistant_message)
            for tool_call in tool_calls:
                result = await builtin_tools.call_tool(
                    _tool_call_name(tool_call),
                    _tool_call_arguments(tool_call),
                )
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tool_call_id(tool_call),
                        "content": result,
                    }
                )
        else:
            reply = "Error: tool loop exceeded maximum iterations"
            conversation.append({"role": "assistant", "content": reply})

        await self.sender.send_text(
            message.chat_id,
            reply,
            root_id=message.root_id,
            reply_to_message_id=message.message_id,
        )

        if message.chat_type == "group" and message.root_id:
            self.router.mark_thread_activated(message.chat_id, message.root_id)

        return reply


def _build_system_prompt(agents_md: str, skills_fragment: str) -> str:
    parts = [part.strip() for part in (agents_md, skills_fragment) if part.strip()]
    return "\n\n".join(parts)


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
