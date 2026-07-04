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
    ├── config.py           # Typed YAML configuration loading
    ├── agents_conf.py      # AGENTS.md fallback loading
    ├── conversation.py     # JSONL history persistence and context windowing
    ├── llm_client.py       # OpenAI-compatible client wrapper
    ├── project.py          # chat_id -> Project and conversation paths
    ├── router.py           # Trigger rules and thread activation state
    └── transport/
        └── base.py         # Internal transport boundary dataclasses/protocols
```

---

## Module Organization

- Keep external SDK-specific code in adapter modules, not in core logic. For
  example, future `lark-oapi` WebSocket code belongs under `transport/`, while
  tests should exercise `IncomingMessage` from `transport/base.py`.
- Put one cross-layer contract owner next to the data it owns:
  `conversation.py` owns history JSONL message grouping, `project.py` owns
  filesystem path layout, and `config.py` owns YAML decoding.
- Prefer constructor injection for external clients (`LLMClient`, sender
  protocols) so tests can use fakes without network or credentials.

---

## Naming Conventions

- Use lowercase snake_case module names.
- Runtime group data lives under `data/groups/<chat_id>/`.
- Default project resources live under `data/defaults/`.
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
- `src/lark_agent/conversation.py`: JSONL persistence and windowing owned in one
  module instead of repeated parsing in consumers.
