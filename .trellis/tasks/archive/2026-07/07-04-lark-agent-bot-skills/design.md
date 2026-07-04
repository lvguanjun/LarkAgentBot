# Design: Skills 与 read_skill 工具闭环

## Architecture

本子任务在 core 对话链路上增加两个边界：

```text
Project
  ├─ AgentsConf -> AGENTS.md
  ├─ SkillsRegistry -> Tier 1 list + read_skill data source
  └─ Conversation -> OpenAI messages JSONL

BotApp
  ├─ builds system prompt from AGENTS.md + Skills Tier 1 list
  ├─ passes built-in tool schemas to LLMClient
  ├─ executes returned tool_calls through BuiltinTools
  └─ persists assistant(tool_calls), tool results, assistant(final)
```

MCP is deliberately not included, but the tool loop should accept a generic tool executor shape so `MCPManager` can be added later without rewriting `LLMClient`.

## Data Model

### Skill Metadata

```python
@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    skill_dir: Path
```

- `name` and `description` come from YAML frontmatter.
- `skill_dir` is internal only and is never exposed to the LLM.
- Discovery returns a registry keyed by `name`.

### Skill Discovery Order

Discovery order should be deterministic:

1. Load global default skills from `data/defaults/skills`.
2. Load group skills from `data/groups/<chat_id>/skills`.
3. If a group Skill has the same `name` as a default Skill, replace the default entry.
4. Sort system prompt output by Skill name for stable tests.

## Files

- `src/lark_agent/skills.py`
  - `SkillMeta`
  - `SkillsRegistry`
  - frontmatter parsing
  - safe Skill/reference file reading
- `src/lark_agent/tools.py`
  - `BuiltinTools`
  - OpenAI function schema for `read_skill`
  - async `call_tool(name, args)` dispatch
- `src/lark_agent/project.py`
  - add `get_skills_registry()`
- `src/lark_agent/llm_client.py`
  - support tools and tool-capable fake clients
  - return structured assistant messages instead of only text when needed
- `src/lark_agent/app.py`
  - build prompt with AGENTS.md + Skills Tier 1 list
  - run bounded tool loop
  - persist all messages in the chain
- `tests/`
  - add focused tests for Skills discovery, built-in tool safety, and app tool loop

## System Prompt

The prompt builder should keep AGENTS.md first and append a compact Skills section only when at least one Skill exists:

```text
<AGENTS.md content>

Available skills:
- skill-name: short description

Use read_skill(name) to load full instructions when a skill is relevant.
Use read_skill(name, file="references/...") to read a referenced skill file.
```

This keeps existing AGENTS.md behavior stable and makes Skills discoverable without front-loading full content.

## Tool Loop

`LLMClient` should expose a method that can return an assistant message in OpenAI message shape:

```python
async def complete_message(
    self,
    system_prompt: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ...
```

`complete()` can remain as a text convenience wrapper for existing tests or compatibility.

`BotApp` owns tool execution because tool implementations are project-scoped:

1. Append user message.
2. Build `messages = conversation.get_context()`.
3. Call `LLMClient.complete_message(system_prompt, messages, tools=...)`.
4. If assistant has no `tool_calls`, persist it and send text.
5. If assistant has `tool_calls`, persist assistant message.
6. Execute each supported tool call through `BuiltinTools`.
7. Persist each result as `{role: "tool", tool_call_id, content}`.
8. Repeat until final assistant message or max iterations.

The default max iteration count should be small, such as `5`, to prevent runaway tool loops.

## Safety

`read_skill` path handling must use `Path.resolve()` and verify the resolved path remains inside the expected base directory.

Allowed reads:

- `SKILL.md` for the selected Skill
- files under `references/`

Rejected reads:

- absolute paths
- paths containing `..`
- paths outside `references/`
- symlink escapes outside the Skill directory
- directories

Tool failures should return clear text like `Error: unknown skill 'x'` instead of raising through `BotApp.handle_message()`.

## Compatibility

- Existing `LLMClient.complete()` callers should keep working.
- Existing text-only fake clients should keep working.
- Existing `Conversation.get_context()` tool pairing behavior should be reused, not replaced.
- The OpenAI API path should pass `tools` only when a non-empty list exists.

