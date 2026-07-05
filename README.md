# Lark Agent

Lark Agent is a Python package for a Feishu/Lark chat bot core. It maps each
chat to a project directory, keeps each thread as an independent conversation,
and prepares project-scoped AI conversations with AGENTS.md rules, Skills, and
OpenAI-compatible tool calling.

The current implementation includes the transport-independent bot core and a
minimal Feishu WebSocket adapter:

- typed YAML configuration loading from `config.yaml`
- transport-independent message dataclasses and sender protocol
- group, private chat, mention, command, and activated-thread routing rules
- per-chat project directories with `AGENTS.md` fallback loading
- JSONL conversation history persistence and context windowing
- Skills discovery from local `data/defaults/.agents/skills/` and
  `data/groups/<chat_id>/.agents/skills/`
- Tier 1 Skills list injection into the system prompt
- safe built-in `read_skill(name, file?)` tool for SKILL.md and reference files
- MCP config loading from `.agents/mcp.yaml`, MCP tool discovery, and
  OpenAI-compatible function schema conversion
- bounded OpenAI-compatible tool loop with complete built-in/MCP tool-call
  persistence
- Feishu WebSocket message-event conversion for text, post, and image messages
- Feishu text replies through the `MessageSender` boundary
- ack-first WebSocket event handling with in-process TTL deduplication
- `python -m lark_agent.main` as a minimal live bot entrypoint
- injectable fake sender and fake LLM clients for local tests

Management commands are still planned.

The next recommended implementation slice is management commands such as
`/help`, `/config`, `/skill list`, `/mcp list`, and `/reset`.

## Requirements

- Python 3.13+
- `uv` for dependency resolution and test execution

## Setup

Install the package with development dependencies:

```bash
uv sync --extra dev
```

`config.yaml` 是全局配置文件。`data/` 是本地运行时目录，默认被 Git
忽略，不应提交群组消息、本地 defaults、群组配置或 MCP 连接配置。

仓库提供可复制的默认资源模板：

```text
templates/
└── defaults/
    └── AGENTS.md
```

初始化本地默认资源时，将模板复制到运行时目录：

```bash
mkdir -p data
cp -R templates/defaults data/defaults
```

运行时数据默认写入 `data/`：

```text
data/
├── defaults/
│   ├── AGENTS.md
│   └── .agents/
│       ├── skills/
│       │   └── <skill_dir>/
│       │       ├── SKILL.md
│       │       └── references/
│       └── mcp.yaml
└── groups/
    └── <chat_id>/
        ├── AGENTS.md
        ├── .agents/
        │   ├── skills/
        │   │   └── <skill_dir>/
        │   │       ├── SKILL.md
        │   │       └── references/
        │   └── mcp.yaml
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

本地 `data/defaults/AGENTS.md` 会作为默认 system prompt。存在群组级
`data/groups/<chat_id>/AGENTS.md` 时，群组级文件优先生效。

## Run The Live Bot

准备好 `config.yaml`、本地 `data/defaults/` 资源和飞书应用凭证后，可以启动
WebSocket 长连接：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m lark_agent.main
```

`lark.bot_id` 建议配置为机器人在飞书事件 `mentions[].id.open_id` 中出现的
open_id；如果你的租户事件使用 `user_id` 或 `union_id` 匹配，也可以配置为对应
ID。

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

全局 Skills 位于本地 `data/defaults/.agents/skills/`。群组级 Skills 位于
`data/groups/<chat_id>/.agents/skills/`，同名时覆盖全局 Skills。模型会先看到
skill name 和 description，再通过 `read_skill` 读取完整说明或 `references/`
下的文件。

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
