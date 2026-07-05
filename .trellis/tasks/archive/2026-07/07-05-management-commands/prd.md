# 管理命令

## Goal

为 Lark Agent 增加第一批低风险管理命令，让用户可以在飞书聊天里查看机器人能力、当前配置摘要、可用 Skills、MCP 配置状态，并重置当前会话历史。

本任务优先补齐已经预留但未实现的命令入口，不引入通用文件读写、脚本执行、用户级权限或跨进程状态管理。

## 已确认事实

- `TODO.md:7` 将管理命令标为下一步推荐：`/help`、`/config`、`/skill list`、`/mcp list`、`/reset`。
- `README.md:30` 明确说明 management commands 仍待实现，`README.md:32` 也将其列为下一推荐实现切片。
- `src/lark_agent/router.py:39` 已经能识别管理命令：私聊中 `/` 开头即为命令；群聊中需要提及机器人且文本以 `/` 开头。
- `src/lark_agent/app.py:42` 当前遇到命令后直接返回 `None`，不会发送回复，也不会调用 LLM。
- 项目已经有 Project、SkillsRegistry、MCP config、Conversation 等边界，可用于实现只读管理命令和当前会话 reset。

## Requirements

- R1: `/help` 返回支持的管理命令清单和简短说明。
- R2: `/config` 返回当前聊天可见的配置摘要，至少包含 `data_dir`、LLM model、conversation max_messages、当前 chat/thread 标识、是否配置 Lark 凭证；不得输出 API key、app secret 或其他敏感值原文。
- R3: `/skill list` 返回当前聊天可用 Skills 的名称和 description，并包含发现错误摘要；无 Skills 时返回明确的空状态。
- R4: `/mcp list` 返回当前聊天合并后的 MCP server 配置摘要，例如 server 名称、command 是否存在、args 数量、env key 名称；不得输出 env 值。该命令不启动 MCP server，也不做工具发现。
- R5: `/reset` 清空当前聊天当前 thread/conversation 的历史，并发送确认消息。群聊 topic 内只重置该 topic；私聊重置私聊 conversation；群聊主线重置 main conversation。
- R6: 未知命令返回可理解的错误和 `/help` 引导。
- R7: 管理命令不调用 LLM，不写入普通对话 history，除 `/reset` 删除当前 history 外不改动运行时资源。
- R8: 群聊命令继续遵守现有 router 规则：只有提及机器人且以 `/` 开头时才响应；私聊 `/` 命令直接响应。
- R9: README 更新管理命令使用说明；`TODO.md` 将管理命令条目标记为已完成或细化剩余项。

## Acceptance Criteria

- [x] `/help`、`/config`、`/skill list`、`/mcp list`、`/reset` 在私聊中返回文本回复，且 fake LLM 未被调用。
- [x] 群聊中未提及机器人的 `/help` 不响应；提及机器人后的 `/help` 会响应。
- [x] `/config` 和 `/mcp list` 的测试覆盖敏感值不泄露。
- [x] `/skill list` 覆盖有 Skills、无 Skills、存在 discovery error 的情况。
- [x] `/reset` 覆盖当前 conversation history 被删除或清空，并且不会影响同一 chat 下其他 thread 的 history。
- [x] 未知命令有测试覆盖，并返回 `/help` 引导。
- [x] 全量测试通过：`UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`。
- [x] 编译检查通过：`UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src`。

## Out of Scope

- `/config set` 和任何运行时配置写入。该能力需要先单独设计安全白名单字段。
- 启动 MCP server 并列出实际工具。当前 `/mcp list` 只做配置摘要，避免管理命令产生额外进程和副作用。
- Webhook 接入、图片/OCR/vision、飞书卡片交互、生产部署说明。
- 用户级权限控制、跨进程事件去重、通用 exec/write/read 文件工具、Skills 脚本执行。

## 技术备注

- 这是轻量任务，PRD-only 足够；实现前仍需通过 Trellis `task.py start` 进入 `in_progress`。
- 文档面向人类，按项目 AGENTS.md 要求使用中文。
