from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    skill_dir: Path


@dataclass(frozen=True)
class SkillLoadError:
    path: Path
    reason: str


class SkillsRegistry:
    def __init__(self, skills: dict[str, SkillMeta] | None = None, errors: list[SkillLoadError] | None = None) -> None:
        self.skills = skills or {}
        self.errors = errors or []

    @classmethod
    def discover(cls, defaults_dir: Path, project_dir: Path) -> "SkillsRegistry":
        skills: dict[str, SkillMeta] = {}
        errors: list[SkillLoadError] = []

        for skills_dir in (defaults_dir / "skills", project_dir / "skills"):
            discovered, load_errors = _discover_dir(skills_dir)
            skills.update(discovered)
            errors.extend(load_errors)

        return cls(skills, errors)

    def get_system_prompt_fragment(self) -> str:
        if not self.skills:
            return ""

        lines = ["Available skills:"]
        for skill in sorted(self.skills.values(), key=lambda item: item.name):
            lines.append(f"- {skill.name}: {skill.description}")
        lines.extend(
            [
                "",
                "Use read_skill(name) to load full instructions when a skill is relevant.",
                'Use read_skill(name, file="references/...") to read a referenced skill file.',
            ]
        )
        return "\n".join(lines)

    def read_skill(self, name: str, file: str | None = None) -> str:
        skill = self.skills.get(name)
        if skill is None:
            return f"Error: unknown skill {name!r}"

        if file is None:
            path = skill.skill_dir / "SKILL.md"
            return _read_resolved_file(path, skill.skill_dir)

        if _is_unsafe_reference_path(file):
            return f"Error: invalid reference path {file!r}"

        references_dir = skill.skill_dir / "references"
        path = skill.skill_dir / file
        return _read_resolved_file(path, references_dir)


def _discover_dir(skills_dir: Path) -> tuple[dict[str, SkillMeta], list[SkillLoadError]]:
    if not skills_dir.exists():
        return {}, []
    if not skills_dir.is_dir():
        return {}, [SkillLoadError(skills_dir, "skills path is not a directory")]

    skills: dict[str, SkillMeta] = {}
    errors: list[SkillLoadError] = []
    for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        meta, error = _load_skill_meta(skill_md)
        if error is not None:
            errors.append(error)
            continue
        if meta is not None:
            skills[meta.name] = SkillMeta(
                name=meta.name,
                description=meta.description,
                skill_dir=skill_dir,
            )
    return skills, errors


def _load_skill_meta(path: Path) -> tuple[SkillMeta | None, SkillLoadError | None]:
    if not path.exists():
        return None, SkillLoadError(path, "missing SKILL.md")

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, SkillLoadError(path, "missing YAML frontmatter")

    end = text.find("\n---", 4)
    if end == -1:
        return None, SkillLoadError(path, "unterminated YAML frontmatter")

    try:
        frontmatter = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        return None, SkillLoadError(path, f"invalid YAML frontmatter: {exc}")

    if not isinstance(frontmatter, dict):
        return None, SkillLoadError(path, "frontmatter must be a mapping")

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        return None, SkillLoadError(path, "frontmatter name must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        return None, SkillLoadError(path, "frontmatter description must be a non-empty string")

    return SkillMeta(name=name.strip(), description=description.strip(), skill_dir=path.parent), None


def _is_unsafe_reference_path(file: str) -> bool:
    path = Path(file)
    return path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "references"


def _read_resolved_file(path: Path, allowed_root: Path) -> str:
    try:
        resolved_root = allowed_root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except OSError:
        return f"Error: file not found {path.name!r}"

    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        return f"Error: invalid file path {path.name!r}"
    if not resolved_path.is_file():
        return f"Error: not a file {path.name!r}"

    return resolved_path.read_text(encoding="utf-8")
