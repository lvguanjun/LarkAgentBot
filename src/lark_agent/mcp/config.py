from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lark_agent.mcp.naming import normalize_tool_name_part

AGENTS_DIR = ".agents"
MCP_CONFIG = "mcp.yaml"


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


def load_mcp_config(defaults_dir: Path, project_dir: Path) -> MCPConfig:
    merged: dict[str, MCPServerConfig] = {}
    normalized_server_names: dict[str, str] = {}

    for config_path in (_mcp_config_path(defaults_dir), _mcp_config_path(project_dir)):
        raw_servers = _read_mcp_servers(config_path)
        for server_name, raw_server in raw_servers.items():
            normalized = normalize_tool_name_part(server_name)
            previous = normalized_server_names.get(normalized)
            if previous is not None and previous != server_name:
                raise ValueError(
                    "MCP server name collision after normalization: "
                    f"{previous!r} and {server_name!r}"
                )

            enabled = _server_enabled(raw_server, server_name)
            if not enabled:
                merged.pop(server_name, None)
                normalized_server_names.pop(normalized, None)
                continue

            server_config = _parse_server_config(server_name, raw_server, config_path)
            merged[server_name] = server_config
            normalized_server_names[normalized] = server_name

    return MCPConfig(merged)


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


def _parse_server_config(
    server_name: str, raw_server: dict[str, Any], config_path: Path
) -> MCPServerConfig:
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
