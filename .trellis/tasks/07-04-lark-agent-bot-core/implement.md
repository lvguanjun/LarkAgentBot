# Implementation Plan

## Checklist

- [x] Create project packaging and defaults
  - `pyproject.toml`
  - `config.yaml`
  - `data/defaults/AGENTS.md`
  - `src/lark_agent/__init__.py`

- [x] Implement core types and config
  - `src/lark_agent/config.py`
  - `src/lark_agent/transport/base.py`
  - config unit tests

- [x] Implement Project, AGENTS.md, and Conversation
  - `src/lark_agent/agents_conf.py`
  - `src/lark_agent/project.py`
  - `src/lark_agent/conversation.py`
  - tests for fallback, JSONL persistence, and window grouping

- [x] Implement routing and orchestration
  - `src/lark_agent/router.py`
  - `src/lark_agent/llm_client.py`
  - `src/lark_agent/app.py`
  - tests for trigger rules and fake end-to-end text response

- [x] Run validation and tighten
  - `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`
  - `UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src`
  - inspect diffs for scope creep beyond this child task

## Validation Commands

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

## Risky Files

- `conversation.py`: history windowing can accidentally orphan tool messages.
- `router.py`: group/thread activation rules can accidentally make the bot too chatty.
- `app.py`: ordering of persistence and send failures determines whether failed replies are recorded.

## Follow-up Checks Before Start

- PRD contains testable acceptance criteria.
- Design and implementation plan match the parent task scope.
- No unresolved open questions block implementation.
- Inline mode means JSONL context curation is skipped; Phase 2 should load `trellis-before-dev` before editing source.
