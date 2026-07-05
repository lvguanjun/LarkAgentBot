# Implementation Plan: MCP Tools 集成

## Preconditions

- 父任务：`06-27-lark-agent-bot`。
- 依赖已完成：
  - `07-04-lark-agent-bot-core`
  - `07-04-lark-agent-bot-skills`
  - `07-04-lark-agent-bot-agents-layout`
- 当前工作流为 inline mode，跳过 `implement.jsonl` / `check.jsonl` curation。
- 开始实现前需要用户 review 并批准，然后运行 `task.py start 07-05-lark-agent-bot-mcp`。

## Ordered Checklist

1. 读取开发规范 ✅
   - 使用 `trellis-before-dev`。
   - 重点读取 backend spec、质量规范、代码复用指南。

2. MCP 配置加载 ✅
   - 新增 `MCPServerConfig` / `MCPConfig`。
   - 实现 `.agents/mcp.yaml` 加载。
   - 实现 defaults + 群组按 server name 合并。
   - 实现群组同名 server 整体覆盖 defaults。
   - 实现 `enabled: false` 禁用默认 server。
   - 在 `Project` 上增加 `get_mcp_config()`。
   - 增加配置加载测试：群组覆盖、defaults 合并、禁用默认 server、空配置、非法配置。

3. MCP tool name 和 schema 转换 ✅
   - 实现 server/tool name 规范化。
   - 实现 `mcp__<server>__<tool>` 映射。
   - 实现 MCP tool -> OpenAI-compatible function tool 转换。
   - 增加冲突和 schema fallback 测试。

4. MCP Manager ✅
   - 新增 `src/lark_agent/mcp_manager.py`。
   - 用官方 Python MCP SDK 实现 stdio client lifecycle。
   - 不引入独立 `fastmcp` PyPI 包。
   - 允许根据实际 SDK API 更新 `mcp` 依赖版本和锁文件。
   - 提供 fake session/factory 注入点，避免单元测试启动真实进程。
   - 实现 tool result 文本化和异常文本化。

5. 统一 Tool Dispatcher ✅
   - 新增或扩展 `tools.py`，提供 `ToolDispatcher`。
   - 合并 `BuiltinTools` 和 MCP tools。
   - 未知 tool 返回错误文本。
   - 保持 `BuiltinTools` 原有行为不变。

6. BotApp 集成 ✅
   - 在 `BotApp` 中接入 MCP 配置和 manager factory。
   - 空 MCP 配置时不启动 MCP manager。
   - 非空配置时在消息处理生命周期内 start/shutdown。
   - tool loop 改为通过 `ToolDispatcher.call_tool()` 分发。
   - 确保 `finally` 中清理 MCP manager。

7. JSONL 和端到端测试 ✅
   - 增加 fake MCP tool call 测试。
   - 验证 user -> assistant(tool_calls) -> tool -> assistant(final) 完整写入 JSONL。
   - 验证 MCP 调用错误会写入 tool result，并允许 LLM 继续 final 回复。
   - 确认原有 `read_skill` 测试继续通过。

8. 依赖和验证 ✅
   - 如需升级 MCP SDK，更新 `pyproject.toml` 和 `uv.lock`。
   - 不引入与本任务无关的依赖升级。
   - 运行完整验证命令。

## Validation Commands

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
git status --short
```

如实现需要更新依赖：

```bash
UV_CACHE_DIR=.uv-cache uv lock
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
```

## Risky Files

- `src/lark_agent/app.py`：不要破坏现有 `read_skill` bounded tool loop 和 JSONL 顺序。
- `src/lark_agent/project.py`：路径 fallback 必须保持 `.agents/` 布局。
- `src/lark_agent/tools.py`：新增 dispatcher 时避免改变 `BuiltinTools` 现有契约。
- `src/lark_agent/mcp_manager.py`：SDK lifecycle 和 async context cleanup 是主要风险。
- `pyproject.toml` / `uv.lock`：只在 MCP SDK API 需要时更新。

## Test Plan

- `test_mcp_config_loads_group_yaml_before_defaults`
- `test_mcp_config_returns_empty_when_missing`
- `test_mcp_config_rejects_non_stdio_transport`
- `test_mcp_tool_schema_converts_to_openai_function`
- `test_mcp_tool_names_are_namespaced_and_collision_checked`
- `test_tool_dispatcher_routes_builtin_and_mcp_tools`
- `test_app_runs_mcp_tool_loop_and_persists_full_chain`
- `test_app_turns_mcp_tool_error_into_tool_result`

## Ready Check Before Start

- [x] 子任务已创建并挂到父任务。
- [x] 子任务依赖已显式写入。
- [x] 范围限定为 MCP tools，排除 live Feishu 和管理命令。
- [x] 配置格式决策为 `.agents/mcp.yaml`。
- [x] 配置合并决策为 defaults + 群组按 server name 合并，群组同名整体覆盖，支持 `enabled: false`。
- [x] SDK 决策为官方 `mcp` Python SDK，不引入独立 `fastmcp` PyPI 包。
- [x] MCP 依赖版本策略已更新：允许按实际情况升级。
- [x] 用户 review 规划产物并批准进入实现。
- [x] 运行 `task.py start 07-05-lark-agent-bot-mcp`。
