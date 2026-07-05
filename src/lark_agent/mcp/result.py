from __future__ import annotations

import json
from typing import Any


def format_tool_result(result: Any) -> str:
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
