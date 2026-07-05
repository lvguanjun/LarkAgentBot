# Lark Agent

Lark Agent is a Python package for a Feishu/Lark chat bot core. It maps each
chat to a project directory, keeps each thread as an independent conversation,
and prepares project-scoped AI conversations with AGENTS.md rules, Skills, and
OpenAI-compatible tool calling.

The current implementation includes the transport-independent bot core and a
minimal Feishu WebSocket adapter:

- typed environment configuration through `pydantic-settings` and `.env`
- transport-independent message dataclasses and sender protocol
- group, private chat, mention, command, and activated-thread routing rules
- per-chat project directories with `AGENTS.md` fallback loading
- JSONL conversation history persistence and context windowing
- Skills discovery from local `data/defaults/.agents/skills/` and
  `data/groups/<chat_id>/.agents/skills/`
- Tier 1 Skills list injection into the system prompt
- safe built-in `read_skill(name, file?)` tool for SKILL.md and reference files
- MCP config loading from `.agents/mcp.yaml`, MCP tool discovery, and
  OpenAI-compatible function schema conversion
- bounded OpenAI-compatible tool loop with complete built-in/MCP tool-call
  persistence
- Feishu WebSocket message-event conversion for text, post, and image messages
- Feishu text replies through the `MessageSender` boundary
- ack-first WebSocket event handling with in-process TTL deduplication
- `python -m lark_agent.main` as a minimal live bot entrypoint
- 管理命令：`/help`、`/config`、`/skill list`、`/mcp list`、`/reset`
- injectable fake sender and fake LLM clients for local tests

`/config set` 等运行时配置写入能力仍在规划中。

## Requirements

- Python 3.13+
- `uv` for dependency resolution and test execution

## Setup

Install the package with development dependencies:

```bash
uv sync --extra dev
```

`.env` 是本地开发配置文件，默认被 Git 忽略；`.env.example` 是可提交的配置模板。
`data/` 是本地运行时目录，默认被 Git 忽略，不应提交群组消息、本地 defaults、
群组配置或 MCP 连接配置。

仓库提供可复制的默认资源模板：

```text
templates/
└── defaults/
    └── AGENTS.md
```

初始化本地默认资源时，将模板复制到运行时目录：

```bash
mkdir -p data
cp -R templates/defaults data/defaults
```

运行时数据默认写入 `data/`：

```text
data/
├── defaults/
│   ├── AGENTS.md
│   └── .agents/
│       ├── skills/
│       │   └── <skill_dir>/
│       │       ├── SKILL.md
│       │       └── references/
│       └── mcp.yaml
└── groups/
    └── <chat_id>/
        ├── AGENTS.md
        ├── .agents/
        │   ├── skills/
        │   │   └── <skill_dir>/
        │   │       ├── SKILL.md
        │   │       └── references/
        │   └── mcp.yaml
        └── conversations/
            └── <thread_id>/
                └── history.jsonl
```

## Configuration

应用级配置通过环境变量读取。本地开发时，复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

`pydantic-settings` 会读取当前工作目录下的 `.env`。真实进程环境变量优先于
`.env`，`.env` 优先于代码默认值。

```env
LARK_AGENT_DATA_DIR=data

LARK_AGENT_LARK__APP_ID=cli_xxx
LARK_AGENT_LARK__APP_SECRET=xxx
LARK_AGENT_LARK__BOT_ID=ou_xxx

LARK_AGENT_LLM__API_KEY=sk-xxx
LARK_AGENT_LLM__BASE_URL=
LARK_AGENT_LLM__MODEL=gpt-4.1-mini

LARK_AGENT_CONVERSATION__MAX_MESSAGES=40
```

`LARK_AGENT_` 是项目环境变量前缀；双下划线 `__` 表示嵌套配置层级，例如
`LARK_AGENT_LLM__API_KEY` 对应内部配置 `llm.api_key`。

本地 `data/defaults/AGENTS.md` 会作为默认 system prompt。存在群组级
`data/groups/<chat_id>/AGENTS.md` 时，群组级文件优先生效。

## Run The Live Bot

这一节用于把当前仓库跑成一个真实飞书机器人。当前入口使用飞书 WebSocket
长连接，不需要公网回调 URL；进程必须持续运行，断开后机器人就无法接收新消息。

### 1. 创建飞书应用

在飞书开放平台创建企业自建应用，并完成这些配置：

1. 在「凭证与基础信息」中复制 `App ID` 和 `App Secret`。
2. 在「事件订阅」中选择 WebSocket 长连接模式。
3. 订阅消息接收事件 `im.message.receive_v1`。当前代码注册的是
   `p2.im.message.receive_v1` 处理器。
4. 为应用开通接收消息和发送消息所需权限。权限名称会随飞书后台展示调整，
   原则上至少需要读取用户发给机器人的消息、向会话发送消息、回复消息的权限。
5. 发布或安装应用到目标企业，并把机器人加入需要测试的群聊。

如果机器人只在私聊可用但群聊无响应，通常是应用没有进群、没有订阅消息事件，
或 `LARK_AGENT_LARK__BOT_ID` 没有和事件里的 mention ID 对上。

### 2. 填写本地配置

复制 `.env.example` 为 `.env`，再替换其中的占位值：

```bash
cp .env.example .env
```

字段说明：

