from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, AsyncContextManager, AsyncIterator, Protocol

import yaml


AGENTS_DIR = ".agents"
MCP_CONFIG = "mcp.yaml"
MCP_TOOL_PREFIX = "mcp"
MCP_TOOL_SEPARATOR = "__"
DEFAULT_TOOL_PARAMETERS: dict[str, Any] = {"type": "object", "properties": {}}


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None


@dataclass(frozen=True)
class MCPConfig:
    servers: dict[str, MCPServerConfig]

    @property
    def is_empty(self) -> bool:
        return not self.servers


@dataclass(frozen=True)
class MCPToolRef:
    server_name: str
    tool_name: str


class MCPSession(Protocol):
    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class MCPSessionFactory(Protocol):
    def create(self, server: MCPServerConfig) -> AsyncContextManager[MCPSession]: ...


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

        return _format_tool_result(result)

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


class OfficialMCPSessionFactory:
    @asynccontextmanager
    async def create(self, server: MCPServerConfig) -> AsyncIterator[MCPSession]:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        parameters = StdioServerParameters(
            command=server.command,
            args=list(server.args),
            env=server.env,
            cwd=server.cwd,
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


def load_mcp_config(defaults_dir: Path, project_dir: Path) -> MCPConfig:
    merged: dict[str, MCPServerConfig] = {}
    normalized_server_names: dict[str, str] = {}

    for config_path in (_mcp_config_path(defaults_dir), _mcp_config_path(project_dir)):
        raw_servers = _read_mcp_servers(config_path)
        for server_name, raw_server in raw_servers.items():
            normalized = normalize_tool_name_part(server_name)
            previous = normalized_server_names.get(normalized)
            if previous is not None and previous != server_name:
                raise ValueError(f"MCP server name collision after normalization: {previous!r} and {server_name!r}")

            enabled = _server_enabled(raw_server, server_name)
            if not enabled:
                merged.pop(server_name, None)
                normalized_server_names.pop(normalized, None)
                continue

            server_config = _parse_server_config(server_name, raw_server, config_path)
            merged[server_name] = server_config
            normalized_server_names[normalized] = server_name

    return MCPConfig(merged)


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    return MCP_TOOL_SEPARATOR.join(
        [
            MCP_TOOL_PREFIX,
            normalize_tool_name_part(server_name),
            normalize_tool_name_part(tool_name),
        ]
    )


def normalize_tool_name_part(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise ValueError(f"MCP name part normalizes to an empty value: {value!r}")
    return normalized


def _mcp_config_path(root: Path) -> Path:
    return root / AGENTS_DIR / MCP_CONFIG


def _read_mcp_servers(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"MCP config file must contain a mapping: {path}")

    raw_servers = loaded.get("mcpServers")
    if raw_servers is None:
        return {}
    if not isinstance(raw_servers, dict):
        raise ValueError(f"mcpServers must be a mapping: {path}")

    servers: dict[str, dict[str, Any]] = {}
    for server_name, raw_server in raw_servers.items():
        if not isinstance(server_name, str) or not server_name.strip():
            raise ValueError(f"MCP server name must be a non-empty string: {path}")
        if not isinstance(raw_server, dict):
            raise ValueError(f"MCP server {server_name!r} must be a mapping: {path}")
        servers[server_name.strip()] = raw_server
    return servers


def _server_enabled(raw_server: dict[str, Any], server_name: str) -> bool:
    enabled = raw_server.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"MCP server {server_name!r} enabled must be a boolean")
    return enabled


def _parse_server_config(server_name: str, raw_server: dict[str, Any], config_path: Path) -> MCPServerConfig:
    transport = raw_server.get("transport", "stdio")
    if not isinstance(transport, str) or not transport.strip():
        raise ValueError(f"MCP server {server_name!r} transport must be a non-empty string")
    if transport != "stdio":
        raise ValueError(f"MCP server {server_name!r} uses unsupported transport {transport!r}")

    command = raw_server.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"MCP server {server_name!r} command must be a non-empty string")

    args = raw_server.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError(f"MCP server {server_name!r} args must be a list of strings")

    env = raw_server.get("env")
    parsed_env = _parse_env(server_name, env)

    cwd = raw_server.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError(f"MCP server {server_name!r} cwd must be a string")
    resolved_cwd = _resolve_cwd(config_path, cwd) if cwd else None

    return MCPServerConfig(
        name=server_name,
        transport=transport,
        command=command.strip(),
        args=tuple(args),
        env=parsed_env,
        cwd=resolved_cwd,
    )


def _parse_env(server_name: str, env: Any) -> dict[str, str] | None:
    if env is None:
        return None
    if not isinstance(env, dict):
        raise ValueError(f"MCP server {server_name!r} env must be a mapping")

    parsed: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"MCP server {server_name!r} env keys must be non-empty strings")
        if not isinstance(value, str):
            raise ValueError(f"MCP server {server_name!r} env values must be strings")
        parsed[key] = _interpolate_env_value(value)
    return parsed


def _interpolate_env_value(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"Environment variable {name!r} is required by MCP config")
        return os.environ[name]

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)


def _resolve_cwd(config_path: Path, cwd: str) -> str:
    cwd_path = Path(cwd)
    if cwd_path.is_absolute():
        return str(cwd_path)
    return str((config_path.parent / cwd_path).resolve())


def _validate_normalized_server_names(servers: dict[str, MCPServerConfig]) -> None:
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


def _format_tool_result(result: Any) -> str:
    is_error = bool(_tool_result_field(result, "isError", False))
    parts: list[str] = []

    content = _tool_result_field(result, "content", [])
    if isinstance(content, list):
        for item in content:
            parts.append(_format_content_part(item))

    structured_content = _tool_result_field(result, "structuredContent", None)
    if structured_content is not None:
        parts.append(json.dumps(structured_content, ensure_ascii=False, sort_keys=True))

    text = "\n".join(part for part in parts if part)
    if not text:
        text = ""
    return f"Error: {text}" if is_error and not text.startswith("Error:") else text


def _tool_result_field(result: Any, field: str, default: Any) -> Any:
    if isinstance(result, dict):
        return result.get(field, default)
    return getattr(result, field, default)


def _format_content_part(item: Any) -> str:
    item_type = _tool_result_field(item, "type", None)
    if item_type == "text":
        text = _tool_result_field(item, "text", "")
        return text if isinstance(text, str) else str(text)
    if isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    if hasattr(item, "model_dump"):
        return json.dumps(item.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True)
    return str(item)
