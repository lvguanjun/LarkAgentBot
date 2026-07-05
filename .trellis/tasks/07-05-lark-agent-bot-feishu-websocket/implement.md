# Implementation Plan

## Dependencies

- Depends on archived `07-04-lark-agent-bot-core`.
- Depends on archived `07-04-lark-agent-bot-skills`.
- Depends on archived `07-04-lark-agent-bot-agents-layout`.
- Depends on archived `07-05-runtime-data-git-hygiene`.
- Depends on archived `07-05-lark-agent-bot-mcp`.

## Checklist

- [x] Add `src/lark_agent/transport/websocket.py`.
- [x] Implement pure event conversion helpers:
  - [x] chat type normalization
  - [x] sender ID extraction
  - [x] mention ID extraction
  - [x] text content parsing
  - [x] image content parsing
  - [x] post content flattening
- [x] Implement `LarkMessageSender.send_text`.
- [x] Implement WebSocket runner registration for `p2.im.message.receive_v1`.
- [x] Implement bounded TTL event deduplication:
  - [x] derive key from event id/uuid when available
  - [x] fallback to `message_id`
  - [x] skip events without stable keys
  - [x] avoid scheduling duplicate keys in the TTL window
- [x] Implement ack-first callback behavior:
  - [x] convert event synchronously
  - [x] schedule `BotApp.handle_message()` as a background task
  - [x] keep task references until completion
  - [x] log task exceptions without propagating to the SDK callback
- [x] Add `src/lark_agent/main.py` with config validation and live startup.
- [x] Add `tests/test_lark_websocket.py` covering conversion, sender requests, dedupe behavior, ack-first scheduling, and runner callback behavior.
- [x] Update README current-status and startup notes after implementation.
- [x] Run validation commands.

## Validation Commands

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
git status --short
```

Manual live validation, only when credentials are available:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m lark_agent.main
```

## Risky Files

- `src/lark_agent/transport/websocket.py`: SDK boundary and event-loop bridge.
- `src/lark_agent/main.py`: live startup; avoid tests invoking blocking `Client.start()`.
- `src/lark_agent/config.py`: avoid expanding config unless required; current `LarkConfig` is enough for MVP.
- `README.md`: keep setup instructions accurate without exposing secrets.

## Rollback Points

- If SDK event model builder proves awkward in tests, keep conversion helpers accepting duck-typed event objects.
- If thread reply semantics are not accepted by Feishu API in live validation, keep sender isolated so only request construction needs adjustment.
- If SDK `Client.start()` event-loop behavior conflicts with async tests, do not unit test real start; test runner wiring with an injected fake WebSocket client factory.
- If background task scheduling on the SDK loop is insufficient under load, later introduce an explicit worker queue; do not block the event callback while experimenting.
- If single-process TTL dedupe is not enough for deployment topology, capture persistent/multi-replica dedupe as a separate task instead of expanding this slice.

## Ready Check Before `task.py start`

- [x] PRD has testable acceptance criteria.
- [x] Design explains SDK boundaries and error handling.
- [x] Implementation plan lists validation commands.
- [ ] User has reviewed and approved starting implementation.
