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

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `b491f07` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
