# Agent Skills Standard Reference

> Source: [Cursor Agent Skills Docs](https://cursor.com/cn/docs/skills) / [agentskills.io](https://agentskills.io)
>
> This document captures the Agent Skills open standard that our bot's Skills subsystem must follow.

---

## Core Model

Skills are **passive instruction + resource packages**. They do NOT execute anything themselves.

- A Skill tells the Agent **what to do** and **when to do it**
- The Agent uses its **own native tools** (read, shell, etc.) to follow the skill's instructions
- Permission isolation happens at the **tool layer**, not the skill layer

```
Skill = Instructions (SKILL.md) + Resources (scripts/, references/, assets/)
Agent = LLM + Native Tools (read, exec, list, ...)

Execution flow:
  1. Agent sees skill list (name + description from frontmatter)
  2. Agent decides a skill is relevant → reads full SKILL.md
  3. SKILL.md says "run scripts/deploy.sh <env>"
  4. Agent uses its native `exec` tool to run the script
```

---

## SKILL.md File Format

```markdown
---
name: my-skill              # identifier, lowercase + hyphens, must match folder name
description: Brief desc     # used by agent to judge relevance
paths: "**/*.py"            # optional: scope to matching files only
disable-model-invocation: false  # true = slash-command only, no auto-invoke
metadata: {}                # arbitrary key-value
---

# My Skill

Detailed instructions for the agent.

## When to Use
- condition A
- condition B

## Instructions
- step-by-step guidance
- reference scripts: `scripts/foo.sh`
- reference docs: `references/REFERENCE.md`
```

---

## Directory Structure

```
skills/
└── <skill-name>/
    ├── SKILL.md          # required: instructions + frontmatter
    ├── scripts/          # optional: executable code agent can run
    │   ├── deploy.sh
    │   └── validate.py
    ├── references/       # optional: additional docs loaded on demand
    │   └── REFERENCE.md
    └── assets/           # optional: templates, configs, static files
        └── config-template.json
```

---

## Three-Tier Progressive Loading

| Tier | What | When | Cost |
|------|------|------|------|
| Tier 1: Discovery | name + description (frontmatter) | Always loaded at startup | Minimal (one line per skill in system prompt) |
| Tier 2: Activation | Full SKILL.md body | Agent decides skill is relevant | Medium (full instructions into context) |
| Tier 3: Execution | scripts/, references/, assets/ | Agent follows instructions to read/run | Variable (file reads, script execution) |

---

## Key Design Principles

1. **Agent-tool separation**: Skills don't "have" tools. The agent has tools. Skills tell the agent how to use them.

2. **Scripts are passive**: `scripts/deploy.sh` is just a file sitting there. The agent's `exec` tool runs it. The permission boundary is on the exec tool, not on the skill.

3. **Progressive context efficiency**: Only load what's needed. Tier 1 costs ~1 line per skill. Tier 2 costs the full SKILL.md. Tier 3 costs individual file reads.

4. **Portability**: Skills work across any agent that supports the standard (Cursor, Claude Code, Codex, etc.)

5. **Version-controlled**: Skills live in the filesystem, tracked by git.

---

## Implications for Our Bot Design

### The bot needs native tools

Since skills don't execute anything themselves, the bot's LLM must have built-in tools to:
- Read files (skill references, project docs)
- Execute scripts (skill scripts)
- List directory contents (discover available resources)

### Permission model lives on tools, not skills

A skill that includes `scripts/rm-everything.sh` is harmless if the bot's exec tool:
- Only allows execution within skill `scripts/` directories
- Runs with restricted env vars
- Has timeout enforcement
- Has no network access (unless explicitly allowed)

### Skills are just context injection with resource pointers

The SKILL.md body goes into the LLM context. Any `scripts/` or `references/` paths mentioned in it are resources the LLM can choose to access via its tools.

---

## Comparison: MCP Tools vs Skills

| Aspect | MCP Tools | Skills |
|--------|-----------|--------|
| What they provide | Executable capabilities (functions) | Instructions + resources |
| Who executes | MCP server process | Agent via its native tools |
| Discovery | Tool list from MCP server | SKILL.md frontmatter scan |
| Invocation | LLM returns tool_call → MCP server handles | LLM reads SKILL.md → uses native tools |
| Permission | MCP server controls its own scope | Native tool layer controls scope |
| Statefulness | MCP server can maintain state | Stateless (just files) |
| Use case | External services, APIs, databases | Workflows, conventions, reusable procedures |

Both coexist: MCP provides capabilities, Skills provide knowledge + workflows that may use those capabilities.
