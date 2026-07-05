# MCP Tools 集成

## Goal

为现有飞书聊天机器人核心接入 MCP tools，使每个群组/私聊 Project 可以通过 `.agents/mcp.yaml` 配置自己的 MCP servers，并让 LLM 在现有 bounded tool loop 中发现、调用 MCP tools，最终把工具结果写入当前 JSONL 对话历史。

用户价值：群组可以通过标准 MCP 扩展领域能力，例如查询数据库、调用内部 API、读取外部系统，而不需要把这些能力硬编码进机器人。

## Background

- 父任务：`06-27-lark-agent-bot`。
- 依赖子任务已完成：
  - `07-04-lark-agent-bot-core`：包骨架、配置加载、路由、Project/Conversation、AGENTS.md fallback、fake LLM 对话闭环。
  - `07-04-lark-agent-bot-skills`：Skills 发现、`read_skill` 内置 tool、bounded OpenAI-compatible tool loop、完整 tool-call JSONL 持久化。
  - `07-04-lark-agent-bot-agents-layout`：将 Skills 和 MCP 约定路径移动到每个 Project 的 `.agents/` 下。
- 当前代码中 `BotApp` 已经支持 OpenAI-compatible `tool_calls`，但只会分发内置 `read_skill`。
- 当前代码还没有 `src/lark_agent/mcp_manager.py`，也没有 `.agents/mcp.yaml` 加载逻辑。
- 项目已有全局 `config.yaml` 和 `PyYAML` 依赖，因此 MCP 配置文件采用 YAML。

## Requirements

### R1: MCP 配置文件

- MVP 只支持 `.agents/mcp.yaml`，不支持 `mcp.json`。
- 群组配置路径：`data/groups/<chat_id>/.agents/mcp.yaml`。
- 默认配置路径：`data/defaults/.agents/mcp.yaml`。
- 全局默认配置和群组配置按 server name 合并。
- 群组配置中的同名 server 整体覆盖默认 server；不同名 server 追加。
- 支持群组配置用 `enabled: false` 显式禁用默认 server。
- 配置格式使用 `mcpServers` 顶层字段，兼容常见 MCP 客户端命名：

```yaml
mcpServers:
  demo:
    enabled: true
    transport: stdio
    command: python
    args:
      - -m
      - demo_mcp_server
    env:
      DEMO_TOKEN: "${DEMO_TOKEN}"
```

- MVP 只支持 `transport: stdio`。
- `command` 必填；`args`、`env`、`cwd` 可选。
- `enabled` 可选，默认为 `true`。
- 无 MCP 配置时应视为没有 MCP tools，而不是启动失败。

### R2: MCP SDK 和依赖版本

- 使用官方 Python MCP SDK。
- 本任务不引入独立 `fastmcp` PyPI 包；官方 SDK 中的 server helper `mcp.server.fastmcp.FastMCP` 与独立 FastMCP 包不是同一个依赖目标。
- 不强制沿用当前 `uv.lock` 中的 MCP 版本；实现时允许根据实际 SDK API、兼容性和测试结果升级 `pyproject.toml`/`uv.lock` 中的依赖版本。
- 依赖升级必须通过测试验证，并避免引入与本任务无关的依赖变更。

### R3: MCP Manager

- 新增 `src/lark_agent/mcp_manager.py`。
- 提供面向 `BotApp` 的最小接口：
  - `get_tools_for_llm() -> list[dict]`
  - `call_tool(name: str, args: dict) -> str`
  - 必要时提供 async lifecycle，例如 `start()` / `shutdown()`。
- 负责：
  - 读取 MCP 配置。
  - 建立 stdio MCP client session。
  - 调用 `list_tools` 发现 MCP tools。
  - 调用 `call_tool` 执行工具。
  - 将工具执行结果转换为 LLM 可读文本。

### R4: Tool 命名和冲突处理

- OpenAI-facing MCP tool name 必须稳定且避免冲突。
- 使用命名空间格式：`mcp__<server>__<tool>`。
- `read_skill` 保持内置 tool 名称，不改名。
- MCP server 名称和 tool 名称需要校验/规范化，避免生成非法 OpenAI function name。
- MCP tool 与内置 tool、不同 server 之间的 tool 不应相互覆盖。
- server/tool 名称规范化后发生冲突时应启动失败并给出明确错误，不自动追加后缀。

### R5: OpenAI Tool Schema 转换

- MCP tool 的 `inputSchema` 转换为 OpenAI-compatible function tool 的 `parameters`。
- MCP tool 的 `description` 透传；缺失时使用安全默认描述。
- 转换结果应可与现有 `LLMClient.complete_message(..., tools=tools)` 直接配合。

### R6: 统一 Tool 分发

- `BotApp` 的 bounded tool loop 继续作为唯一 tool loop。
- LLM 可用 tools = 内置 `read_skill` + MCP tools。
- MCP tool calls 通过 MCP Manager 执行，内置 tool calls 通过 `BuiltinTools` 执行。
- 未知 tool、参数解析失败、MCP 调用异常都应返回 tool result 文本，而不是让消息处理崩溃。

### R7: JSONL 持久化

- 继续使用现有 OpenAI messages JSONL 格式。
- MCP 调用链路必须完整保留：
  - user
  - assistant(tool_calls)
  - tool(result)
  - assistant(final)
- MCP tool result 的 `tool_call_id` 必须对应 assistant tool call ID。
- 不改变 `Conversation` 的窗口截断语义，不能切断 tool_call/tool_result 配对。

### R8: 测试边界

- 子任务必须可以在没有飞书凭证、没有真实外部 MCP server 的情况下验证。
- 单元测试优先使用 fake/in-memory MCP session 或 factory。
- 可以增加最小 SDK 适配测试，但不要求启动真实外部进程。

## Acceptance Criteria

- [x] `.agents/mcp.yaml` 能从 defaults 和群组路径加载并按 server name 合并，群组同名 server 整体覆盖 defaults。
- [x] 群组配置可用 `enabled: false` 禁用默认 server。
- [x] 不支持或非法 MCP 配置能给出明确错误；空配置不报错。
- [x] MCP stdio server 配置能映射为官方 Python MCP SDK client 参数。
- [x] MCP tools 能被发现并转换为 OpenAI-compatible function tools。
- [x] MCP tool 的 OpenAI-facing 名称采用 `mcp__<server>__<tool>`，不会与 `read_skill` 冲突。
- [x] server/tool 规范化命名冲突会报错，不会静默覆盖或自动改名。
- [x] `BotApp` 能同时向 LLM 提供 `read_skill` 和 MCP tools。
- [x] LLM 返回 MCP tool call 时，`BotApp` 能通过 MCP Manager 执行并把结果作为 `role=tool` 消息追加到 JSONL。
- [x] MCP tool 调用异常会变成模型可读的错误文本，不会中断整条消息处理。
- [x] 现有 `read_skill` tool loop 测试继续通过。
- [x] 新增测试覆盖配置加载、schema 转换、tool 分发、JSONL 持久化。

## Out of Scope

- 飞书 WebSocket live adapter。
- 管理命令，例如 `/mcp list`、`/mcp status`、`/config`。
- MCP HTTP/SSE transport。
- MCP resources、prompts、sampling。
- 独立 `fastmcp` PyPI 包接入。
- 用户级 MCP 权限控制。
- MCP tool allow/deny 策略。
- Skills 脚本执行或通用 `exec` tool。

## Open Questions

当前没有阻塞规划的问题。
