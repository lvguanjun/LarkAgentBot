from pathlib import Path

from lark_agent.skills import SkillsRegistry
from lark_agent.tools import BuiltinTools


def skills_root(project_root: Path) -> Path:
    return project_root / ".agents" / "skills"


def write_skill(
    root: Path, dirname: str, *, name: str, description: str, body: str = "body"
) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_discovers_default_skills_from_frontmatter(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    write_skill(
        skills_root(defaults), "writer", name="writing-helper", description="Helps write docs"
    )

    registry = SkillsRegistry.discover(defaults, tmp_path / "groups" / "chat-1")

    assert registry.errors == []
    assert list(registry.skills) == ["writing-helper"]
    skill = registry.skills["writing-helper"]
    assert skill.description == "Helps write docs"
    assert skill.skill_dir == skills_root(defaults) / "writer"


def test_group_skills_override_defaults_by_frontmatter_name(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    project = tmp_path / "groups" / "chat-1"
    write_skill(
        skills_root(defaults), "default-writer", name="writer", description="Default writer"
    )
    write_skill(
        skills_root(defaults), "default-reviewer", name="reviewer", description="Default reviewer"
    )
    override_dir = write_skill(
        skills_root(project), "custom-writer", name="writer", description="Group writer"
    )

    registry = SkillsRegistry.discover(defaults, project)

    assert sorted(registry.skills) == ["reviewer", "writer"]
    assert registry.skills["writer"].description == "Group writer"
    assert registry.skills["writer"].skill_dir == override_dir
    assert registry.skills["reviewer"].description == "Default reviewer"


def test_invalid_skill_metadata_is_reported_and_skipped(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    invalid_dir = skills_root(defaults) / "invalid"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "SKILL.md").write_text("---\nname: broken\n---\n\n# Broken\n", encoding="utf-8")

    registry = SkillsRegistry.discover(defaults, tmp_path / "groups" / "chat-1")

    assert registry.skills == {}
    assert len(registry.errors) == 1
    assert registry.errors[0].path == invalid_dir / "SKILL.md"
    assert "description" in registry.errors[0].reason


def test_system_prompt_fragment_lists_only_tier_one_metadata(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    write_skill(
        skills_root(defaults),
        "writer",
        name="writer",
        description="Writes docs",
        body="SECRET FULL BODY",
    )

    fragment = SkillsRegistry.discover(
        defaults, tmp_path / "groups" / "chat-1"
    ).get_system_prompt_fragment()

    assert "- writer: Writes docs" in fragment
    assert "Use read_skill(name)" in fragment
    assert "SECRET FULL BODY" not in fragment


def test_direct_skills_directories_are_not_discovered(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    project = tmp_path / "groups" / "chat-1"
    write_skill(defaults / "skills", "default-writer", name="writer", description="Default writer")
    write_skill(project / "skills", "group-reviewer", name="reviewer", description="Group reviewer")

    registry = SkillsRegistry.discover(defaults, project)

    assert registry.skills == {}
    assert registry.errors == []


async def test_builtin_tool_reads_skill_and_reference_file(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    skill_dir = write_skill(
        skills_root(defaults), "writer", name="writer", description="Writes docs"
    )
    references = skill_dir / "references"
    references.mkdir()
    (references / "style.md").write_text("# Style\n\nBe concise.\n", encoding="utf-8")
    tools = BuiltinTools(SkillsRegistry.discover(defaults, tmp_path / "groups" / "chat-1"))

    skill_text = await tools.call_tool("read_skill", {"name": "writer"})
    reference_text = await tools.call_tool(
        "read_skill", {"name": "writer", "file": "references/style.md"}
    )

    assert "# writer" in skill_text
    assert "Be concise." in reference_text


async def test_read_skill_rejects_unsafe_reference_paths(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    skill_dir = write_skill(
        skills_root(defaults), "writer", name="writer", description="Writes docs"
    )
    references = skill_dir / "references"
    references.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (references / "escape.md").symlink_to(outside)
    tools = BuiltinTools(SkillsRegistry.discover(defaults, tmp_path / "groups" / "chat-1"))

    assert "Error:" in await tools.call_tool(
        "read_skill", {"name": "writer", "file": "/tmp/secret.md"}
    )
    assert "Error:" in await tools.call_tool(
        "read_skill", {"name": "writer", "file": "references/../SKILL.md"}
    )
    assert "Error:" in await tools.call_tool("read_skill", {"name": "writer", "file": "SKILL.md"})
    assert "Error:" in await tools.call_tool(
        "read_skill", {"name": "writer", "file": "references/escape.md"}
    )
