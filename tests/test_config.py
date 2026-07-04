from pathlib import Path

from lark_agent.config import load_config


def test_load_config_from_yaml_and_override_data_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
data_dir: runtime-data
lark:
  app_id: app
  app_secret: secret
  bot_id: bot
llm:
  base_url: https://example.test/v1
  api_key: key
  model: custom-model
conversation:
  max_messages: 12
""",
        encoding="utf-8",
    )

    override_dir = tmp_path / "override-data"
    config = load_config(config_path, data_dir=override_dir)

    assert config.data_dir == override_dir
    assert config.lark.app_id == "app"
    assert config.lark.app_secret == "secret"
    assert config.lark.bot_id == "bot"
    assert config.llm.base_url == "https://example.test/v1"
    assert config.llm.api_key == "key"
    assert config.llm.model == "custom-model"
    assert config.conversation.max_messages == 12


def test_load_config_uses_relative_data_dir_from_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("data_dir: data\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.data_dir == (config_path.parent / "data").resolve()
