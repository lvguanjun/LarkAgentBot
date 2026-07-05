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
    ├── config.py           # Typed environment/.env configuration loading
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
  filesystem path layout, and `config.py` owns application settings decoding.
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

## Scenario: Application Environment Configuration

### 1. Scope / Trigger

- Trigger: application-level configuration for live bot credentials, LLM
  settings, runtime data directory, and conversation window size.
- `config.py` owns decoding from process environment and `.env` into internal
  typed config objects. Do not add application-level YAML config loaders.

### 2. Signatures

- `load_config(*, data_dir: str | Path | None = None) -> AppConfig`
- `python -m lark_agent.main`
- Internal access shape:
  - `config.data_dir`
  - `config.lark.app_id`
  - `config.lark.app_secret`
  - `config.lark.bot_id` (runtime value; live startup resolves it from Lark
    bot info instead of requiring user-provided environment configuration)
  - `config.llm.api_key`
  - `config.llm.base_url`
  - `config.llm.model`
  - `config.conversation.max_messages`

### 3. Contracts

- Settings use `pydantic-settings` with:
  - `env_prefix="LARK_AGENT_"`
  - `env_file=".env"`
  - `env_nested_delimiter="__"`
- Public environment keys:
  - `LARK_AGENT_DATA_DIR`
  - `LARK_AGENT_LARK__APP_ID`
  - `LARK_AGENT_LARK__APP_SECRET`
  - `LARK_AGENT_LLM__API_KEY`
  - `LARK_AGENT_LLM__BASE_URL`
  - `LARK_AGENT_LLM__MODEL`
  - `LARK_AGENT_CONVERSATION__MAX_MESSAGES`
- Source priority, highest first:
  1. Explicit `load_config(data_dir=...)`
  2. Real process environment variables
  3. Current-working-directory `.env`
  4. Code defaults
- Relative `data_dir` values resolve against the current working directory.

### 4. Validation & Error Matrix

- Empty `LARK_AGENT_DATA_DIR` -> Pydantic validation error.
- Non-integer `LARK_AGENT_CONVERSATION__MAX_MESSAGES` -> Pydantic validation
  error.
- Missing live Feishu credentials at runner startup -> `validate_lark_config`
  raises `ValueError` naming missing `lark.app_id` / `lark.app_secret` fields.
- Missing bot identity at runner startup -> bot info resolution raises before
  opening WebSocket; do not ask users to configure a bot ID environment value.
- Unknown extra values in `.env` -> ignored by application settings.

### 5. Good/Base/Bad Cases

- Good: `LARK_AGENT_LLM__API_KEY=sk-...` maps to `config.llm.api_key`.
- Base: no `.env` and no relevant process environment yields code defaults.
- Bad: reintroducing `config.yaml` or `--config` for application settings
  violates the active-development no-backward-compatibility rule.
- Bad: requiring users to copy `bot.open_id` into `.env` reintroduces stale
  identity configuration and should not be used for live startup.

### 6. Tests Required

- Defaults resolve `data_dir` from the current working directory.
- `.env` populates nested `lark`, `llm`, and `conversation` settings.
- Real environment variables override `.env`.
- Explicit `data_dir` overrides every settings source.
- `LARK_AGENT_LLM__API_KEY` and `LARK_AGENT_CONVERSATION__MAX_MESSAGES` preserve
  field underscores through the `__` nested delimiter.
- Invalid integer and empty data directory values raise validation errors.
- Runner startup without `lark.bot_id` still succeeds through mocked bot info
  resolution and injects the returned `open_id` into `BotApp`.

### 7. Wrong vs Correct

#### Wrong

```python
def load_config(path: str = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())
    ...
```

This adds a second application configuration path and makes users maintain both
YAML and environment files.

#### Correct

```python
class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LARK_AGENT_",
        env_file=".env",
        env_nested_delimiter="__",
    )
```

Environment variables and `.env` are the application configuration boundary.

## Scenario: Lark Bot Identity Resolution

### 1. Scope / Trigger

- Trigger: live Lark startup needs the bot identity used by mention routing.
- The identity is external state owned by Lark. Resolve it from the Lark bot
  info API at startup instead of making users maintain a local bot ID setting.
- SDK-specific request construction stays under `src/lark_agent/transport/lark/`.

### 2. Signatures

- `build_bot_info_request() -> BaseRequest`
- `fetch_lark_bot_info(client: LarkClientLike) -> LarkBotInfo`
- `python -m lark_agent.transport.lark.bot_info [--json]`
- `build_runner(config: AppConfig) -> LarkWebSocketBotRunner`

### 3. Contracts

- Bot info request:
  - HTTP method: `GET`
  - URI: `https://fsopen.bytedance.net/open-apis/bot/v3/info`
  - token type: `AccessTokenType.TENANT`
- Successful response must contain `code == 0` and `bot.open_id`.
- `build_runner()` must resolve bot info after validating app credentials and
  before constructing `BotApp`.
- `build_runner()` must pass a derived `AppConfig` to `BotApp` where
  `config.lark.bot_id == bot_info.open_id`.
- Bot ID is not a public environment key. If a legacy local value exists, live
  startup still ignores it and prefers the Lark API response.

### 4. Validation & Error Matrix

- Missing `lark.app_id` -> `validate_lark_config` raises `ValueError`.
- Missing `lark.app_secret` -> `validate_lark_config` raises `ValueError`.
- Bot info response with non-zero `code` -> `LarkBotInfoError` naming code/msg.
- Bot info response without `bot` object -> `LarkBotInfoError`.
- Bot info response without non-empty `bot.open_id` -> `LarkBotInfoError`.
- Bot info failure -> startup fails before opening WebSocket.

### 5. Good/Base/Bad Cases

- Good: `.env` contains only app credentials and LLM settings; startup fetches
  `bot.open_id` and group mention routing works.
- Base: manual bot info script prints `open_id` for diagnostics without asking
  users to write it back to `.env`.
- Bad: `build_runner()` uses `config.lark.bot_id` from `.env` when it differs
  from the API response.

### 6. Tests Required

- Request construction asserts method, URI, and tenant token type.
- Response parsing asserts `open_id`, app metadata, and error cases.
- Runner construction test patches the Lark client and bot info fetcher, then
  asserts `BotApp.config.lark.bot_id` and `MessageRouter.bot_id` equal the API
  `open_id`.
- Config validation test asserts missing app secret fails while missing bot ID
  does not.

### 7. Wrong vs Correct

#### Wrong

```python
validate_lark_config(config)  # requires config.lark.bot_id from .env
app = BotApp(config, sender=sender, llm_client=llm_client)
```

This makes startup depend on stale local identity configuration.

#### Correct

```python
validate_lark_config(config)
bot_info = fetch_lark_bot_info(lark_client)
runtime_config = config.model_copy(
    update={
        "lark": LarkConfig(
            app_id=config.lark.app_id,
            app_secret=config.lark.app_secret,
            bot_id=bot_info.open_id,
        )
    }
)
app = BotApp(runtime_config, sender=sender, llm_client=llm_client)
```

The app uses the live bot identity returned by Lark.

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
- `python -m lark_agent.main`

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

- Missing `lark.app_id` or `lark.app_secret` at startup -> raise `ValueError`
  before opening WebSocket.
- Missing or invalid bot identity from bot info resolution -> raise before
  opening WebSocket.
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
- Main-entry tests should cover config validation and bot identity injection
  with fake Lark clients; never start a real WebSocket in unit tests.

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
