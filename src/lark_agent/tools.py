from __future__ import annotations

import inspect
from typing import Any

from lark_agent.skills import SkillsRegistry


class BuiltinTools:
    def __init__(self, skills_registry: SkillsRegistry) -> None:
        self.skills_registry = skills_registry

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        if not self.skills_registry.skills:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_skill",
                    "description": (
                        "Read a skill's full instructions or one of its reference files. "
                        "Call with just the name for SKILL.md, or include file=\"references/...\"."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Skill name from the available skills list.",
                            },
                            "file": {
                                "type": "string",
                                "description": "Optional reference path under references/, such as references/api.md.",
                            },
                        },
                        "required": ["name"],
                    },
                },
            }
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        if name != "read_skill":
            return f"Error: unknown built-in tool {name!r}"

        skill_name = args.get("name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            return "Error: read_skill requires a non-empty string name"

        file = args.get("file")
        if file is not None and not isinstance(file, str):
            return "Error: read_skill file must be a string when provided"

        result = self.skills_registry.read_skill(skill_name, file)
        if inspect.isawaitable(result):
            result = await result
        return str(result)
