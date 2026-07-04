# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Backend work is validated with `uv`. Do not rely on system `pip` or globally
installed `pytest`; Codex sandboxes may not have writable home caches or a pip
module installed.

---

## Forbidden Patterns

- Do not add external SDK imports to core modules that are meant to be tested
  locally. Keep SDK adapters at the edge and depend on typed internal
  dataclasses/protocols.
- Do not parse history JSONL fields in multiple consumers. `conversation.py`
  owns history decoding and context windowing.
- Do not hard-truncate an `assistant(tool_calls)` message away from its
  contiguous `tool` results. Context windows may exceed `max_messages` to keep
  that atomic exchange intact.

---

## Required Patterns

- Use `uv` for dependency resolution and test execution.
- In restricted Codex sandboxes, set `UV_CACHE_DIR=.uv-cache` so uv writes cache
  data inside the workspace.
- Keep external clients injectable so tests can run without live credentials or
  network access.

---

## Testing Requirements

Run these checks for backend changes:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

Tests for new modules should cover the boundary contract, not only happy-path
helpers. For this bot, that includes trigger rules, AGENTS.md fallback,
conversation JSONL round trips, context window tool-pair preservation, and fake
client/sender orchestration.

---

## Code Review Checklist

- Tests pass with `uv`, not a globally installed pytest.
- New runtime files are not generated artifacts (`.venv/`, `.uv-cache/`,
  `__pycache__/`, `*.egg-info/`).
- Cross-layer payloads are decoded in one owner module.
- New external integrations remain behind adapters or injectable clients.
