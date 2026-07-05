from __future__ import annotations

from lark_agent.config import AppConfig
from lark_agent.mcp import MCPConfig
from lark_agent.project import Project
from lark_agent.skills import SkillsRegistry
from lark_agent.transport.base import IncomingMessage


class ManagementCommandHandler:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def handle(
        self,
        message: IncomingMessage,
        project: Project,
        thread_id: str,
        *,
        text: str | None = None,
    ) -> str:
        command, args = _parse_command(text if text is not None else message.text_content())

        if command == "/help":
            return _help_text()
        if command == "/config":
            if args and args[0] == "set":
                return "Config updates are not supported yet. Use /config to view the current safe summary."
            return self._config_text(message, thread_id)
        if command == "/skill":
            if args == ["list"]:
                return _skill_list_text(project.get_skills_registry())
            return "Usage: /skill list"
        if command == "/mcp":
            if args == ["list"]:
                return self._mcp_list_text(project)
            return "Usage: /mcp list"
        if command == "/reset":
            project.get_conversation(thread_id).clear()
            return f"Conversation reset for thread: {thread_id}"

        return f"Unknown command: {command or '<empty>'}\nUse /help to see supported commands."

    def _config_text(self, message: IncomingMessage, thread_id: str) -> str:
        return "\n".join(
            [
                "Config summary:",
                f"- data_dir: {self.config.data_dir}",
                f"- llm.model: {self.config.llm.model}",
                f"- llm.api_key: {_configured(self.config.llm.api_key)}",
                f"- llm.base_url: {_configured(self.config.llm.base_url)}",
                f"- conversation.max_messages: {self.config.conversation.max_messages}",
                f"- lark.app_id: {_configured(self.config.lark.app_id)}",
                f"- lark.app_secret: {_configured(self.config.lark.app_secret)}",
                f"- lark.bot_id: {_configured(self.config.lark.bot_id)}",
                f"- chat_id: {message.chat_id}",
                f"- chat_type: {message.chat_type}",
                f"- thread_id: {thread_id}",
            ]
        )

    def _mcp_list_text(self, project: Project) -> str:
        try:
            mcp_config = project.get_mcp_config()
        except ValueError as exc:
            return f"Error loading MCP config: {exc}"
        return _mcp_config_text(mcp_config)


def _parse_command(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    return parts[0].lower(), [part.lower() for part in parts[1:]]


def _help_text() -> str:
    return "\n".join(
        [
            "Supported commands:",
            "- /help: Show this help message.",
            "- /config: Show a safe runtime configuration summary.",
            "- /skill list: List available skills for this chat.",
            "- /mcp list: List configured MCP servers for this chat.",
            "- /reset: Clear the current conversation history.",
        ]
    )


def _skill_list_text(registry: SkillsRegistry) -> str:
    lines = ["Skills:"]
    if registry.skills:
        for skill in sorted(registry.skills.values(), key=lambda item: item.name):
            lines.append(f"- {skill.name}: {skill.description}")
    else:
        lines.append("- No skills configured.")

    if registry.errors:
        lines.append("")
        lines.append("Skill discovery errors:")
        for error in registry.errors:
            lines.append(f"- {error.path}: {error.reason}")

    return "\n".join(lines)


def _mcp_config_text(mcp_config: MCPConfig) -> str:
    lines = ["MCP servers:"]
    if not mcp_config.servers:
        lines.append("- No MCP servers configured.")
        return "\n".join(lines)

    for server in sorted(mcp_config.servers.values(), key=lambda item: item.name):
        env_keys = sorted((server.env or {}).keys())
        env_text = ", ".join(env_keys) if env_keys else "none"
        cwd_text = "configured" if server.cwd else "not configured"
        lines.append(
            f"- {server.name}: transport={server.transport}, command=configured, "
            f"args={len(server.args)}, env_keys={env_text}, cwd={cwd_text}"
        )
    return "\n".join(lines)


def _configured(value: str) -> str:
    return "configured" if value else "not configured"
