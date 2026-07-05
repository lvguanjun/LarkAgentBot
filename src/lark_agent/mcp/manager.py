from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncContextManager

from lark_agent.mcp.config import MCPConfig
from lark_agent.mcp.naming import build_mcp_tool_name, normalize_tool_name_part
from lark_agent.mcp.result import format_tool_result
from lark_agent.mcp.session import MCPSession, MCPSessionFactory, OfficialMCPSessionFactory


DEFAULT_TOOL_PARAMETERS: dict[str, Any] = {"type": "object", "properties": {}}


@dataclass(frozen=True)
class MCPToolRef:
    server_name: str
    tool_name: str


class MCPManager:
    def __init__(
        self,
        config: MCPConfig,
        *,
        session_factory: MCPSessionFactory | None = None,
    ) -> None:
        self.config = config
        self.session_factory = session_factory or OfficialMCPSessionFactory()
        self._session_contexts: list[AsyncContextManager[MCPSession]] = []
        self._sessions: dict[str, MCPSession] = {}
        self._tools: list[dict[str, Any]] = []
        self._tool_index: dict[str, MCPToolRef] = {}
        self._started = False
        _validate_normalized_server_names(config.servers)

    async def start(self) -> None:
        if self._started:
            return

        self._tools = []
        self._tool_index = {}
        try:
            for server in self.config.servers.values():
                session_context = self.session_factory.create(server)
                session = await session_context.__aenter__()
                self._session_contexts.append(session_context)
                self._sessions[server.name] = session

                list_result = await session.list_tools()
                for tool in _list_tools(list_result):
                    self._register_tool(server.name, tool)
        except Exception:
            await self.shutdown()
            raise

        self._started = True

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        return list(self._tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        tool_ref = self._tool_index.get(name)
        if tool_ref is None:
            return f"Error: unknown MCP tool {name!r}"

        session = self._sessions.get(tool_ref.server_name)
        if session is None:
            return f"Error: MCP server {tool_ref.server_name!r} is not connected"

        try:
            result = await session.call_tool(tool_ref.tool_name, args)
        except Exception as exc:  # noqa: BLE001 - tool errors must be returned to the model.
            return f"Error: MCP tool {name!r} failed: {exc}"

        return format_tool_result(result)

    async def shutdown(self) -> None:
        while self._session_contexts:
            session_context = self._session_contexts.pop()
            try:
                await session_context.__aexit__(None, None, None)
            except Exception:
                pass
        self._sessions.clear()
        self._tools = []
        self._tool_index = {}
        self._started = False

    def _register_tool(self, server_name: str, tool: Any) -> None:
        raw_tool_name = _tool_field(tool, "name")
        if not isinstance(raw_tool_name, str) or not raw_tool_name.strip():
            raise ValueError(f"MCP tool from server {server_name!r} has an invalid name")

        exposed_name = build_mcp_tool_name(server_name, raw_tool_name)
        if exposed_name in self._tool_index:
            raise ValueError(f"MCP tool name collision after normalization: {exposed_name}")

        description = _tool_field(tool, "description")
        input_schema = _tool_field(tool, "inputSchema")
        parameters = input_schema if isinstance(input_schema, dict) else dict(DEFAULT_TOOL_PARAMETERS)
        self._tool_index[exposed_name] = MCPToolRef(server_name=server_name, tool_name=raw_tool_name)
        self._tools.append(
            {
                "type": "function",
                "function": {
                    "name": exposed_name,
                    "description": (
                        description
                        if isinstance(description, str) and description.strip()
                        else f"MCP tool {server_name}/{raw_tool_name}"
                    ),
                    "parameters": parameters,
                },
            }
        )


def _validate_normalized_server_names(servers: dict[str, Any]) -> None:
    normalized_names: dict[str, str] = {}
    for server_name in servers:
        normalized = normalize_tool_name_part(server_name)
        previous = normalized_names.get(normalized)
        if previous is not None and previous != server_name:
            raise ValueError(f"MCP server name collision after normalization: {previous!r} and {server_name!r}")
        normalized_names[normalized] = server_name


def _list_tools(list_result: Any) -> list[Any]:
    if isinstance(list_result, dict):
        tools = list_result.get("tools", [])
    else:
        tools = getattr(list_result, "tools", [])
    if not isinstance(tools, list):
        raise ValueError("MCP list_tools result must contain a tools list")
    return tools


def _tool_field(tool: Any, field: str) -> Any:
    if isinstance(tool, dict):
        return tool.get(field)
    return getattr(tool, field, None)
