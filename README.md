# Lark Agent

Lark Agent is a Python package for a Feishu/Lark chat bot core. It maps each
chat to a project directory, keeps each thread as an independent conversation,
and prepares project-scoped AI conversations with AGENTS.md rules, Skills, and
OpenAI-compatible tool calling.

The current implementation is a local, transport-independent bot core:

- typed YAML configuration loading from `config.yaml`
- transport-independent message dataclasses and sender protocol
- group, private chat, mention, command, and activated-thread routing rules
- per-chat project directories with `AGENTS.md` fallback loading
- JSONL conversation history persistence and context windowing
- Skills discovery from `data/defaults/skills/` and
  `data/groups/<chat_id>/skills/`
- Tier 1 Skills list injection into the system prompt
- safe built-in `read_skill(name, file?)` tool for SKILL.md and reference files
- bounded OpenAI-compatible tool loop with complete tool-call persistence
- injectable fake sender and fake LLM clients for local tests

Live Feishu WebSocket integration, MCP tools, management commands, and a
runnable `main.py` entrypoint are still planned.

The next recommended implementation slice is MCP tools: load `mcp.yaml`,
discover MCP tools, convert them to OpenAI-compatible function schemas, and
dispatch MCP tool calls through the existing tool loop.

## Requirements

- Python 3.11+
- `uv` for dependency resolution and test execution

## Setup

Install the package with development dependencies:

```bash
uv sync --extra dev
```

The default configuration lives in `config.yaml`. Runtime data is written under
`data/` by default:

```text
data/
├── defaults/
│   ├── AGENTS.md
│   └── skills/
│       └── <skill_dir>/
│           ├── SKILL.md
│           └── references/
└── groups/
    └── <chat_id>/
        ├── AGENTS.md
        ├── skills/
        │   └── <skill_dir>/
        │       ├── SKILL.md
        │       └── references/
        └── conversations/
            └── <thread_id>/
                └── history.jsonl
```

## Configuration

`config.yaml` supports the current core settings:

```yaml
data_dir: data

lark:
  app_id: ""
  app_secret: ""
  bot_id: ""

llm:
  model: gpt-4.1-mini
  api_key: ""
  base_url: ""

conversation:
  max_messages: 40
```

`data/defaults/AGENTS.md` is used as the default system prompt. A chat-specific
`data/groups/<chat_id>/AGENTS.md` overrides it when present.

## Skills

Skills are read-only instruction packages. Each skill lives in a directory with
a `SKILL.md` file containing YAML frontmatter:

```markdown
---
name: example_skill
description: Use this when the assistant needs example behavior.
---

# Example Skill

Skill instructions go here.
```

Global skills live under `data/defaults/skills/`. Chat-specific skills live
under `data/groups/<chat_id>/skills/` and override global skills with the same
skill name. The model first sees only skill names and descriptions, then can
call `read_skill` to read full instructions or files under `references/`.

## Tests

Run the full test suite:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
```

Compile-check the package:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

Async tests are supported through `pytest-asyncio` with
`asyncio_mode = "auto"` in `pyproject.toml`, so `async def test_...` functions
can run directly.
