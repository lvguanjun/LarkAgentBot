from pathlib import Path

from lark_agent.agents_conf import AgentsConf


def test_group_agents_overrides_default(tmp_path: Path) -> None:
    group_dir = tmp_path / "groups" / "chat"
    defaults_dir = tmp_path / "defaults"
    group_dir.mkdir(parents=True)
    defaults_dir.mkdir()
    (defaults_dir / "AGENTS.md").write_text("default", encoding="utf-8")
    (group_dir / "AGENTS.md").write_text("group", encoding="utf-8")

    assert AgentsConf(group_dir, defaults_dir).load() == "group"


def test_default_agents_fallback(tmp_path: Path) -> None:
    group_dir = tmp_path / "groups" / "chat"
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    (defaults_dir / "AGENTS.md").write_text("default", encoding="utf-8")

    assert AgentsConf(group_dir, defaults_dir).load() == "default"


def test_missing_agents_returns_empty_string(tmp_path: Path) -> None:
    assert AgentsConf(tmp_path / "group", tmp_path / "defaults").load() == ""
