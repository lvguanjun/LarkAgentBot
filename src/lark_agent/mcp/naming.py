from __future__ import annotations

import re


MCP_TOOL_PREFIX = "mcp"
MCP_TOOL_SEPARATOR = "__"


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
