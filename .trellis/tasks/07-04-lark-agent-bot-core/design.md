# Design: 基础骨架与文本对话闭环

## Architecture

本子任务建立核心后端边界，不连接真实飞书 WebSocket，不实现 Skills/MCP。

```
IncomingMessage
  -> MessageRouter
  -> ProjectStore / Project
  -> Conversation
  -> AgentsConf
  -> LLMClient
  -> MessageSender
```

## Package Structure

```
src/lark_agent/
  __init__.py
  app.py
  config.py
  agents_conf.py
  conversation.py
  llm_client.py
  project.py
  router.py
  transport/
    __init__.py
    base.py
tests/
  test_agents_conf.py
  test_app.py
  test_config.py
  test_conversation.py
  test_router.py
```

## Component Boundaries

### Config

`config.py` owns typed dataclasses and YAML loading:

- `AppConfig`
- `LarkConfig`
- `LLMConfig`
- `ConversationConfig`

Tests can call `load_config(path)` with a temp YAML. Runtime defaults come from `config.yaml`.

### Transport Base

`transport/base.py` defines stable internal message shapes:

- `TextPart`
- `ImagePart`
- `IncomingMessage`
- `MessageSender`

The base layer performs no `lark-oapi` imports. The future WebSocket adapter will convert Feishu events into these objects.

### Router

`MessageRouter` is pure application logic:

- `should_respond(msg)` decides whether to process a message.
- `mark_thread_activated(chat_id, thread_id)` persists in memory for this slice.
- `get_thread_id(msg)` returns `root_id` when present, otherwise `chat_id` for p2p and message id/main-thread value for group main conversations.

Persistence for activation state can be added later if needed; MVP only needs process-local behavior for a running bot.

### Project And Agents

`ProjectStore` maps `chat_id` to `Project`.

`Project` exposes:

- `path`
- `get_agents_md()`
- `get_conversation(thread_id)`

`AgentsConf` loads group-level `AGENTS.md` first, then default `AGENTS.md`, then empty string.

### Conversation

`Conversation` appends JSON objects to `history.jsonl`, one OpenAI message per line.

Windowing uses a small grouping pass:

- Treat an assistant message with `tool_calls` and the following contiguous `tool` messages as an atomic group.
- Keep the most recent groups around `max_messages`; the returned context may exceed the limit when needed to preserve an atomic tool exchange.
- Never return a window starting with orphan `tool` messages.

This satisfies the parent requirement that truncation not break tool_call/tool_result pairing while keeping token counting out of this first slice.

### LLM Client

`LLMClient` wraps an injected OpenAI-compatible client. The first slice only supports final text responses:

```python
async def complete(system_prompt: str, messages: list[dict]) -> str
```

The implementation should keep constructor injection so tests can use a fake client and later slices can add tools without rewriting the app layer.

### App Orchestration

`BotApp.handle_message(msg)`:

1. Ask router whether to respond.
2. Resolve project and conversation.
3. Append user message.
4. Build context and system prompt.
5. Call LLM.
6. Append assistant message.
7. Send text reply to the original chat/thread.
8. Mark thread activated when bot is mentioned in a group thread or successfully replies in a thread.

## Compatibility

- Public internal dataclasses should be conservative and typed; future Feishu/MCP/Skills layers depend on them.
- Runtime data layout must match the parent task: `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`.
- No database or migration layer is introduced in this slice.

## Trade-offs

- No real WebSocket in the first child task: this keeps the first verification local and deterministic, but delays live Feishu smoke testing.
- In-memory thread activation: enough for first slice tests, but process restarts lose activation state.
- Message-count windowing before token counting: simpler and testable now, with a clear extension point for token budgets later.

## Rollback

All changes are additive new source/test/config files. Rollback is removing the new package skeleton and this child task's generated runtime data, if any.
