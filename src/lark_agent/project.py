from __future__ import annotations

from pathlib import Path

from lark_agent.agents_conf import AgentsConf
from lark_agent.conversation import Conversation


class ProjectStore:
    def __init__(self, data_dir: Path, *, max_messages: int = 40) -> None:
        self.data_dir = data_dir
        self.groups_dir = data_dir / "groups"
        self.defaults_dir = data_dir / "defaults"
        self.max_messages = max_messages

    def get_project(self, chat_id: str) -> "Project":
        safe_chat_id = _safe_path_name(chat_id, "chat_id")
        return Project(
            chat_id=safe_chat_id,
            path=self.groups_dir / safe_chat_id,
            defaults_dir=self.defaults_dir,
            max_messages=self.max_messages,
        )


class Project:
    def __init__(self, chat_id: str, path: Path, defaults_dir: Path, *, max_messages: int) -> None:
        self.chat_id = chat_id
        self.path = path
        self.defaults_dir = defaults_dir
        self.max_messages = max_messages

    def get_agents_md(self) -> str:
        return AgentsConf(self.path, self.defaults_dir).load()

    def get_conversation(self, thread_id: str) -> Conversation:
        safe_thread_id = _safe_path_name(thread_id, "thread_id")
        return Conversation(
            self.path / "conversations" / safe_thread_id,
            max_messages=self.max_messages,
        )


def _safe_path_name(value: str, field: str) -> str:
    if not value:
        raise ValueError(f"{field} must not be empty")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{field} contains invalid path characters: {value!r}")
    return value
