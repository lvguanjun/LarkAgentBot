# Implementation Plan

## Current Status

This parent task remains in `planning`, with implementation delivered through independently verifiable child tasks.

Completed child tasks:

- [x] `07-04-lark-agent-bot-core`: package skeleton, config loading, transport base types, routing rules, Project/Conversation persistence, AGENTS.md fallback, fake-LLM text conversation loop.
- [x] `07-04-lark-agent-bot-skills`: Skills discovery, Tier 1 prompt injection, safe `read_skill` built-in tool, bounded OpenAI-compatible tool loop, complete tool-call JSONL persistence.
- [x] `07-04-lark-agent-bot-agents-layout`: moved Skills and MCP agent asset contracts under project `.agents/` directories.

Current verification:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
# 26 passed
```

## Completed Capabilities

- [x] `pyproject.toml` declares Python 3.11+ and dependencies: `lark-oapi`, `openai`, `mcp`, `pyyaml`.
- [x] `config.yaml` and `src/lark_agent/config.py` provide typed local config loading.
- [x] `transport/base.py` defines `IncomingMessage`, text/image content parts, and `MessageSender`.
- [x] `router.py` implements private chat, group mention, activated thread, and command-boundary routing.
- [x] `project.py` maps `chat_id` to `data/groups/<chat_id>/`.
- [x] `conversation.py` persists OpenAI messages as JSONL and windows history without splitting tool_call/tool result pairs.
- [x] `agents_conf.py` loads group `AGENTS.md` with fallback to `data/defaults/AGENTS.md`.
- [x] `skills.py` discovers global/group Skills and handles group override semantics.
- [x] `tools.py` exposes the safe `read_skill(name, file?)` built-in tool.
- [x] `llm_client.py` supports OpenAI-compatible chat completions with optional tools.
- [x] `app.py` orchestrates router, project, conversation, prompt construction, bounded tool loop, persistence, and sender reply.

## Remaining Work

### Next Recommended Child: Runtime Data Git Hygiene

- [ ] Add `data/` to `.gitignore` so runtime group messages and local defaults are not shown by `git status`.
- [ ] Move committed default resources from `data/defaults/` to `templates/defaults/`.
- [ ] Update README setup instructions to copy templates into local `data/defaults/`.
- [ ] Verify generated `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl` and local edits to `data/defaults/AGENTS.md` stay ignored.
- [ ] Verify `templates/defaults/AGENTS.md` remains tracked as the de-identified bootstrap template.

### Next Recommended Child: MCP Tools

- [ ] `mcp_manager.py`: MCP Client 连接管理、tools 发现、tool 执行
- [ ] `.agents/mcp.yaml` loading with group override and defaults fallback.
- [ ] Convert MCP tool schemas to OpenAI-compatible function tool schemas.
- [ ] Combine built-in `read_skill` tools and MCP tools in one dispatcher.
- [ ] Execute MCP tool calls from the existing bounded tool loop.
- [ ] Persist assistant(tool_calls), MCP tool result, and assistant(final) in the existing JSONL format.
- [ ] Add fake/in-memory MCP tests; avoid requiring real external MCP server processes for unit tests.

### Later Child: Live Feishu Transport

- [ ] `transport/websocket.py`: 飞书 WebSocket 长连接实现
- [ ] Convert Feishu text/post/image message events into `IncomingMessage`.
- [ ] Send text replies into the correct chat/thread using `MessageSender`.
- [ ] Add integration-friendly tests around event conversion and sender payload construction.

### Later Child: Management Commands

- [ ] `commands.py`: `/help`, `/config`, `/skill list`, `/mcp list`, `/reset`
- [ ] Route commands after mention/private-chat trigger rules but before LLM handling.
- [ ] Keep command behavior local and deterministic; avoid invoking LLM for management responses.

### Later Polish

- [ ] `main.py`: runnable bot entrypoint once live transport exists.
- [ ] README examples for live Feishu setup and MCP config once those features exist.

## Validation Commands

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
git status --short
```

## Risky Areas

- MCP stdio transport 的进程管理（子进程生命周期、异常处理、shutdown cleanup）
- MCP/OpenAI tool name collisions between servers or between MCP and built-in tools
- MCP tool schema conversion fidelity, especially required fields and nested JSON schema
- Ensuring MCP tool failures become model-readable tool result text rather than crashing `BotApp`
- 飞书 WebSocket 长连接的稳定性和重连机制
- 并发消息处理（同一话题多人同时发消息）

## Ready Check Before Starting the MCP Child

- [ ] Create a child task for MCP, or update an existing one if already present.
- [ ] Keep the child independently verifiable without live Feishu credentials.
- [ ] Write child dependencies explicitly: it depends on archived `lark-agent-bot-core` and `lark-agent-bot-skills`.
- [ ] Because current workflow is inline mode, skip `implement.jsonl` / `check.jsonl` curation.
- [ ] Ask for review before running `task.py start`.
