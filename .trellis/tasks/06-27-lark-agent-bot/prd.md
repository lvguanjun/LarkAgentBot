# 飞书聊天机器人 — 支持 Skills / MCP / AGENTS.md

## Goal

构建一个飞书聊天机器人，将每个群组/私聊映射为一个独立的 **Project**（拥有独立的 AGENTS.md、Skills、MCP 配置），每个飞书话题（Thread）映射为该 Project 下的一次独立 **Conversation**。

用户价值：在飞书中获得类似 Antigravity 的 AI 助手体验——每个群可以定制不同的人格、技能和工具，话题内保持完整对话上下文。

## Background

- 飞书提供"话题"（Thread）概念，通过 `root_id` 标识，天然适合作为对话容器
- 飞书 Python SDK `lark-oapi` 支持长连接（WebSocket）和 Webhook 两种消息接收方式
- MCP (Model Context Protocol) 已有成熟的 Python SDK (`mcp`)
- Skills 采用 SKILL.md + YAML frontmatter 标准，三层渐进加载
- `07-04-lark-agent-bot-core` 已归档完成：已交付 Python 包骨架、配置加载、transport-independent 消息模型、路由规则、Project/Conversation 持久化、AGENTS.md fallback、OpenAI 兼容文本对话闭环。
- `07-04-lark-agent-bot-skills` 已归档完成：已交付 Skills 发现、Tier 1 system prompt 注入、安全 `read_skill` 内置 tool、bounded OpenAI-compatible tool loop，以及 user → assistant(tool_calls) → tool → assistant(final) JSONL 持久化链路。
- 当前测试基线：`UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` 通过，26 个测试全部通过。

## Requirements

### R1: 飞书消息收发

- 使用 `lark-oapi` SDK 通过 **WebSocket 长连接**接收消息
- 消息处理层抽象为独立接口，后续添加 Webhook 只需注册路由
- 支持接收文本消息、识别 @提及、解析话题 `root_id`
- 支持发送文本消息、Markdown 消息，回复到指定话题

### R2: 触发规则

| 场景 | 触发条件 |
|------|---------|
| 群聊主会话 | 必须 @机器人 |
| 话题内（已激活） | 自动响应所有消息 |
| 私聊 | 全部响应 |
| 管理指令（群聊） | @机器人 + `/` 前缀 |
| 管理指令（私聊） | `/` 前缀即可 |

- 话题"激活"定义：机器人在该话题内被 @过，或由机器人发起的话题

### R3: 群组即 Project

- 每个群组/私聊拥有独立的配置目录：
  ```
  data/groups/<chat_id>/
    AGENTS.md          # 系统规则 (system prompt)
    config.yaml        # 群组级 LLM 配置（可选，覆盖全局）
    .agents/           # Agent assets
      skills/          # 该群的技能目录
        <skill_name>/
          SKILL.md
      mcp.yaml         # MCP server 配置
  ```
- 全局默认配置在 `data/defaults/` 下，默认 Skills 和 MCP 配置在 `data/defaults/.agents/` 下
- 群组配置未设置的项 fallback 到全局默认

### R4: AGENTS.md 支持

- AGENTS.md 内容作为 system prompt 注入每次 LLM 调用
- 群组级 AGENTS.md 覆盖全局默认
- 纯 Markdown 格式，无需特殊解析

### R5: Skills 支持（只读 / Prompt 注入）

- Skills 是被动的指令+资源包，MVP 不支持脚本执行
- 三层渐进加载（均为只读操作）：
  - Tier 1 (发现)：启动时读取所有 SKILL.md 的 name + description（YAML frontmatter），生成技能列表注入 system prompt
  - Tier 2 (激活)：LLM 通过内置 `read_skill(name)` tool 按需读取完整 SKILL.md body
  - Tier 3 (引用)：LLM 通过 `read_skill(name, file="refs/xxx")` 按需读取 references/ 等附加文件
- SKILL.md 结构：YAML frontmatter (name, description) + Markdown body
- 群组级 skills 目录覆盖/扩展全局 skills
- 遵循 Agent Skills 开放标准，可直接使用开源社区 skills

### R6: MCP 支持

- 使用官方 `mcp` Python SDK 作为 MCP Client
- 通过 `.agents/mcp.yaml` 配置 MCP servers（支持 stdio transport）
- 启动时连接配置的 MCP servers，获取 tools 列表
- 将 MCP tools 转换为 OpenAI function calling 格式注入 LLM
- LLM 返回 tool_calls 时，通过 MCP Client 执行并返回结果
- 权限模型：群组级配置，群内所有人可用配置的工具

### R7: 内置 Tools

- MVP 仅提供 `read_skill` 一个内置 tool
  - `read_skill(name)` → 返回 SKILL.md 完整内容
  - `read_skill(name, file="references/xxx")` → 返回 references 下的文件
- 专用 tool，只接收 skill name，内部解析路径，无路径注入风险
- 域能力（查数据库、调 API 等）全部通过 MCP tools 提供，不内置
- LLM 可用的 tools = 内置 tools + MCP tools

### R8: LLM 对接

- 通过 OpenAI 兼容 API 统一接入（初期单一 provider）
- 全局配置默认模型，群组级可覆盖
- 支持 function calling / tool use

### R9: 对话上下文管理

- 每个话题（Thread）对应一个独立对话，持久化为 JSONL
  ```
  data/groups/<chat_id>/conversations/<thread_id>/
    history.jsonl     # 完整 OpenAI messages 格式
    metadata.json     # 元信息
  ```
- 完整保留 user → assistant(tool_calls) → tool(result) → assistant(final) 链路
- 滑动窗口截断：发送最近 N 条消息或按 token 数截断（如 8k tokens）
- 截断按完整"轮次"进行，不切断 tool_call/tool_result 配对
- 私聊无话题时，使用 `chat_id` 本身作为默认 conversation

