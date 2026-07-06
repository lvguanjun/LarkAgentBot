# 避免 `__init__.py` 承担导入职责

## Goal

将项目约定落成文档：`__init__.py` 不承担聚合导入或 re-export 职责。现有代码中依赖 `lark_agent.mcp`、`lark_agent.transport.lark` 聚合导出的调用点改为从具体模块绝对导入。

## Background

- 当前项目采用 `src/` 布局和绝对导入。
- `src/lark_agent/transport/lark/__init__.py` 聚合导出了 Lark transport 相关类和异常。
- `src/lark_agent/mcp/__init__.py` 聚合导出了 MCP config、manager、naming、session 相关对象。
- 内部代码和测试中存在 `from lark_agent.mcp import ...`、`from lark_agent.transport.lark import ...`，这些导入依赖了 `__init__.py` 的 re-export。

## Requirements

- `__init__.py` 只能用于标识包、包级说明或极少量稳定元信息，不应导入并导出包内实现对象。
- 内部代码和测试必须从对象的所有者模块进行绝对导入。
- 后端规范中必须明确该约定和禁止模式。
- 不引入兼容层，不保留为了旧导入路径服务的 re-export。

## Acceptance Criteria

- [x] `src/lark_agent/mcp/__init__.py` 不再导入或导出 `MCPConfig`、`MCPManager` 等包内对象。
- [x] `src/lark_agent/transport/lark/__init__.py` 不再导入或导出 Lark transport 包内对象。
- [x] 源码和测试中不再出现依赖这些聚合导出的导入语句。
- [x] `.trellis/spec/backend/` 中记录 `__init__.py` 不承担导入职责的项目规范。
- [x] 相关测试通过，至少覆盖当前导入路径调整涉及的测试文件。

## Notes

- 这是轻量任务，PRD-only 足够。
