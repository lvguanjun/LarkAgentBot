from pathlib import Path

import pytest
from pydantic import ValidationError

from lark_agent.config import load_config


CONFIG_ENV_KEYS = (
    "LARK_AGENT_DATA_DIR",
    "LARK_AGENT_LARK__APP_ID",
    "LARK_AGENT_LARK__APP_SECRET",
    "LARK_AGENT_LARK__BOT_ID",
    "LARK_AGENT_LLM__BASE_URL",
    "LARK_AGENT_LLM__API_KEY",
    "LARK_AGENT_LLM__MODEL",
    "LARK_AGENT_CONVERSATION__MAX_MESSAGES",
)


@pytest.fixture(autouse=True)
def isolated_config_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_config_uses_defaults_from_current_working_directory(tmp_path: Path) -> None:
    config = load_config()

    assert config.data_dir == (tmp_path / "data").resolve()
    assert config.lark.app_id == ""
    assert config.lark.app_secret == ""
    assert config.lark.bot_id == ""
    assert config.llm.base_url == ""
    assert config.llm.api_key == ""
    assert config.llm.model == "gpt-4.1-mini"
    assert config.conversation.max_messages == 40


def test_load_config_from_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "LARK_AGENT_DATA_DIR=runtime-data",
                "LARK_AGENT_LARK__APP_ID=app",
                "LARK_AGENT_LARK__APP_SECRET=secret",
                "LARK_AGENT_LARK__BOT_ID=bot",
                "LARK_AGENT_LLM__BASE_URL=https://example.test/v1",
                "LARK_AGENT_LLM__API_KEY=key",
                "LARK_AGENT_LLM__MODEL=custom-model",
                "LARK_AGENT_CONVERSATION__MAX_MESSAGES=12",
            )
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.data_dir == (tmp_path / "runtime-data").resolve()
    assert config.lark.app_id == "app"
    assert config.lark.app_secret == "secret"
    assert config.lark.bot_id == "bot"
    assert config.llm.base_url == "https://example.test/v1"
    assert config.llm.api_key == "key"
    assert config.llm.model == "custom-model"
    assert config.conversation.max_messages == 12


def test_real_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "LARK_AGENT_LARK__APP_ID=dotenv-app",
                "LARK_AGENT_LLM__API_KEY=dotenv-key",
                "LARK_AGENT_CONVERSATION__MAX_MESSAGES=12",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LARK_AGENT_LARK__APP_ID", "env-app")
    monkeypatch.setenv("LARK_AGENT_LLM__API_KEY", "env-key")
    monkeypatch.setenv("LARK_AGENT_CONVERSATION__MAX_MESSAGES", "15")

    config = load_config()

    assert config.lark.app_id == "env-app"
    assert config.llm.api_key == "env-key"
    assert config.conversation.max_messages == 15


def test_explicit_data_dir_overrides_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LARK_AGENT_DATA_DIR", "env-data")
    override_dir = tmp_path / "override-data"

    config = load_config(data_dir=override_dir)

    assert config.data_dir == override_dir


def test_nested_env_names_preserve_field_underscores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LARK_AGENT_LLM__API_KEY", "key")
    monkeypatch.setenv("LARK_AGENT_LARK__APP_ID", "app")
    monkeypatch.setenv("LARK_AGENT_CONVERSATION__MAX_MESSAGES", "9")

    config = load_config()

    assert config.llm.api_key == "key"
    assert config.lark.app_id == "app"
    assert config.conversation.max_messages == 9


def test_invalid_max_messages_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LARK_AGENT_CONVERSATION__MAX_MESSAGES", "not-an-int")

    with pytest.raises(ValidationError):
        load_config()


def test_empty_data_dir_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LARK_AGENT_DATA_DIR", "")

    with pytest.raises(ValidationError, match="data_dir"):
        load_config()
