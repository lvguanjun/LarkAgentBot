# Design: MCP Tools 集成

## Architecture

本子任务只扩展现有 transport-independent core，不接入飞书 live transport。

```
IncomingMessage
  -> MessageRouter
  -> Project
      -> AGENTS.md
      -> SkillsRegistry
      -> MCPConfig
      -> Conversation
  -> ToolDispatcher
      -> BuiltinTools(read_skill)
      -> MCPManager(mcp__server__tool)
  -> LLMClient.complete_message(..., tools=...)
  -> Conversation JSONL
  -> MessageSender
```

设计原则：

- 保留现有 `BotApp` bounded tool loop，不创建第二套 LLM/tool loop。
- MCP 作为外部领域能力层，内置 tool 仍只负责机器人本地能力 `read_skill`。
- 所有 MCP 失败都转成 tool result 文本，让 LLM 决定如何回复用户。
- 测试以 fake MCP session/factory 为主，避免依赖真实外部进程。

## 配置模型

新增 MCP 配置加载能力，建议放在 `mcp_manager.py` 或单独的轻量配置类型中。

```python
@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    command: str
    args: list[str]
    env: dict[str, str]
    cwd: str | None

@dataclass(frozen=True)
class MCPConfig:
    servers: dict[str, MCPServerConfig]
```

加载规则：

- `Project.get_mcp_config()` 从 `project.path / ".agents" / "mcp.yaml"` 加载。
- 同时读取 `defaults_dir / ".agents" / "mcp.yaml"` 和群组配置。
- 如果都不存在，返回空 `MCPConfig`。
- 全局默认配置和群组配置按 server name 合并。
- 不同名 server 追加。
- 群组同名 server 整体覆盖默认 server，不做字段级 deep merge。这个规则避免半继承 `command/args/env` 导致启动参数不可预测。
- 群组配置可用 `enabled: false` 显式禁用默认 server。

配置示例：

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
    cwd: ./servers/demo