- `LARK_AGENT_DATA_DIR`：运行时数据目录，默认 `data`。
- `LARK_AGENT_LARK__APP_ID`：飞书开放平台应用的 `App ID`。
- `LARK_AGENT_LARK__APP_SECRET`：飞书开放平台应用的 `App Secret`，不要提交到 Git。
- `LARK_AGENT_LARK__BOT_ID`：机器人在消息事件 `mentions[].id` 中出现的 ID。优先使用
  `open_id`；如果你的租户事件实际返回 `user_id` 或 `union_id`，就填对应值。
- `LARK_AGENT_LLM__API_KEY`：OpenAI-compatible API key；为空时真实对话无法调用模型。
- `LARK_AGENT_LLM__BASE_URL`：兼容 OpenAI SDK 的自定义网关地址；使用默认 OpenAI 地址时留空。
- `LARK_AGENT_LLM__MODEL`：模型名，默认 `gpt-4.1-mini`。
- `LARK_AGENT_CONVERSATION__MAX_MESSAGES`：每个 conversation 的上下文消息窗口。

第一次确认 `bot_id` 时，可以先启动机器人，在群里提及机器人并发送 `/config`。
如果没有响应，临时查看事件日志或在调试环境打印 `mentions[].id`，把其中和机器
人对应的 ID 填入 `LARK_AGENT_LARK__BOT_ID`。

### 3. 初始化运行时目录

本地运行前准备默认 system prompt 和数据目录：

```bash
mkdir -p data
cp -R templates/defaults data/defaults
```

`data/` 默认被 Git 忽略，用来保存群组目录、conversation history、默认
`AGENTS.md`、Skills 和 MCP 配置。不要把生产聊天记录或密钥提交到仓库。

### 4. 启动机器人

安装依赖后启动 WebSocket 长连接：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m lark_agent.main
```

请在包含 `.env` 的项目目录中启动。生产部署可以不使用 `.env`，直接注入同名真实
环境变量。

启动时如果缺少 `LARK_AGENT_LARK__APP_ID`、`LARK_AGENT_LARK__APP_SECRET` 或
`LARK_AGENT_LARK__BOT_ID`，进程会直接报错退出。

### 5. 验证

推荐按这个顺序验证：

1. 私聊机器人发送 `/help`，确认机器人能收到消息并回复。
2. 私聊机器人发送 `/config`，确认 `lark.*`、`llm.*` 和 `conversation.*` 摘要正确。
3. 在群聊中提及机器人并发送 `/help`，确认群聊 mention 路由生效。
4. 在群聊中提及机器人发送普通问题，确认 LLM 能正常返回。
5. 在同一群聊话题或回复串中继续发消息，确认 conversation history 写入
   `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`。

### 6. 常见问题

- 进程启动后没有任何响应：确认飞书后台使用 WebSocket 事件订阅、应用已发布或
  安装到企业、机器人已加入目标群聊。
- 群聊不响应但私聊响应：确认群消息里实际提及了机器人，并检查 `LARK_AGENT_LARK__BOT_ID`
  是否出现在事件 `mentions[].id` 中。
- `/help` 可用但普通问题失败：通常是 `LARK_AGENT_LLM__API_KEY`、
  `LARK_AGENT_LLM__BASE_URL` 或模型名配置不正确。
- 回复消息接口报权限错误：回到飞书开放平台补齐发送/回复消息权限，并重新发布或
  安装应用。
- 重启后重复处理旧事件：当前只做进程内 TTL 去重，跨进程或重启后的持久化事件
  去重仍在 `TODO.md` 的暂不做列表中。

旧版 `config.yaml` 不再作为应用级配置入口。手动迁移时，将旧字段改写为同名环境
变量，例如 `lark.app_id` 改为 `LARK_AGENT_LARK__APP_ID`，
`llm.api_key` 改为 `LARK_AGENT_LLM__API_KEY`。

## Skills

Skills are read-only instruction packages. Each skill lives in a directory with
a `SKILL.md` file containing YAML frontmatter:

```markdown
---
name: example_skill
description: Use this when the assistant needs example behavior.
---

# Example Skill

Skill instructions go here.
```

全局 Skills 位于本地 `data/defaults/.agents/skills/`。群组级 Skills 位于
`data/groups/<chat_id>/.agents/skills/`，同名时覆盖全局 Skills。模型会先看到
skill name 和 description，再通过 `read_skill` 读取完整说明或 `references/`
下的文件。

## 管理命令

管理命令不会调用 LLM，也不会写入普通对话历史。群聊中仍遵守路由规则：需要提及
机器人且消息文本以 `/` 开头；私聊中 `/` 开头的命令会直接响应。

- `/help`：查看支持的管理命令。
- `/config`：查看安全配置摘要。敏感值只显示是否已配置，不输出原文。
- `/skill list`：查看当前聊天可用 Skills 和 discovery error 摘要。
- `/mcp list`：查看合并后的 MCP server 配置摘要。该命令不启动 MCP server，
  也不做 tool discovery；env 只显示 key，不输出 value。
- `/reset`：清空当前 chat/thread 的 conversation history，不影响同一 chat 下
  其他 thread。

`/config set` 暂未支持，需要先设计可写字段白名单和安全边界。

## Tests

Run the full test suite:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
```

Compile-check the package:

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

Async tests are supported through `pytest-asyncio` with
`asyncio_mode = "auto"` in `pyproject.toml`, so `async def test_...` functions
can run directly.
