from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LarkConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_id: str = ""
    app_secret: str = ""
    bot_id: str = ""


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str = "gpt-4.1-mini"
    api_key: str = ""
    base_url: str = ""


class ConversationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_messages: int = 40


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_dir: Path = Path("data")
    lark: LarkConfig = Field(default_factory=LarkConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _validate_data_dir(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("data_dir must not be empty")
        return value


class _AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LARK_AGENT_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    data_dir: Path = Path("data")
    lark: LarkConfig = Field(default_factory=LarkConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _validate_data_dir(cls, value: object) -> object:
        return AppConfig._validate_data_dir(value)


def load_config(*, data_dir: str | Path | None = None) -> AppConfig:
    settings = _AppSettings()
    configured_data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    return AppConfig(
        data_dir=_resolve_data_dir(configured_data_dir),
        lark=settings.lark,
        llm=settings.llm,
        conversation=settings.conversation,
    )


def _resolve_data_dir(path: str | Path) -> Path:
    data_dir = Path(path)
    if data_dir.is_absolute():
        return data_dir
    return (Path.cwd() / data_dir).resolve()
