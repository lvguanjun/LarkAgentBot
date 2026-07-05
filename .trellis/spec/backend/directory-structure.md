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
- Feishu/Lark receiving events normalize known message types to
  SDK-independent `IncomingMessage.content` parts in `transport/base.py`.
  `text`, `post`, `image`, `file`, `folder`, `audio`, `media`, `sticker`,
  `interactive`, `hongbao`, calendar cards, share cards, system messages,
  locations, video chats, todos, votes, and merge-forward messages must produce
  either structured parts or a stable readable `SummaryPart`.
- Unsupported message types and unknown chat types return `None` from the
  adapter; they should not reach `BotApp`. Known message types should not be
  dropped merely because the adapter cannot fetch attachment or business-card
  details.
- Dedupe keys prefer event header `event_id`, then event `uuid`, then
  `message.message_id`. Events without a stable key are acknowledged but not
  handed to `BotApp`.
- Replies use the Feishu/Lark reply API when `reply_to_message_id` is present;
  otherwise create a new message in `chat_id`.
- SDK callbacks must acknowledge quickly and schedule `BotApp.handle_message`
  as background work. Do not block callbacks on LLM or tool execution.
- Background `BotApp.handle_message` failures are logged in task callbacks and
  must not propagate into the SDK event callback.
- Runner event logs that include Feishu `message.content` or normalized message
  projections must use bounded previews. Do not log raw content, normalized
  part JSON, or text projections without a hard length cap.

### Scenario: Feishu/Lark Leading Bot Mention Normalization

#### 1. Scope / Trigger

- Trigger: Feishu/Lark group messages can encode the same visible bot mention
  as text content (`@_user_1 /help`) or rich-text post content (`tag: "at"`).
- Scope: Transport adapters preserve mention structure; router/app code owns
  command and LLM text normalization.

#### 2. Signatures

- `IncomingMessage.content` may contain text, link, mention, image, file,
  media, sticker, emoji, divider, code block, location, and summary parts.
- `MessageRouter.normalized_text_content(message: IncomingMessage) -> str`
  is the canonical text projection for command parsing and LLM user messages.

#### 3. Contracts

- Text messages keep Feishu placeholder tokens such as `@_user_1` in
  `TextPart.text`.
- Post `tag: "at"` nodes normalize to `MentionPart(user_id, user_name)`, not
  plain text.
- Post and interactive card elements preserve readable order. Links, media,
  emoji, dividers, code blocks, controls, and nested notes must normalize to
  shared content parts instead of being silently discarded.
- Attachment parts store only Feishu-provided keys, names, duration, and cover
  image metadata. They do not imply that the bot has downloaded, OCR'd, or
  transcribed the attachment.
- Group messages strip only leading bot-mention prefixes after
  `is_bot_mentioned(message)` is true. Private chats keep raw text content.
- Default `IncomingMessage.text_content()` projection is owned by
  `transport/base.py`; router code may strip leading bot mentions but must not
  reimplement per-message-type Feishu semantics.
- After adapter normalization succeeds, runner logs one `INFO` comparison entry
  with `message_id`, `chat_id`, `message_type`, bounded `raw_content_preview`,
  bounded `normalized_parts_preview`, and bounded `text_projection_preview`.
  The pre-normalization "received event" log must also use a bounded
  `content_preview`.

#### 4. Validation & Error Matrix

- Unknown message type -> adapter returns `None`.
- Invalid content JSON -> adapter returns `None` and logs a warning.
- Known attachment/business message with no downloadable content -> adapter
  returns structured metadata or `SummaryPart` instead of pretending content
  was read.
- Long raw content, normalized parts, or projections -> log only the configured
  preview prefix and append a truncation marker. This protects logs if future
  Feishu payloads include base64, very large card JSON, or long text.
- Group message without a bot mention -> router must not strip leading mention
  placeholders and must not treat `/command` as actionable.

#### 5. Good/Base/Bad Cases

- Good: `@_user_1 /help` in a mentioned group chat normalizes to `/help`.
- Good: `MentionPart("@_user_1", "Bot") + ImagePart + TextPart("这张图说了啥")`
  normalizes to `[用户发送了一张图片]这张图说了啥`.
- Good: a Feishu `file` message becomes `FilePart(file_key, file_name)` and
  projects to a readable placeholder containing those metadata fields.
- Good: an interactive card button or selector becomes a `SummaryPart` in card
  order, while card text, links, and images use their structured parts.
- Base: `/help` in a private chat remains `/help`.
- Bad: Converting post `at` nodes to `TextPart("Bot")` prevents command and LLM
  normalization from reliably removing the leading mention.
- Bad: Returning `None` for known `audio`, `media`, `file`, calendar, vote, or
  location messages makes real conversations disappear at the adapter boundary.
- Bad: Logging `message.content` directly can flood logs with large payloads and
  makes normalized comparison logging unsafe to enable at `INFO`.

#### 6. Tests Required

- Router tests must cover command detection with a leading `@_user_N` text
  placeholder.
- Adapter tests must cover post `tag: "at"` conversion to `MentionPart` plus
  representative post tags, attachments, interactive cards, and business
  summary message types.
- App tests must prove normalized group text, including image alt text, is what
  reaches the LLM history.
- Runner tests must prove raw event content and normalized comparison logs are
  emitted with bounded previews and truncation markers for oversized content.

#### 7. Wrong vs Correct

Wrong:

```python
# Loses mention structure and leaves "Bot /help" or "Bot question" in core text.
parts.append(TextPart(node["user_name"]))
```

Correct:

```python
parts.append(MentionPart(user_id=node["user_id"], user_name=node["user_name"]))
text = router.normalized_text_content(message)
```

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