```

校验规则：

- 顶层必须是 mapping。
- `mcpServers` 缺失时视为空。
- 每个 server 必须是 mapping。
- `enabled` 缺失时默认 `true`；为 `false` 时该 server 不进入最终配置。
- `transport` 缺失时默认 `stdio`；非 `stdio` 在 MVP 报错。
- `command` 必须是非空字符串。
- `args` 必须是字符串列表。
- `env` 必须是字符串到字符串的 mapping。
- `cwd` 必须是字符串或缺失。

环境变量插值：

- MVP 可以支持 `${NAME}` 从当前进程环境读取。
- 缺失环境变量应保留为空字符串或报错，具体实现时优先选择明确报错，避免 server 以错误凭证静默启动。

## MCP Manager

`MCPManager` 对 `BotApp` 暴露与 `BuiltinTools` 类似的接口。

```python
class MCPManager:
    async def start(self) -> None: ...
    def get_tools_for_llm(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> str: ...
    async def shutdown(self) -> None: ...
```

内部状态：

- `config: MCPConfig`
- `connections: dict[str, MCPServerConnection]`
- `tool_index: dict[str, MCPToolRef]`

`MCPServerConnection` 记录：

- server name
- SDK session
- async context manager / exit stack，用于 shutdown
- 原始 tools 列表

生命周期：

- 空配置不启动任何 server。
- `start()` 对每个 stdio server 建立 client session，调用 initialize，再调用 list_tools。
- `shutdown()` 关闭所有 session/context，允许重复调用。
- 如果某个 server 启动失败，MVP 推荐让启动阶段抛出配置/连接错误；tool 调用阶段错误则返回 tool result 文本。

依赖版本：

- 使用官方 Python MCP SDK。
- 本任务不引入独立 `fastmcp` PyPI 包。官方 SDK 内置的 `mcp.server.fastmcp.FastMCP` 是 server helper，不作为本任务的 client 依赖目标。
- 实现时可以根据 SDK 真实 API 升级 `mcp` 版本和锁文件，不把当前 `uv.lock` 中的版本作为硬约束。
- 任何升级都必须通过单元测试和编译检查。

## Tool Name Mapping

OpenAI function 名称采用：

```text
mcp__<server>__<tool>
```

规范化：

- 只允许字母、数字、下划线。
- 非法字符替换为 `_`。
- 名称不能为空。
- 如果规范化后冲突，启动时报错，而不是静默覆盖。
- 不自动追加后缀；OpenAI-facing tool name 必须稳定，方便调试和复现历史。

示例：

- server `github` tool `search_repos` -> `mcp__github__search_repos`
- server `internal-db` tool `query.sql` -> `mcp__internal_db__query_sql`

`MCPManager.call_tool()` 解码 OpenAI-facing name 后定位到真实 server/tool；真实 MCP tool name 保留原始名称调用 SDK。

## Tool Schema 转换

MCP tool:

```python
Tool(
    name="query",
    description="Run readonly query",
    inputSchema={...},
)
```

OpenAI-compatible tool:

```python
{
    "type": "function",
    "function": {
        "name": "mcp__db__query",
        "description": "Run readonly query",
        "parameters": {...},
    },
}
```

转换规则：

- `parameters` 直接使用 MCP `inputSchema`。
- 如果 `inputSchema` 缺失或不是 mapping，使用 `{"type": "object", "properties": {}}`。
- `description` 缺失时使用 `MCP tool <server>/<tool>`。

## Tool Dispatcher

建议新增小型统一分发器，避免 `BotApp` 直接知道所有 tool 类型。

```python
class ToolDispatcher:
    def get_tools_for_llm(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> str: ...
```

组成：

- `BuiltinTools`
- 可选 `MCPManager`

分发规则：

- `read_skill` -> `BuiltinTools.call_tool`
- `mcp__...` -> `MCPManager.call_tool`
- 其他 -> `Error: unknown tool '<name>'`

`BotApp` 改为：

- 构建 `BuiltinTools`
- 构建/获取 `MCPManager`
- 构建 `ToolDispatcher`
- `tools = dispatcher.get_tools_for_llm()`
- tool loop 中调用 `dispatcher.call_tool(...)`

## BotApp 集成策略

为了保持当前测试简单，`BotApp` 可以通过依赖注入接收 MCP manager factory。

```python
class BotApp:
    def __init__(..., mcp_manager_factory: MCPManagerFactory | None = None) -> None: ...
```

处理消息时：

1. 通过 `Project` 获取 MCP 配置。
2. 如果配置为空，只使用内置 tools。
3. 如果配置非空，创建 MCP manager 并 `start()`。
4. 进入现有 bounded tool loop。
5. 在 `finally` 中 `shutdown()` MCP manager。

这个策略每条消息启动/关闭 MCP server，性能不是最优，但生命周期清晰、测试简单、不会引入长期连接缓存和并发清理问题。后续可以在 live transport 阶段优化为按 Project 缓存。

## JSONL

不改 `Conversation` 格式。MCP tool result 仍保存为：

```json
{"role":"tool","tool_call_id":"call-1","content":"..."}
```

如果 MCP 返回多段内容：

- text content 拼接为文本。
- structured content 序列化为 JSON 文本。
- image/audio/resource 暂时用占位说明或 JSON 摘要表示，不做多模态传递。

## Trade-offs

- 选择 `mcp.yaml` 而不是 `mcp.json`：更适合人维护和写注释，且项目已有 YAML 配置栈；代价是不能直接复制部分 JSON-only 客户端配置。
- 选择 stdio-only：覆盖 MVP 的本地/命令式 MCP server 场景；HTTP/SSE 延后可降低生命周期复杂度。
- 选择每消息生命周期：简单可靠，适合当前无 live transport 阶段；代价是后续可能需要优化连接复用。
- 选择 tool 名称命名空间：避免冲突；代价是 LLM 看到的 tool name 比原 MCP tool name 更长。

## Rollback

- MCP 集中在 `mcp_manager.py`、`tools.py`/dispatcher、`project.py`、`app.py`。
- 如果 MCP 集成出现问题，可以保留配置加载和 manager 测试，临时让 `BotApp` 不注入 MCP tools，现有 `read_skill` 路径应不受影响。
