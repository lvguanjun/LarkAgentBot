from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, AsyncIterator, Protocol

from lark_agent.mcp.config import MCPServerConfig


class MCPSession(Protocol):
    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class MCPSessionFactory(Protocol):
    def create(self, server: MCPServerConfig) -> AsyncContextManager[MCPSession]: ...


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
