# Skills Subsystem Guidelines

> Development contract for the bot's local Agent Skills subsystem.

---

## Overview

Skills are passive instruction and resource packages. They do not execute code
by themselves; the agent reads Skill instructions and then uses its own native
tools. Permission isolation belongs at the tool layer.

Keep this file focused on implementation constraints for this project. General
explanations of the Agent Skills standard or user-facing authoring guidance
belong in README/reference documentation, not in development spec.

---

## External Standard Assumptions

The project follows the Agent Skills filesystem convention:

```text
<skills-root>/
`-- <skill-dir>/
    |-- SKILL.md
    |-- references/
    |-- scripts/
    `-- assets/
```

Only `SKILL.md` and files under `references/` are currently exposed to the LLM.
`scripts/`, `assets/`, and generic filesystem reads are out of scope for the
MVP.

`SKILL.md` must use YAML frontmatter with non-empty string `name` and
`description`. The frontmatter `name` is the LLM-facing identifier; directory
names are internal filesystem locators.

---

## Module Ownership

Skills-related behavior is owned by:

- `src/lark_agent/skills.py`: discovery, metadata parsing, merging, validation,
  system prompt fragment, and bounded reference reads.
- `src/lark_agent/tools.py`: built-in tool schema and dispatch for `read_skill`.
- `src/lark_agent/project.py`: default and group Skills root resolution.
- `src/lark_agent/app.py`: prompt assembly, tool loop orchestration, persistence,
  and final reply behavior.
- `src/lark_agent/llm_client.py`: OpenAI-compatible request/response shape for
  tool calls.

Do not duplicate Skills metadata parsing or path validation in consumers.

---

## Discovery Contract

- Discover default Skills from `data/defaults/.agents/skills/<dir>/SKILL.md`.
- Discover group Skills from
  `data/groups/<chat_id>/.agents/skills/<dir>/SKILL.md`.
- Do not treat `data/defaults/skills/` or `data/groups/<chat_id>/skills/` as
  fallback locations.
- Missing Skills directories return an empty registry without error.
- Invalid or missing frontmatter skips that Skill and records a `SkillLoadError`.
- Group Skills override default Skills by frontmatter `name`; non-conflicting
  Skills are merged.
- Tier 1 prompt content may include only Skill `name`, `description`, and the
  instruction to call `read_skill`. It must not include full Skill bodies or
  reference file contents.

---

## Built-In Tool Contract

The MVP exposes one safe built-in tool:

```python
SkillsRegistry.read_skill(name: str, file: str | None = None) -> str
BuiltinTools.get_tools_for_llm() -> list[dict[str, Any]]
BuiltinTools.call_tool(name: str, args: dict[str, Any]) -> str
LLMClient.complete_message(
    system_prompt: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]
```

- `read_skill(name)` returns the selected Skill's full `SKILL.md`.
- `read_skill(name, file="references/...")` returns a file under that Skill's
  `references/` directory.
- Unknown Skill names return model-visible `Error:` text.
- Absolute paths, `..`, non-`references/` paths, and symlink escapes return
  model-visible `Error:` text before reading.
- Tool argument errors are ordinary model-visible failures and should not crash
  `BotApp.handle_message()`.
- The tool loop must persist the complete OpenAI message chain:
  `user -> assistant(tool_calls) -> tool -> assistant(final)`.
- If the tool loop exceeds the configured maximum iterations, persist an
  assistant error message and return it.

---

## Forbidden Patterns

- Do not expose generic file reads to the LLM; they can leak config, MCP
  credentials, conversation history, or local runtime data.
- Do not include full Skill bodies in the Tier 1 system prompt.
- Do not use Skill directory names as the public identifier when frontmatter
  provides `name`.
- Do not execute Skill scripts or read Skill assets until the tool permission
  model is explicitly designed and tested.
- Do not crash message handling for ordinary bad tool arguments.

---

## Required Tests

When changing the Skills subsystem, tests must cover:

- frontmatter discovery and invalid metadata reporting
- default/group merge and override behavior
- Tier 1 prompt excluding full Skill bodies and reference content
- `read_skill` reading `SKILL.md` and allowed `references/...` files
- rejection of absolute paths, `..`, non-reference paths, and symlink escapes
- fake LLM tool calls executing through `BuiltinTools`
- complete OpenAI message-chain persistence for tool calls
- max-iteration failure behavior

---

## Examples

Wrong:

```python
# Generic file reads expose config, MCP credentials, or conversation history.
read_file("../../../config.yaml")
```

Correct:

```python
# The LLM names a Skill; the tool resolves it internally and only permits
# SKILL.md or references/ reads.
read_skill("writer", file="references/style.md")
```

MCP tools and Skills remain separate concepts: MCP provides executable external
capabilities, while Skills provide local instructions and bounded read-only
resources.
