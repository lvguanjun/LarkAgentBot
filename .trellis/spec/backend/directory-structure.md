# Directory Structure

> How backend code is organized in this project.

---

## Overview

The backend is a Python package under `src/lark_agent/`. The package keeps
transport adapters at the edge and core conversation behavior in small modules
that can be tested without live Feishu, OpenAI, Skills, or MCP services.

---

## Directory Layout

```
src/
└── lark_agent/
    ├── app.py              # Application orchestration
    ├── config.py           # Typed YAML configuration loading
    ├── agents_conf.py      # AGENTS.md fallback loading
    ├── conversation.py     # JSONL history persistence and context windowing
    ├── llm_client.py       # OpenAI-compatible client wrapper
    ├── mcp/                # MCP config, naming, session, manager, results
    ├── project.py          # chat_id -> Project and conversation paths
    ├── router.py           # Trigger rules and thread activation state
    └── transport/
        ├── base.py         # Internal transport boundary dataclasses/protocols
        └── lark/           # Feishu/Lark SDK adapter, sender, runner, dedupe
```

---

## Module Organization

- Keep external SDK-specific code in adapter modules, not in core logic. For
  example, `lark-oapi` WebSocket code belongs under `transport/lark/`, while
  tests should exercise `IncomingMessage` from `transport/base.py`.
- Keep MCP protocol/client details under `mcp/`. Core modules import the public
  package boundary (`from lark_agent.mcp import ...`) instead of reaching into
  implementation files unless they truly need an internal helper.
- Put one cross-layer contract owner next to the data it owns:
  `conversation.py` owns history JSONL message grouping, `project.py` owns
  filesystem path layout, and `config.py` owns YAML decoding.
- Prefer constructor injection for external clients (`LLMClient`, sender
  protocols) so tests can use fakes without network or credentials.

---

## Naming Conventions

- Use lowercase snake_case module names.
- Runtime group data lives under `data/groups/<chat_id>/`.
- Default project resources live under `data/defaults/`.
- The entire runtime `data/` directory is local state and must be ignored by
  Git. Do not commit real group conversations, local defaults, group config, or
  MCP connection details from this path.
- Committed bootstrap defaults live under `templates/defaults/`, with a layout
  that mirrors the runtime `data/defaults/` directory. Developers copy these
  templates into local `data/defaults/` before running the bot.
- Agent assets live under `.agents/` below the default or group root:
  `data/defaults/.agents/skills/`,
  `data/defaults/.agents/mcp.yaml`,
  `data/groups/<chat_id>/.agents/skills/`, and
  `data/groups/<chat_id>/.agents/mcp.yaml`.
- `AGENTS.md` stays at the default or group root. Conversation history stays
  under `data/groups/<chat_id>/conversations/`.
- Conversation history paths must follow
  `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`.

---

## Examples

- `src/lark_agent/transport/base.py`: stable boundary types without SDK imports.
- `src/lark_agent/transport/lark/`: Feishu/Lark SDK-specific event adapters,
  senders, runners, and dedupe cache.
- `src/lark_agent/mcp/`: MCP config loading, tool naming, session factory,
  manager lifecycle, and tool result formatting.
- `src/lark_agent/conversation.py`: JSONL persistence and windowing owned in one
  module instead of repeated parsing in consumers.

## Scenario: Feishu WebSocket Transport Adapter

### 1. Scope / Trigger

- Trigger: live Feishu/Lark WebSocket integration adds an external SDK boundary
  and converts SDK event payloads into the internal transport contract.
- SDK-specific imports stay in `src/lark_agent/transport/lark/` and
  `src/lark_agent/main.py`; core modules keep depending only on
  `IncomingMessage` and `MessageSender`.

### 2. Signatures

- `LarkMessageEventAdapter.to_incoming_message(event) -> IncomingMessage | None`
- `LarkMessageEventAdapter.dedupe_key(event) -> str | None`
- `LarkMessageSender.send_text(chat_id, text, *, root_id=None, reply_to_message_id=None) -> None`
- `LarkWebSocketBotRunner.handle_event(event) -> None`
- `python -m lark_agent.main --config config.yaml`

### 3. Contracts

- Feishu text/post/image events are normalized to `IncomingMessage.content`
  with `TextPart` and `ImagePart`; unsupported message types return `None`.
- Feishu `chat_type` maps only to internal `"group"` or `"p2p"`; unknown chat
  types return `None`.
- Dedupe keys prefer event header `event_id`, then event `uuid`, then
  `message.message_id`. Events without a stable key are acknowledged but not
  handed to `BotApp`.
- Replies use Feishu reply API when `reply_to_message_id` is present; otherwise
  create API sends to `chat_id`.

### 4. Validation & Error Matrix

- Missing `lark.app_id`, `lark.app_secret`, or `lark.bot_id` at startup ->
  raise `ValueError` before opening WebSocket.
- Invalid message JSON -> log and return `None`.
- Unsupported message/chat type -> return `None`.
- Duplicate dedupe key in TTL window -> return without scheduling a task.
- Feishu send API failure -> raise `LarkSendError` from the sender.
- Background `BotApp.handle_message` failure -> log in task callback; do not
  propagate to the SDK event callback.

### 5. Good/Base/Bad Cases

- Good: `p2.im.message.receive_v1` text event with stable `event_id` schedules
  one background `BotApp.handle_message` call and returns quickly.
- Base: image event becomes `ImagePart(file_key=...)` without downloading the
  image.
- Bad: event without `event_id`, `uuid`, or `message_id` is skipped to avoid
  non-idempotent LLM replies.

### 6. Tests Required

- Pure conversion tests for text, post, image, unsupported type, and unknown
  chat type.
- Sender tests with fake message API asserting reply/create request fields.
- Runner tests asserting ack-first scheduling, TTL dedupe, missing-key skip,
  background error logging, and event-handler registration.
- Main-entry tests should cover config validation only; never start a real
  WebSocket in unit tests.

### 7. Wrong vs Correct

#### Wrong

```python
def on_message(event):
    message = adapter.to_incoming_message(event)
    asyncio.run(app.handle_message(message))
```

This blocks the SDK callback on LLM/tool work and risks Feishu retrying the
event.

#### Correct

```python
def on_message(event):
    key = adapter.dedupe_key(event)
    if key is None or cache.seen_or_mark(key):
        return
    message = adapter.to_incoming_message(event)
    if message is None:
        return
    task = asyncio.get_running_loop().create_task(app.handle_message(message))
    task.add_done_callback(log_background_failure)
```
