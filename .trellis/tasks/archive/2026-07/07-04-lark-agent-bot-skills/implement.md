# Implementation Plan

## Phase 1: Skills Registry

- [x] Add `src/lark_agent/skills.py`.
- [x] Parse `SKILL.md` frontmatter with `yaml.safe_load`.
- [x] Discover global and group Skills with group override semantics.
- [x] Generate stable Tier 1 system prompt fragment.
- [x] Add tests for discovery, invalid metadata handling, and override behavior.

## Phase 2: Built-in read_skill Tool

- [x] Add `src/lark_agent/tools.py`.
- [x] Define OpenAI function schema for `read_skill`.
- [x] Implement `read_skill(name)` for full `SKILL.md`.
- [x] Implement `read_skill(name, file="references/...")` for references.
- [x] Add path safety checks for absolute path, `..`, non-reference files, directories, and symlink escape.
- [x] Add tests for successful reads and rejected reads.

## Phase 3: Project and Prompt Integration

- [x] Add `Project.get_skills_registry()`.
- [x] Update `BotApp` prompt construction to append the Skills Tier 1 list after AGENTS.md.
- [x] Preserve no-Skills behavior for existing tests.
- [x] Add app-level test verifying AGENTS.md + Skills list are passed to the LLM without full Skill body.

## Phase 4: LLM Tool Loop

- [x] Extend `LLMClient` with a structured assistant-message method while keeping `complete()` compatibility.
- [x] Support fake clients that return OpenAI-style assistant messages.
- [x] Pass `tools` to OpenAI chat completions when tools are available.
- [x] Update `BotApp` to run bounded tool loop and persist assistant(tool_calls), tool result, and assistant(final).
- [x] Add end-to-end fake LLM test for `read_skill` tool_call and final reply.

## Phase 5: Validation

- [x] Run full test suite.
- [x] Run compile check.
- [x] Check git diff for accidental runtime data or cache files.

## Validation Commands

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
git status --short
```

## Risky Areas

- OpenAI SDK response objects differ from fake dict objects; isolate response normalization in `LLMClient`.
- Tool loop persistence must preserve exact OpenAI message shapes so `Conversation.get_context()` can keep tool pairs intact.
- Prompt concatenation must avoid duplicating Skills content across turns.
- Path safety must account for symlinks, not only lexical `..` checks.

## Ready Check Before `task.py start`

- [x] PRD, design, and implementation plan reviewed.
- [x] Parent task map includes this child task.
- [x] No blocking open product questions remain.
- [x] Inline workflow confirmed; no implement/check JSONL curation required.
