# 重组 MCP 和飞书 transport 模块

## Goal

优化当前 Python 包结构，把已经明显增长的 MCP 相关代码和飞书 transport 适配代码收进更清晰的子包边界，同时保持现有行为不变。

用户价值：后续继续开发管理命令、更多 transport 或 MCP 能力时，代码位置更直观，核心 bot 编排层不被外部 SDK 和协议细节拖重。

## Background

- 当前项目已经采用 `src/lark_agent/` 的 src layout。
- 大多数模块仍然较小且职责单一，暂不需要全项目分层重构。
- `src/lark_agent/mcp_manager.py` 已增长到 300 行以上，混合了 MCP 配置解析、命名规范、session 生命周期、tool schema 暴露和 result 格式化。
- `src/lark_agent/transport/websocket.py` 已增长到 300 行以上，混合了飞书消息发送、事件转换、去重缓存和 WebSocket runner。
- 这次调整是结构整理，不改变业务行为、不新增功能。

## Requirements

- R1: 新建 `lark_agent.mcp` 子包，承载 MCP 配置、命名、session、manager 和 result 格式化等职责。
- R2: 新建 `lark_agent.transport.lark` 子包，承载飞书/Lark SDK 相关 sender、event adapter、dedupe cache 和 WebSocket runner。
- R3: `app.py`、`project.py`、`main.py`、测试等调用方应改用新的模块边界。
- R4: 删除旧的大文件入口 `lark_agent.mcp_manager` 和 `lark_agent.transport.websocket`，避免结构调整后仍有两个入口并存。
- R5: 不移动仍然清晰的小模块，例如 `config.py`、`router.py`、`conversation.py`、`skills.py`、`tools.py`。
- R6: 不改变运行时行为、配置格式、数据目录格式、JSONL 历史格式或飞书/MCP 对外契约。

## Acceptance Criteria

- [x] MCP 相关 public symbols 可从新的 `lark_agent.mcp` 包导入。
- [x] 飞书 transport public symbols 可从新的 `lark_agent.transport.lark` 包导入。
- [x] 源码和测试不再从 `lark_agent.mcp_manager` 或 `lark_agent.transport.websocket` 导入。
- [x] 现有测试全部通过。
- [x] `src/` 可通过 compile check。

## Notes

- 这是轻量结构任务，PRD-only 足够。
- 目标是小步拆分增长点，不做全项目架构重命名。
