<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## When Writing Documentation

If the documentation is intended for humans, write it in **Chinese**. If the documentation is intended for machines, write it in **English**.

- `prd.md` or `design.md` will be reviewed/approved by a human → Write it in Chinese
- Content is only injected into agents, manifests, or machine-oriented context → English is acceptable
- Unsure who reads it → Treat it as human-reviewed and write Chinese


## Code Style

- Use src layout python package structure
- Always use absolute imports

## Pre-Commit Checks

提交代码前先执行自动修复和验证：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev ruff check src tests --fix
UV_CACHE_DIR=.uv-cache uv run --extra dev ruff format src tests
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

## Development Stage

- This project is in active development. Do not implement backward-compatibility code paths; every change should follow the current best-practice design and keep the codebase fully up to date.
