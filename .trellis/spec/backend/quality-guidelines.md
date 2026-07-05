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
- Do not hard-code dependency versions from memory or model knowledge. Resolve
  the current compatible release with `uv` at implementation time.
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
- Treat Python 3.13 as the dependency resolution baseline. When adding or
  upgrading runtime or development dependencies, resolve the latest stable
  version compatible with Python 3.13 through `uv`; do not limit choices to the
  versions already present in `pyproject.toml`.
- Prefer `uv` commands that update both project metadata and `uv.lock`, for
  example:

```bash
UV_CACHE_DIR=.uv-cache uv add --python 3.13 <package>
UV_CACHE_DIR=.uv-cache uv add --python 3.13 --optional dev <package>
UV_CACHE_DIR=.uv-cache uv lock --python 3.13 --upgrade-package <package>
```

- Only pin an exact dependency version when a compatibility issue, reproducible
  bug, or upstream regression requires it; document the reason near the change.
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
- New or updated dependencies were resolved with `uv` against Python 3.13, not
  copied from existing `pyproject.toml` bounds or model knowledge.
- New runtime files are not generated artifacts (`.venv/`, `.uv-cache/`,
  `__pycache__/`, `*.egg-info/`).
- Cross-layer payloads are decoded in one owner module.
- New external integrations remain behind adapters or injectable clients.