## Technical Notes

- Python 3.11+
- 依赖：`lark-oapi`（飞书 SDK）、`mcp`（MCP SDK）、`openai`（LLM 客户端）、`pyyaml`
- 飞书话题通过消息事件的 `root_id` 字段识别
- 长连接使用 `lark.ws.Client`，事件处理使用 `EventDispatcherHandler`

## Acceptance Criteria

- [ ] 机器人启动后能通过 WebSocket 长连接接收飞书消息
- [x] 群聊中 @机器人 能触发回复，不 @ 时不响应（transport-independent core 已验证）
- [x] 话题内被激活后自动响应后续消息（router/app core 已验证）
- [x] 私聊中所有消息都响应（router/app core 已验证）
- [x] 群组拥有独立的 AGENTS.md，内容作为 system prompt 生效
- [x] Skills 能被发现（Tier 1 列表注入 system prompt）
- [x] LLM 能通过 `read_skill` tool 读取 Skill 完整内容和 references
- [ ] MCP tools 能被发现、列举、执行，结果返回给 LLM
- [x] 对话历史正确持久化为 JSONL，包含完整 tool_calls 链路
- [x] 滑动窗口截断后 LLM 仍能正常工作（不切断 tool 配对）
- [ ] `/config` 等管理指令可查看/修改群组配置

## Task Map

- `07-04-lark-agent-bot-core` ✅ archived: first independently verifiable child task. Built the Python package skeleton, local configuration, transport base types, routing rules, Project/Conversation persistence, AGENTS.md fallback, and a fake-LLM text conversation loop. It intentionally excluded live Feishu WebSocket integration, Skills, MCP, and management commands.
- `07-04-lark-agent-bot-skills` ✅ archived: second independently verifiable child task. Built Skills discovery, Tier 1 system prompt injection, the safe `read_skill` built-in tool, and a bounded OpenAI-compatible tool loop that persists user → assistant(tool_calls) → tool → assistant(final). It intentionally excluded live Feishu WebSocket integration, MCP tools, Skills script execution, and management commands.
- `07-04-lark-agent-bot-agents-layout` ✅ complete: lightweight child task that moved Skills discovery and MCP planning paths under each project `.agents/` directory instead of placing them directly in the chat group root.
- Recommended next child task: `lark-agent-bot-mcp`. Scope should cover `.agents/mcp.yaml` loading/fallback, MCP stdio client lifecycle, MCP tool discovery, conversion to OpenAI function tool schemas, dispatching MCP tool calls through the existing tool loop, JSONL persistence of MCP tool results, fake/in-memory MCP tests, and no live Feishu dependency.
- Later child tasks: live Feishu WebSocket adapter, then management commands (`/help`, `/config`, `/skill list`, `/mcp list`, `/reset`) once MCP and live transport boundaries exist.

## Current Implementation Snapshot

- Implemented modules: `config.py`, `transport/base.py`, `router.py`, `project.py`, `conversation.py`, `agents_conf.py`, `skills.py`, `tools.py`, `llm_client.py`, `app.py`.
- Not yet implemented modules: `transport/websocket.py`, `mcp_manager.py`, `commands.py`, `main.py`.
- The existing app can be tested locally with fake `MessageSender` and fake LLM clients; it does not yet run as a live Feishu bot.
- The existing OpenAI-compatible LLM path already supports `tools` and assistant `tool_calls`, which makes MCP the lowest-friction next integration.

## Decisions Log

### D1: 内置 Tools — MVP 专用 `read_skill` ✅ 已决策

- MVP 内置 tool 仅 `read_skill(name, file?)`，不做通用 `read_file`/`exec`/`write_file`
- 专用 tool 而非通用 `read_file` 的原因：project 目录中敏感文件（config.yaml、mcp.yaml、conversations/）占绝大多数，通用 read_file 需白名单 + 路径校验，安全面过大；专用 tool 只接收 skill name，零路径注入风险
- 域能力全部通过 MCP tools 提供
- 参考调研: `research/builtin-tools-comparison.md`

**演进路径**:
- V2: 引入 Docker 沙箱后，切换为通用 `read_file` + `exec`（安全由沙箱保证）
- MVP 阶段无沙箱，用专用 tool 规避安全问题

### D2: Skills 执行 — MVP 不做 ✅ 已决策

- MVP 阶段 Skills 仅做只读 prompt 注入（Tier 1-3 均为读操作）
- Skills 内的 scripts/ 执行需要 `exec` tool + 沙箱，权限不可控，推迟到 V2
- Skills 遵循 Agent Skills 开放标准，不修改标准本身
- 参考调研: `research/agent-sandbox-comparison.md`

### D3: IncomingMessage.content 多模态 ✅ 已决策

- `content: list[ContentPart]`，ContentPart = TextPart | ImagePart
- MVP 不做图片理解，ImagePart 降级为 `[用户发送了一张图片]` 文本传给 LLM
- history JSONL 完整保存 ImagePart 信息（file_key），后续开启 vision 时可回溯
- 飞书 post（富文本）类型拍平为 text+image 序列

---

## Out of Scope

- Skills 脚本执行（`exec` tool + Docker 沙箱，V2 考虑）
- `write_file` / `search` 等内置 tools（按需在后续版本添加）
- Tool allow/deny 权限策略（V2 随 exec 一起考虑）
- Webhook 接入（架构预留，不实现）
- 用户级权限控制（MVP 仅群组级）
- 多 LLM provider 切换（初期单一 OpenAI 兼容）
- 对话摘要压缩（滑动窗口截断即可）
- 飞书卡片消息交互
