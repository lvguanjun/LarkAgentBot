from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class LarkConfig:
    app_id: str = ""
    app_secret: str = ""
    bot_id: str = ""


@dataclass(frozen=True)
class LLMConfig:
    model: str = "gpt-4.1-mini"
    api_key: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class ConversationConfig:
    max_messages: int = 40


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    lark: LarkConfig
    llm: LLMConfig
    conversation: ConversationConfig


def load_config(path: str | Path = "config.yaml", *, data_dir: str | Path | None = None) -> AppConfig:
    config_path = Path(path)
    raw = _read_yaml(config_path)
    base_dir = config_path.parent if config_path.parent != Path("") else Path.cwd()

    configured_data_dir = Path(data_dir) if data_dir is not None else Path(raw.get("data_dir", "data"))
    if not configured_data_dir.is_absolute():
        configured_data_dir = (base_dir / configured_data_dir).resolve()

    lark_raw = _mapping(raw.get("lark"))
    llm_raw = _mapping(raw.get("llm"))
    conversation_raw = _mapping(raw.get("conversation"))

    return AppConfig(
        data_dir=configured_data_dir,
        lark=LarkConfig(
            app_id=str(lark_raw.get("app_id", "")),
            app_secret=str(lark_raw.get("app_secret", "")),
            bot_id=str(lark_raw.get("bot_id", "")),
        ),
        llm=LLMConfig(
            model=str(llm_raw.get("model", "gpt-4.1-mini")),
            api_key=str(llm_raw.get("api_key", "")),
            base_url=str(llm_raw.get("base_url", "")),
        ),
        conversation=ConversationConfig(
            max_messages=int(conversation_raw.get("max_messages", 40)),
        ),
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return loaded


def _mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Config section must be a mapping")
    return value
