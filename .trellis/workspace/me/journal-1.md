# Journal - me (Part 1)

> AI development session journal
> Started: 2026-06-27

---

## 2026-06-27 19:40 — Brainstorm: lark-agent-bot Tools/Skills/Multimodal

**Task**: `.trellis/tasks/06-27-lark-agent-bot/` (status: planning)

### 已确认的决策

1. **Skills 遵循开放标准**，不做任何自定义扩展。能直接用开源 skills。
   - Agent Skills standard 已持久化到 `.trellis/spec/backend/agent-skills-standard.md`

2. **IncomingMessage.content 改为 `list[ContentPart]`**
   - MVP 图片降级为 `[用户发送了一张图片]` 占位文本
   - history 完整保存 ImagePart（file_key），后续可回溯

3. **Agent 给通用 exec/shell tool**（参考 OpenClaw + Hermes）
   - 不限制为白名单，因为要兼容任意开源 skill
   - Docker 容器作为主要安全边界
   - Tool allow/deny 策略为第二层

### 仍待讨论

- MVP 是否要求 Docker，还是可插拔 backend（默认 local）？
- 容器生命周期：per-group 持久 vs per-session 临时？
- Tool allow/deny 默认策略
- design.md 需要大幅重写（当前版本缺少 exec tool + sandbox 架构）

### 研究产出

- `.trellis/tasks/06-27-lark-agent-bot/research/agent-sandbox-comparison.md`
  — 对比 OpenClaw / Codex / Hermes / Claude Code / E2B / Modal 的沙箱方案

### 下次续接方式

1. 打开 task: `python3 ./.trellis/scripts/task.py current` 确认任务
2. 读 prd.md Open Questions 部分，从 Q1 待确认项继续
3. 确认 Docker 策略后，重写 design.md 的 Tool/Sandbox 架构

---


## Session 1: Lark agent core conversation slice

**Date**: 2026-07-04
**Task**: Lark agent core conversation slice
**Branch**: `master`

### Summary

Planned and implemented the first lark-agent-bot child task: Python package skeleton, uv-based validation, config loading, transport boundary dataclasses, router trigger rules, AGENTS.md fallback, JSONL conversation persistence/windowing, injectable OpenAI-compatible LLM client, BotApp orchestration, and 18 unit tests.

### Main Changes

- Raised the project Python requirement from `>=3.11` to `>=3.13`.
- Resolved runtime direct dependencies with `uv` against Python 3.13: `lark-oapi`, `mcp`, `openai`, and `pyyaml`.
- Resolved development direct dependencies with `uv` against Python 3.13: `pytest` and `pytest-asyncio`.
- Synchronized `uv.lock` and documented the future dependency-resolution convention in backend quality guidelines.

### Git Commits

| Hash | Message |
|------|---------|
| `b491f07` | (see git log) |

### Testing

- [OK] `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync --python 3.13 --extra dev`
- [OK] `UV_CACHE_DIR=.uv-cache uv lock --check`
- [OK] `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` (`37 passed`)
- [OK] `UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src`

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Skills read tool loop

**Date**: 2026-07-04
**Task**: Skills read tool loop
**Branch**: `master`

### Summary

Implemented the lark-agent-bot Skills slice: Skills discovery with default/group override, safe read_skill built-in tool, Tier 1 prompt injection, OpenAI-compatible tool loop persistence, focused tests, and backend spec contract updates.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a047b4e` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: MCP tools integration

**Date**: 2026-07-05
**Task**: MCP tools integration
**Branch**: `master`

### Summary

Implemented the lark-agent MCP child task: .agents/mcp.yaml defaults/group merge with enabled=false overrides, official MCP SDK stdio manager with injectable sessions, mcp__server__tool naming and schema conversion, unified built-in/MCP tool dispatch, BotApp lifecycle integration, JSONL tool-result persistence, and 37 passing tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `d57ba83` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: Update Python 3.13 dependency baseline

**Date**: 2026-07-05
**Task**: Update Python 3.13 dependency baseline
**Branch**: `master`

### Summary

Updated the project Python requirement to >=3.13, resolved runtime and dev direct dependencies through uv against Python 3.13, synchronized uv.lock, added dependency-resolution guidance to backend quality specs, validated uv sync, lock check, pytest, and compileall, then archived the task.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `7b02ef8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: Runtime data Git hygiene

**Date**: 2026-07-05
**Task**: Runtime data Git hygiene
**Branch**: `master`

### Summary

Moved runtime defaults out of tracked data into templates/defaults, ignored local data/, updated README and backend directory spec, verified ignored conversation history and full tests, then archived the lightweight task.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `bc9fe71` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: Feishu websocket transport

**Date**: 2026-07-05
**Task**: Feishu websocket transport
**Branch**: `master`

### Summary

Implemented the Feishu WebSocket transport slice: event conversion for text/post/image, Feishu reply/create sender, ack-first runner with TTL dedupe and background error logging, minimal python -m lark_agent.main startup, README live-bot notes, focused tests, and backend transport contract spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `34e4492` | (see git log) |
| `e9c5bf0` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
