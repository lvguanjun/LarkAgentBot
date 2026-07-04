# Skills 与 read_skill 工具闭环

## Goal

为父任务 `06-27-lark-agent-bot` 交付第二个可独立验证的后端切片：在已完成的 core 对话引擎上实现 Skills 发现、system prompt 注入、`read_skill` 内置 tool，以及 OpenAI 兼容的 tool calling 闭环。

用户价值：每个群组/私聊 Project 可以拥有可配置的只读技能包，LLM 能先看到可用 Skills 列表，再按需读取完整 Skill 指令和 reference 文件，从而让飞书机器人具备可扩展的项目级能力。

## Background

- 父任务要求 Skills 采用 `SKILL.md` + YAML frontmatter，并实现三层渐进加载：Tier 1 发现、Tier 2 读取完整 Skill、Tier 3 读取 references 文件：`.trellis/tasks/06-27-lark-agent-bot/prd.md:58`。
- 父任务已决策 MVP 内置 tool 仅 `read_skill(name, file?)`，不提供通用 `read_file`、`exec` 或 `write_file`：`.trellis/tasks/06-27-lark-agent-bot/prd.md:133`。
- 父任务已决策 Skills 在 MVP 中只读，不执行 scripts：`.trellis/tasks/06-27-lark-agent-bot/prd.md:144`。
- `lark-agent-bot-core` 已完成本子任务依赖的基础能力：`ProjectStore`/`Project` 映射 `data/groups/<chat_id>/`，`Conversation` 持久化 OpenAI messages JSONL，`BotApp` 串联 router、project、conversation 和 LLM。
- 当前 `Project` 只有 `get_agents_md()` 和 `get_conversation()`，还没有 Skills registry 入口：`src/lark_agent/project.py:33`。
- 当前 `LLMClient.complete()` 只返回纯文本，不支持 tools 参数、tool_calls 或 assistant/tool/final 链路：`src/lark_agent/llm_client.py:27`。
- 当前 `BotApp.handle_message()` 只保存 user 和 assistant final，不保存 tool_calls/tool results：`src/lark_agent/app.py:39`。
- 当前 `Conversation.get_context()` 已有不切断 `assistant(tool_calls)` 与后续 `tool` 结果的窗口逻辑，可直接复用：`src/lark_agent/conversation.py:36`。

## Requirements

### R1: Skills 发现与覆盖

- 新增 `src/lark_agent/skills.py`，发现以下目录中的 Skill：
  - 全局默认：`data/defaults/skills/<skill_name>/SKILL.md`
  - 群组级：`data/groups/<chat_id>/skills/<skill_name>/SKILL.md`
- Skill 目录名必须是内部定位键，`SKILL.md` frontmatter 中的 `name` 是暴露给 LLM 的调用名。
- 解析 `SKILL.md` YAML frontmatter 中的 `name` 和 `description`；缺失或格式非法时跳过该 Skill，并提供可测试的错误记录或返回值。
- 群组级 Skills 覆盖同名全局 Skills；非同名 Skills 合并。

### R2: System Prompt 注入

- `Project` 提供 Skills registry 入口。
- `BotApp` 调 LLM 前将 AGENTS.md 与可用 Skills 列表合并为 system prompt。
- Skills 列表只包含 `name` 和 `description`，不把完整 Skill body 或 references 预先塞入 prompt。
- 没有可用 Skills 时，system prompt 行为应与 core 版本兼容，不引入多余噪声。

### R3: `read_skill` 内置 tool

- 新增 `src/lark_agent/tools.py`，提供内置 tool 注册和执行。
- 暴露给 LLM 的 function schema 仅包含：
  - `name`：必填，Skill name
  - `file`：可选，仅允许读取该 Skill 下 `references/` 内的相对文件
- `read_skill(name)` 返回该 Skill 的完整 `SKILL.md` 内容。
- `read_skill(name, file="references/xxx.md")` 返回 reference 文件内容。
- 必须防止路径注入：
  - 不接受绝对路径
  - 不接受 `..`
  - 不接受符号链接逃逸 Skill 目录
  - 不允许读取 `references/` 之外的文件
- 未知 Skill 或非法文件路径返回结构化错误文本供 LLM 消费，不导致整个消息处理崩溃。

### R4: LLM Tool Loop

- 扩展 `LLMClient` 支持 OpenAI 兼容 tools/function calling。
- LLM 可接收 `tools` schema；当返回 `tool_calls` 时，应用层执行内置 tool 并把 tool result 作为 OpenAI `tool` 消息追加回上下文，再请求 final assistant 回复。
- MVP 支持多轮 tool loop，但必须设置最大迭代次数，避免无限循环。
- 对话历史必须完整持久化：
  - user message
  - assistant message with `tool_calls`
  - one or more `tool` result messages
  - assistant final message
- fake LLM client 必须能在单元测试中模拟 tool_calls 和 final response，不依赖真实 OpenAI API。

### R5: Scope Boundary

- 本子任务只实现 Skills 和内置 `read_skill`。
- 不实现 MCP server 连接或 MCP tool execution，但 tool loop 的接口命名应便于后续加入 MCP tools。
- 不实现 Skills scripts 执行。
- 不实现管理命令，如 `/skill list`。

## Acceptance Criteria

- [x] 单元测试覆盖全局 Skills 发现，并验证 `name` / `description` frontmatter 解析。
- [x] 单元测试覆盖群组级 Skills 覆盖同名全局 Skills，且能合并非同名全局 Skills。
- [x] 单元测试覆盖 system prompt 同时包含 AGENTS.md 和 Tier 1 Skills 列表，但不包含完整 Skill body。
- [x] 单元测试覆盖 `read_skill(name)` 读取完整 `SKILL.md`。
- [x] 单元测试覆盖 `read_skill(name, file="references/xxx.md")` 读取 reference 文件。
- [x] 单元测试覆盖 `read_skill` 拒绝绝对路径、`..`、非 `references/` 文件和符号链接逃逸。
- [x] 单元测试覆盖 fake LLM 发起 `read_skill` tool_call，应用层执行 tool，随后得到 final assistant 回复。
- [x] 对话 JSONL 持久化完整包含 user、assistant(tool_calls)、tool、assistant(final) 链路。
- [x] 现有 core 测试继续通过。
- [x] `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` 通过。

## Out of Scope

- 真实飞书 WebSocket 长连接。
- MCP tools 发现、转换和执行。
- Skills scripts、`exec`、通用 `read_file`、写文件能力。
- `/skill`、`/config`、`/mcp` 等管理指令。
- token 级窗口截断和摘要压缩。
