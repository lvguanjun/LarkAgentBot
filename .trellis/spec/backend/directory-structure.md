# Directory Structure

> Backend module ownership and implementation boundaries for this project.

---

## Overview

The backend is a Python package under `src/lark_agent/`. Keep transport
adapters at the edge and core conversation behavior in small modules that can
be tested without live Feishu/Lark, OpenAI, Skills, or MCP services.

This file is a development contract, not an operator guide. User-facing setup,
environment variable examples, and live bot runbooks belong in `README.md`.

---

## Directory Layout

```text
src/
`-- lark_agent/
    |-- app.py              # Application orchestration and LLM/tool loop
    |-- config.py           # Typed environment/.env configuration loading
    |-- agents_conf.py      # AGENTS.md fallback loading
    |-- conversation.py     # JSONL history persistence and context windowing
    |-- llm_client.py       # OpenAI-compatible client wrapper
    |-- mcp/                # MCP config, naming, sessions, manager, results
    |-- project.py          # chat_id -> Project and conversation paths
    |-- router.py           # Trigger rules and thread activation state
    `-- transport/
        |-- base.py         # Internal transport dataclasses/protocols
        `-- lark/           # Feishu/Lark SDK adapter, sender, runner, dedupe
```

---

## Module Ownership

- `transport/base.py` owns SDK-independent message and sender contracts.
- `transport/lark/` owns all `lark-oapi` imports, event conversion, sending,
  bot identity resolution, WebSocket runner behavior, and dedupe integration.
- `config.py` owns application settings decoding from environment variables
  and the current-working-directory `.env`.
- `conversation.py` owns history JSONL decoding, grouping, persistence, and
  context windowing.
- `project.py` owns runtime filesystem path layout for defaults, groups,
  AGENTS.md, Skills, MCP config, and conversations.
- `mcp/` owns MCP configuration, tool naming, session lifecycle, discovery,
  invocation, and result formatting.
- `app.py` coordinates project lookup, routing, prompt assembly, LLM calls,
  built-in tools, MCP tools, persistence, and sender replies.

When adding cross-layer behavior, put the decoding/normalization in one owner
module and make consumers call that owner instead of re-parsing raw payloads.

---

## Dependency Boundaries

- Core modules must not import external transport SDKs. Tests should be able to
  exercise core behavior with `IncomingMessage`, `MessageSender`, fake LLM
  clients, and fake MCP/tool implementations.
- External clients must be constructor-injected where practical so tests do not
  need credentials, network access, or live Feishu/Lark/OpenAI/MCP services.
- Core modules should import MCP through the public `lark_agent.mcp` package
  boundary unless they need an internal helper owned by that package.
- Do not add a second application configuration path such as YAML config or a
  `--config` option. Environment variables and `.env` are the application
  configuration boundary.

---

## Runtime Path Contracts

- Runtime group data lives under `data/groups/<chat_id>/`.
- Default project resources live under `data/defaults/`.
- The runtime `data/` directory is local state and must stay ignored by Git.
  Do not commit real group conversations, local defaults, group config, or MCP
  connection details from this path.
- Committed bootstrap defaults live under `templates/defaults/`, mirroring the
  runtime `data/defaults/` layout.
- Agent assets live under `.agents/` below the default or group root:
  `data/defaults/.agents/skills/`,
  `data/defaults/.agents/mcp.yaml`,
  `data/groups/<chat_id>/.agents/skills/`, and
  `data/groups/<chat_id>/.agents/mcp.yaml`.
- `AGENTS.md` stays at the default or group root.
- Conversation history must use
  `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`.

---

## Configuration Contract

- Settings use `pydantic-settings` with `env_prefix="LARK_AGENT_"`,
  `env_file=".env"`, and `env_nested_delimiter="__"`.
- Source priority is: explicit `load_config(data_dir=...)`, real process
  environment variables, current-working-directory `.env`, then code defaults.
- Relative `data_dir` values resolve against the current working directory.
- Public app settings are `data_dir`, `lark.app_id`, `lark.app_secret`,
  `llm.api_key`, `llm.base_url`, `llm.model`, and
  `conversation.max_messages`.
- `lark.bot_id` is runtime-derived state. Live startup must resolve it from the
  Feishu/Lark bot info API and inject it into the runtime `AppConfig`; do not
  require users to maintain a bot ID environment variable.

Tests that modify configuration must cover defaults, `.env`, real environment
overrides, explicit `data_dir`, nested `__` field names, invalid integer values,
empty data directories, and runner startup without a configured bot ID.

---

## Feishu/Lark Transport Contract

- Bot info resolution happens after app credential validation and before
  constructing `BotApp`.
- Bot info requests use tenant access tokens and must require a successful
  response with non-empty `bot.open_id`.
- Feishu/Lark text, post, and image events normalize to `IncomingMessage`
  content using `TextPart` and `ImagePart`.
- Unsupported message types and unknown chat types return `None` from the
  adapter; they should not reach `BotApp`.
- Dedupe keys prefer event header `event_id`, then event `uuid`, then
  `message.message_id`. Events without a stable key are acknowledged but not
  handed to `BotApp`.
- Replies use the Feishu/Lark reply API when `reply_to_message_id` is present;
  otherwise create a new message in `chat_id`.
- SDK callbacks must acknowledge quickly and schedule `BotApp.handle_message`
  as background work. Do not block callbacks on LLM or tool execution.
- Background `BotApp.handle_message` failures are logged in task callbacks and
  must not propagate into the SDK event callback.

Tests that modify live transport must cover pure event conversion, sender
request fields, ack-first scheduling, TTL dedupe, missing-key skip, background
error logging, event-handler registration, config validation, and bot identity
injection with fake Lark clients.

---

## Examples

- `src/lark_agent/transport/base.py`: stable boundary types without SDK imports.
- `src/lark_agent/transport/lark/`: Feishu/Lark SDK-specific event adapters,
  senders, runners, bot info, and dedupe cache.
- `src/lark_agent/mcp/`: MCP config loading, tool naming, session factory,
  manager lifecycle, and tool result formatting.
- `src/lark_agent/conversation.py`: one owner for JSONL persistence, decoding,
  and context windowing.
