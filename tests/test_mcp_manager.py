from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from lark_agent.mcp_manager import (
    MCPConfig,
    MCPManager,
    MCPServerConfig,
    build_mcp_tool_name,
    load_mcp_config,
)
from lark_agent.skills import SkillsRegistry
from lark_agent.tools import BuiltinTools, ToolDispatcher


def mcp_config_path(root: Path) -> Path:
    return root / ".agents" / "mcp.yaml"


def write_mcp_config(root: Path, text: str) -> None:
    path = mcp_config_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")


class FakeSession:
    def __init__(self, tools: list[dict[str, Any]], result: Any = None) -> None:
        self.tools = tools
        self.result = result or {"content": [{"type": "text", "text": "tool result"}]}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def list_tools(self) -> dict[str, Any]:
        return {"tools": self.tools}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments))
        return self.result


class FakeSessionFactory:
    def __init__(self, sessions: dict[str, FakeSession]) -> None:
        self.sessions = sessions
        self.closed: list[str] = []

    @asynccontextmanager
    async def create(self, server: MCPServerConfig) -> AsyncIterator[FakeSession]:
        try:
            yield self.sessions[server.name]
        finally:
            self.closed.append(server.name)


def test_mcp_config_merges_defaults_and_group_with_overrides_and_disabled(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    project = tmp_path / "groups" / "chat-1"
    write_mcp_config(
        defaults,
        """
mcpServers:
  default_db:
    command: python
    args: ["-m", "default_db"]
  shared:
    command: python
    args: ["-m", "default_shared"]
  disabled_by_group:
    command: python
    args: ["-m", "disabled"]
""",
    )
    write_mcp_config(
        project,
        """
mcpServers:
  shared:
    command: node
    args: ["server.js"]
  group_only:
    command: python
    env:
      TOKEN: literal-token
  disabled_by_group:
    enabled: false
""",
    )

    config = load_mcp_config(defaults, project)

    assert sorted(config.servers) == ["default_db", "group_only", "shared"]
    assert config.servers["default_db"].command == "python"
    assert config.servers["shared"].command == "node"
    assert config.servers["shared"].args == ("server.js",)
    assert config.servers["group_only"].env == {"TOKEN": "literal-token"}


def test_mcp_config_returns_empty_when_missing(tmp_path: Path) -> None:
    config = load_mcp_config(tmp_path / "defaults", tmp_path / "groups" / "chat-1")

    assert config.is_empty
    assert config.servers == {}


def test_mcp_config_rejects_non_stdio_transport(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    write_mcp_config(
        defaults,
        """
mcpServers:
  remote:
    transport: sse
    command: python
""",
    )

    with pytest.raises(ValueError, match="unsupported transport"):
        load_mcp_config(defaults, tmp_path / "groups" / "chat-1")


def test_mcp_config_interpolates_env_and_requires_existing_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = tmp_path / "defaults"
    write_mcp_config(
        defaults,
        """
mcpServers:
  demo:
    command: python
    env:
      TOKEN: "${MCP_TOKEN}"
""",
    )
    monkeypatch.setenv("MCP_TOKEN", "secret")

    config = load_mcp_config(defaults, tmp_path / "groups" / "chat-1")

    assert config.servers["demo"].env == {"TOKEN": "secret"}


def test_mcp_config_rejects_normalized_server_name_collisions(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    write_mcp_config(
        defaults,
        """
mcpServers:
  internal-db:
    command: python
  internal_db:
    command: python
""",
    )

    with pytest.raises(ValueError, match="server name collision"):
        load_mcp_config(defaults, tmp_path / "groups" / "chat-1")


async def test_mcp_tool_schema_converts_to_openai_function_and_calls_original_tool_name() -> None:
    session = FakeSession(
        [
            {
                "name": "query.sql",
                "description": "Run query",
                "inputSchema": {
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                },
            }
        ]
    )
    factory = FakeSessionFactory({"internal-db": session})
    manager = MCPManager(
        MCPConfig({"internal-db": MCPServerConfig(name="internal-db", command="python")}),
        session_factory=factory,
    )

    await manager.start()
    tools = manager.get_tools_for_llm()
    result = await manager.call_tool("mcp__internal_db__query_sql", {"sql": "select 1"})
    await manager.shutdown()

    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "mcp__internal_db__query_sql",
                "description": "Run query",
                "parameters": {
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                },
            },
        }
    ]
    assert result == "tool result"
    assert session.calls == [("query.sql", {"sql": "select 1"})]
    assert factory.closed == ["internal-db"]


async def test_mcp_tool_name_collision_is_rejected() -> None:
    session = FakeSession(
        [
            {"name": "query-sql", "inputSchema": {"type": "object"}},
            {"name": "query_sql", "inputSchema": {"type": "object"}},
        ]
    )
    factory = FakeSessionFactory({"db": session})
    manager = MCPManager(MCPConfig({"db": MCPServerConfig(name="db", command="python")}), session_factory=factory)

    with pytest.raises(ValueError, match="tool name collision"):
        await manager.start()


async def test_tool_dispatcher_routes_builtin_and_mcp_tools(tmp_path: Path) -> None:
    session = FakeSession([{"name": "lookup", "inputSchema": {"type": "object"}}])
    manager = MCPManager(
        MCPConfig({"search": MCPServerConfig(name="search", command="python")}),
        session_factory=FakeSessionFactory({"search": session}),
    )
    await manager.start()
    dispatcher = ToolDispatcher(BuiltinTools(SkillsRegistry.discover(tmp_path / "defaults", tmp_path / "project")), manager)

    mcp_result = await dispatcher.call_tool(build_mcp_tool_name("search", "lookup"), {"q": "x"})
    unknown_result = await dispatcher.call_tool("unknown", {})
    await manager.shutdown()

    assert mcp_result == "tool result"
    assert "Error: unknown tool" in unknown_result
