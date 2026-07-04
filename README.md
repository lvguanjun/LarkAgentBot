# Lark Agent

Lark Agent is a Python package for a Feishu/Lark chat bot core. It maps each
chat to a project directory, keeps each thread as an independent conversation,
and prepares the core boundaries needed for project-scoped AI conversations.

The current implementation focuses on the local core:

- typed YAML configuration loading from `config.yaml`
- transport-independent message dataclasses and sender protocol
- group, private chat, mention, command, and activated-thread routing rules
- per-chat project directories with `AGENTS.md` fallback loading
- JSONL conversation history persistence and context windowing
- injectable OpenAI-compatible LLM client for local tests and future API use
- `BotApp` orchestration with fake-client test coverage

Live Feishu WebSocket integration, Skills, MCP tools, and management commands
are planned but not part of the current core slice.

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
│   └── AGENTS.md
└── groups/
    └── <chat_id>/
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
