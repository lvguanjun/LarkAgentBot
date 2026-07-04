# Project .agents layout for Skills and MCP

## Goal

将 Project 级 agent 资产从 chat group 根目录移到专用 `.agents/` 目录下。

用户价值：每个飞书群/私聊 Project 的运行时对话数据与 agent 配置分离，Skills 和 MCP 配置可以作为一组清晰的 agent 资产被检查、同步、备份和保护。

## Classification

这是轻量任务，`prd.md` 足够，不需要额外 `design.md` / `implement.md`。

原因：

- `SkillsRegistry.discover(defaults_dir, project_dir)` 已经集中管理 Skills 路径查找。
- `Project.get_skills_registry()` 是 app 层唯一 Skills registry 入口。
- MCP 尚未实现，本任务只需要先确定未来 MCP 配置路径。
- 变更需要测试和文档更新，但不引入新架构或外部集成。

## Background

- 父任务：`06-27-lark-agent-bot`。
- 依赖：已归档 `07-04-lark-agent-bot-core`，提供 `data/groups/<chat_id>/` Project 目录和 conversation 持久化。
- 依赖：已归档 `07-04-lark-agent-bot-skills`，实现了从直接 `skills/` 目录发现 Skills，以及 `read_skill` tool loop。
- 任务开始时，代码在 `src/lark_agent/skills.py` 中从 `data/defaults/skills/` 和 `data/groups/<chat_id>/skills/` 发现 Skills。
- 任务开始时，测试在 `tests/test_skills.py` 和 `tests/test_app.py` 中使用 `defaults / "skills"` 与 `project / "skills"` 作为 fixture。
- 父任务规划文档已在 planning 阶段同步为 `.agents/` canonical location，避免 MCP 实现前路径合同不稳定。

## Target Layout

群组 Project 目录：

```text
data/groups/<chat_id>/
  AGENTS.md
  .agents/
    skills/
      <skill_dir>/
        SKILL.md
        references/
    mcp.yaml
  conversations/
    <thread_id>/
      history.jsonl
```

默认 Project 目录：

```text
data/defaults/
  AGENTS.md
  .agents/
    skills/
      <skill_dir>/
        SKILL.md
        references/
    mcp.yaml
```

## Requirements

### R0: defaults 和 group 布局一致

- 全局 defaults 和 chat group project 都必须使用 `.agents/` 存放 agent 资产。
- 全局 Skills canonical path：`data/defaults/.agents/skills/`。
- 群组 Skills canonical path：`data/groups/<chat_id>/.agents/skills/`。
- 全局 MCP canonical path：`data/defaults/.agents/mcp.yaml`。
- 群组 MCP canonical path：`data/groups/<chat_id>/.agents/mcp.yaml`。

### R1: Skills 发现路径

- 从 `data/defaults/.agents/skills/` 发现全局 Skills。
- 从 `data/groups/<chat_id>/.agents/skills/` 发现群组 Skills。
- 保留当前按 `SKILL.md` frontmatter `name` 进行群组覆盖全局的行为。
- 保留 `read_skill(name)` 与 `read_skill(name, file="references/...")` 行为。
- 不向 LLM 暴露 `.agents` 文件系统路径。

### R2: MCP 规划路径

- 更新父任务和子任务规划文档，使未来 MCP 实现从以下位置加载配置：
  - 群组：`data/groups/<chat_id>/.agents/mcp.yaml`
  - 默认：`data/defaults/.agents/mcp.yaml`
- 本任务不实现 MCP；只确定目录合同。

### R3: 运行时数据分离

- conversation history 继续保存在 `data/groups/<chat_id>/conversations/`。
- 群组 `AGENTS.md` 继续保存在 `data/groups/<chat_id>/AGENTS.md`。
- 不移动现有 conversation JSONL 路径。

### R4: 文档和测试

- 更新 README 示例，展示 `.agents/skills/` 和 `.agents/mcp.yaml`。
- 更新父任务文档，让后续会话把 `.agents` 视为 canonical location。
- 更新 Skills tests 和 app tests，使 fixture 使用 `.agents/skills/`。
- 新增或更新测试，确保旧的直接 `skills/` 路径不再是 canonical discovery path。

## Acceptance Criteria

- [x] `SkillsRegistry.discover()` 能发现 `data/defaults/.agents/skills/` 下的默认 Skills。
- [x] `SkillsRegistry.discover()` 能发现 `data/groups/<chat_id>/.agents/skills/` 下的群组 Skills。
- [x] `.agents/skills/` 下的群组 Skills 仍按 frontmatter `name` 覆盖默认 Skills。
- [x] `read_skill` 仍能从新布局读取完整 `SKILL.md` 和 `references/...` 文件。
- [x] app 级 prompt injection 和 tool-loop 测试使用 `.agents/skills/` fixture 后继续通过。
- [x] README 记录 `.agents/skills/` 和 `.agents/mcp.yaml`。
- [x] 父任务 `lark-agent-bot` 规划文档把 `.agents/skills/` 和 `.agents/mcp.yaml` 作为 canonical location。
- [x] `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` 通过。

## Out of Scope

- 实现 MCP client、tool discovery 或 tool execution。
- 实现飞书 WebSocket live transport。
- 移动 conversation history。
- 为已有运行时数据添加 migration script；当前项目仍处于 pre-release/local-test 阶段。
- 移动 `AGENTS.md`。

## Decisions

- defaults 也使用 `.agents/`。`data/defaults/.agents/skills/` 与 `data/defaults/.agents/mcp.yaml` 是 canonical fallback locations。
- `AGENTS.md` 保持在 `data/defaults/AGENTS.md` 和 `data/groups/<chat_id>/AGENTS.md`；只有 Skills 和 MCP 移到 `.agents/`。
- 不要求兼容旧的直接 `skills/` fallback。项目仍是 pre-release/local-test 状态，测试应断言新 canonical path，而不是保留旧 fixture。

## Notes

- 任务已实现并通过测试。
- Inline workflow：不需要整理 `implement.jsonl` / `check.jsonl`。
