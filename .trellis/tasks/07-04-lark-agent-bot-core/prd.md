# 基础骨架与文本对话闭环

## Goal

为父任务 `06-27-lark-agent-bot` 交付第一个可独立验证的后端切片：建立 Python 包骨架、配置加载、消息路由、Project/Conversation 持久化、AGENTS.md 注入和 OpenAI 兼容文本对话循环。

用户价值：先获得一个本地可测试的核心对话引擎，后续飞书 WebSocket、Skills、MCP 和管理命令可以在稳定边界上逐步接入。

## Background

- 父任务 PRD 要求每个群组/私聊映射为独立 Project，每个话题映射为独立 Conversation：`.trellis/tasks/06-27-lark-agent-bot/prd.md` R3、R9。
- 父任务已决策 MVP 内置 tool 仅 `read_skill`，但本子任务不实现 Skills/tool loop，只保留接口边界以便后续接入。
- 仓库当前没有应用代码；本子任务从零创建 `src/lark_agent/`、配置文件和测试。
- 当前 Trellis Codex 模式是 inline，执行阶段由主会话直接实现和检查，不需要 `implement.jsonl` / `check.jsonl`。

## Requirements

### R1: Python 包与配置骨架

- 创建 `pyproject.toml`，声明 Python 3.11+、运行依赖和测试配置。
- 创建 `src/lark_agent/` 包结构及可导入模块。
- 提供全局配置加载，支持从 YAML 文件读取 Lark、OpenAI 兼容 API、存储路径和对话窗口配置。
- 配置加载必须允许测试传入临时配置路径和临时 data 目录，不依赖真实飞书或 OpenAI 凭证。

### R2: Transport 边界与消息模型

- 提供 `transport/base.py`，定义 `IncomingMessage`、内容分片和 `MessageSender` 协议。
- `IncomingMessage.content` 使用多模态结构，MVP 对图片分片降级为文本占位，但保留 `file_key` 元数据。
- 本子任务不要求真实 `lark-oapi` WebSocket 长连接联调；真实飞书 adapter 留给后续子任务。

### R3: 触发规则

- 实现群聊、私聊和话题激活判断：
  - 私聊总是响应。
  - 群聊主会话必须 @ 机器人。
  - 群聊话题被激活后，同话题后续消息自动响应。
- 话题激活状态必须按 `chat_id + thread_id` 隔离。
- 管理命令只识别并跳过到命令处理边界；具体 `/config`、`/skill`、`/mcp` 行为不在本子任务实现。

### R4: Project 与 AGENTS.md

- 每个 `chat_id` 映射到 `data/groups/<chat_id>/`。
- 支持群组级 `AGENTS.md` 覆盖 `data/defaults/AGENTS.md`。
- 当群组级文件不存在时 fallback 到全局默认；两者都不存在时返回空字符串。

### R5: Conversation 持久化与窗口截断

- 每个 conversation 存储到 `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`。
- 支持追加和读取 OpenAI messages 格式的 JSONL。
- 支持按最近消息数截断，并且不切断 `assistant(tool_calls)` 与后续 `tool` 结果配对。
- 私聊无话题时使用 `chat_id` 作为默认 `thread_id`。

### R6: LLM 文本对话循环

- 提供 OpenAI 兼容客户端封装，支持注入 fake client 做单元测试。
- 首个版本只要求文本回复闭环：system prompt + conversation context + user message -> assistant final text。
- tool loop、`read_skill` 和 MCP tool execution 不在本子任务实现，但接口命名不得阻碍后续扩展。

### R7: 本地应用编排

- 提供应用层函数，将 `IncomingMessage` 经由 router、project、conversation、LLM client 处理后通过 `MessageSender` 回复。
- 本地测试可使用 fake sender 和 fake LLM 验证端到端文本路径。

## Acceptance Criteria

- [ ] `pip install -e .` 后可以导入 `lark_agent`。
- [ ] 配置加载支持 YAML 文件和测试临时路径，不要求真实外部服务凭证。
- [ ] 单元测试覆盖群聊 @ 触发、不 @ 忽略、私聊响应、话题激活后自动响应。
- [ ] 单元测试覆盖 `AGENTS.md` 群组覆盖与默认 fallback。
- [ ] 单元测试覆盖 JSONL history 追加、读取、私聊默认 conversation id。
- [ ] 单元测试覆盖窗口截断不切断 tool_call/tool_result 配对。
- [ ] 单元测试覆盖 fake LLM + fake sender 的文本端到端回复，并验证 user/assistant 消息被持久化。
- [ ] `python -m pytest` 通过。

## Out of Scope

- 真实飞书 WebSocket 长连接和飞书 API 凭证联调。
- Skills 发现、`read_skill` tool 和 reference 文件读取。
- MCP client、MCP tools 发现和执行。
- 管理命令的具体行为。
- 多 provider 切换、流式回复、摘要压缩。
- Docker 沙箱、通用 `read_file`、`exec`、写文件能力。
