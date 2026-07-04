from __future__ import annotations

from pathlib import Path


class AgentsConf:
    def __init__(self, group_dir: Path, defaults_dir: Path) -> None:
        self.group_dir = group_dir
        self.defaults_dir = defaults_dir

    def load(self) -> str:
        group_agents = self.group_dir / "AGENTS.md"
        if group_agents.exists():
            return group_agents.read_text(encoding="utf-8")

        default_agents = self.defaults_dir / "AGENTS.md"
        if default_agents.exists():
            return default_agents.read_text(encoding="utf-8")

        return ""
