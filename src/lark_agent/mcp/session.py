from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from lark_agent.mcp.config import MCPServerConfig


class MCPSession(Protocol):
    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class MCPSessionFactory(Protocol):
    def create(self, server: MCPServerConfig) -> AbstractAsyncContextManager[MCPSession]: ...


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
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            yield session
