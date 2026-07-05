# Design: 飞书聊天机器人

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                  Lark Agent Bot                  │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────┐    ┌──────────────┐               │
│  │ Transport │───▶│ MessageRouter│               │
│  │  Layer    │    │  (触发规则)   │               │
│  └──────────┘    └──────┬───────┘               │
│   WebSocket             │                        │
│   (Webhook*)            ▼                        │
│              ┌──────────────────┐                │
│              │  ConversationMgr │                │
│              │  (上下文管理)     │                │
│              └────────┬─────────┘                │
│                       │                          │
│         ┌─────────────┼─────────────┐            │
│         ▼             ▼             ▼            │
│  ┌───────────┐ ┌───────────┐ ┌──────────┐       │
│  │ AgentsConf│ │ SkillsLdr │ │ MCPMgr   │       │
│  │ (系统规则) │ │ (技能加载) │ │ (工具管理)│       │
│  └─────┬─────┘ └─────┬─────┘ └────┬─────┘       │
│        └─────────────┼─────────────┘             │
│                      ▼                           │
│              ┌───────────────┐                   │
│              │   LLMClient   │                   │
│              │ (OpenAI API)  │                   │
│              └───────────────┘                   │
│                                                  │
│  ┌──────────────────────────────────────┐        │
│  │         ProjectStore (文件系统)       │        │
│  │  data/groups/<chat_id>/              │        │
│  │    AGENTS.md | .agents/ | conversations/ │    │
│  │    conversations/<thread_id>/        │        │
│  └──────────────────────────────────────┘        │
└─────────────────────────────────────────────────┘
```

## Package Structure

```
lark_agent/
├── pyproject.toml
├── config.yaml                 # 全局配置
├── templates/
│   └── defaults/               # 可提交的默认资源模板
│       ├── AGENTS.md
│       └── .agents/
│           ├── skills/
│           └── mcp.yaml
├── data/                       # 本地运行时目录，整体不进 Git
│   ├── defaults/               # 本地全局默认配置，由 templates/defaults/ 初始化
│   │   ├── AGENTS.md
│   │   └── .agents/
│   │       ├── skills/
│   │       └── mcp.yaml
│   └── groups/                 # 群组数据（运行时生成）
│       └── <chat_id>/
│           ├── AGENTS.md
│           ├── config.yaml
│           ├── .agents/
│           │   ├── skills/
│           │   └── mcp.yaml
│           └── conversations/
├── src/
│   └── lark_agent/
│       ├── __init__.py
│       ├── main.py             # 入口
│       ├── config.py           # 全局配置加载
│       ├── transport/          # 消息传输层
│       │   ├── __init__.py
│       │   ├── base.py         # 抽象接口
│       │   └── websocket.py    # 飞书 WebSocket 长连接
│       ├── router.py           # 消息路由 & 触发规则
│       ├── project.py          # 群组 Project 管理
│       ├── conversation.py     # 对话上下文管理
│       ├── agents_conf.py      # AGENTS.md 加载
│       ├── skills.py           # Skills 发现 & 元信息加载（只读）
│       ├── tools.py            # 内置 tools（MVP: read_skill）
│       ├── mcp_manager.py      # MCP Client 管理
│       ├── llm_client.py       # LLM 调用（含 tool loop）
│       └── commands.py         # 斜杠命令处理
```

Version-control boundary:

- `data/` is local runtime state and must be ignored by Git.
- `templates/defaults/` is the committed, de-identified template source for initializing local `data/defaults/`.
- Runtime code continues to read defaults from `data/defaults/`; templates are an operator/developer bootstrap artifact, not a second runtime lookup path.

Current code status:

- Present: `config.py`, `transport/base.py`, `router.py`, `project.py`, `conversation.py`, `agents_conf.py`, `skills.py`, `tools.py`, `llm_client.py`, `app.py`.
- Missing and still planned: `transport/websocket.py`, `mcp_manager.py`, `commands.py`, `main.py`.
- The current transport boundary is intentionally live-adapter-free: tests exercise the app with fake senders and fake LLM clients.
- The current tool loop already handles OpenAI-compatible assistant `tool_calls`; MCP should attach to this existing dispatch path instead of creating a parallel LLM loop.

## Component Design

### 1. Transport Layer (`transport/`)

抽象接口，解耦消息来源：

```python
# base.py
class IncomingMessage:
    """飞书消息的统一表示"""
    message_id: str
    chat_id: str          # 群组/私聊 ID
    chat_type: str        # "group" | "p2p"
    sender_id: str        # 发送者 ID
    root_id: str | None   # 话题根消息 ID（None = 主会话）
    content: str          # 纯文本内容
    mentions: list[str]   # 被 @的 user/bot ID 列表
    raw_event: Any        # 原始事件数据

class MessageSender(Protocol):
    """发送消息的抽象接口"""
    async def send_text(self, chat_id: str, text: str, 
                         root_id: str | None = None) -> None: ...
    async def send_markdown(self, chat_id: str, md: str,
                             root_id: str | None = None) -> None: ...
    async def reply(self, message_id: str, text: str) -> None: ...
```

WebSocket 实现使用 `lark-oapi` 的 `lark.ws.Client`。Webhook 实现只需另写一个适配器注册到 HTTP 路由。

### 2. MessageRouter (`router.py`)

根据触发规则决定是否处理消息：

```python
class MessageRouter:
    async def should_respond(self, msg: IncomingMessage) -> bool:
        """触发规则判断"""
        # 私聊: 始终响应
        if msg.chat_type == "p2p":
            return True
        # 群聊: 必须 @机器人
        if self.bot_id in msg.mentions:
            return True
        # 话题内: 检查是否已激活
        if msg.root_id and self.is_thread_activated(msg.chat_id, msg.root_id):
            return True
        return False
```

### 3. Project (`project.py`)

管理群组级配置，延迟加载：

```python
class Project:
    """一个群组/私聊对应一个 Project"""
    chat_id: str
    base_path: Path          # data/groups/<chat_id>/
    
    def get_agents_md(self) -> str: ...
    def get_skills_registry(self) -> SkillsRegistry: ...
    def get_mcp_config(self) -> MCPConfig: ...
    def get_llm_config(self) -> LLMConfig: ...  # fallback 到全局
    def get_conversation(self, thread_id: str) -> Conversation: ...
```

配置 fallback 链：群组配置 → 全局默认配置。

### 4. Conversation (`conversation.py`)

对话上下文管理，核心数据结构：

```python
class Conversation:
    thread_id: str
    history_path: Path   # history.jsonl
    
    def append(self, message: dict) -> None:
        """追加消息到 JSONL（完整格式，含 tool_calls）"""
    
    def get_context(self, max_tokens: int = 8000) -> list[dict]:
        """获取发送给 LLM 的上下文（滑动窗口截断）
        截断按完整轮次，不切断 tool_call/tool_result 配对"""
    
    def get_full_history(self) -> list[dict]:
        """获取完整历史"""
```

### 5. Skills (`skills.py`)

只读 prompt 注入，不执行脚本。Tier 2/3 的动态加载通过内置 `read_skill` tool 完成，
LLM 根据 Tier 1 的技能列表自行决定何时读取完整 Skill 内容。

```python
@dataclass
class SkillMeta:
    """Tier 1: 仅元信息"""
    name: str
    description: str
    skill_dir: Path  # skills/<name>/ 的绝对路径（内部使用，不暴露给 LLM）

class SkillsRegistry:
    skills: dict[str, SkillMeta]  # name → meta
    
    def discover(self, skills_dirs: list[Path]) -> None:
        """扫描目录，解析所有 SKILL.md 的 frontmatter
        支持多目录（群组 skills + 全局默认 skills），群组优先"""
    
    def get_system_prompt_fragment(self) -> str:
        """生成 skills 列表描述（name + description），注入 system prompt
        LLM 通过 read_skill(name) 读取完整内容"""
    
    def read_skill(self, name: str, file: str | None = None) -> str:
        """读取 skill 内容
        file=None → 返回 SKILL.md 完整内容
        file="references/xxx" → 返回 references 下的文件"""
```

### 6. MCP Manager (`mcp_manager.py`)

MCP Client 生命周期管理：

```python
class MCPManager:
    servers: dict[str, MCPServerConnection]
    
    async def start(self, config: MCPConfig) -> None:
        """启动所有配置的 MCP servers，建立连接"""
    
    def get_tools_for_llm(self) -> list[dict]:
        """获取所有 tools 的 OpenAI function 格式描述"""
    
    async def call_tool(self, server_name: str, 
                         tool_name: str, args: dict) -> str:
        """执行 tool 调用"""
    
    async def shutdown(self) -> None:
        """关闭所有 MCP server 连接"""
```

Recommended next implementation boundary:

- Add `mcp_manager.py` behind a small app-facing interface that mirrors `BuiltinTools`:
  - `get_tools_for_llm() -> list[dict]`
  - `call_tool(name: str, args: dict) -> str`
- Keep MCP tool names collision-safe. If OpenAI-facing names need namespacing, use a stable prefix such as `mcp__<server>__<tool>` and decode it inside `MCPManager`.
- Load MCP config from group `data/groups/<chat_id>/.agents/mcp.yaml` with fallback to `data/defaults/.agents/mcp.yaml`.
- Start with stdio transport only, matching the parent PRD. Defer HTTP/SSE and per-user permissioning.
- Tests should use fake MCP server/session objects and should not require spawning real external processes for the core behavior.

### 7. Built-in Tools (`tools.py`)

内置 tool 注册与执行。MVP 仅 `read_skill`（专用 tool，零路径注入风险）。
V2 引入 Docker 沙箱后再切换为通用 `read_file` + `exec`。

```python
class BuiltinTools:
    """内置 tools 管理"""
    skills_registry: SkillsRegistry
    
    def get_tools_for_llm(self) -> list[dict]:
        """返回内置 tools 的 OpenAI function 格式描述"""
        return [{
            "type": "function",
            "function": {
                "name": "read_skill",
                "description": "Read a skill's full instructions or reference files. "
                               "Call with just the name to get the skill's main content (SKILL.md). "
                               "Add the file parameter to read a specific reference file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the skill (from the available skills list)"
                        },
                        "file": {
                            "type": "string",
                            "description": "Optional. Relative path to a reference file within the skill "
                                           "(e.g. 'references/api-docs.md')"
                        }
                    },
                    "required": ["name"]
                }
            }
        }]
    
    async def call_tool(self, name: str, args: dict) -> str:
        """执行内置 tool 调用"""
        if name == "read_skill":
            return self.skills_registry.read_skill(
                args["name"], args.get("file")
            )
        raise ValueError(f"Unknown built-in tool: {name}")
```

Current implementation note:

- `BuiltinTools` is implemented and returns structured error text for invalid tool calls instead of raising into the message handler.
- `BotApp` currently dispatches only built-in tools. The MCP child task should introduce a combined tool dispatcher so built-in and MCP tools share one bounded loop and one JSONL persistence path.

安全模型：LLM 只传 skill name，路径解析在 `SkillsRegistry.read_skill()` 内部完成。
`read_skill` 内部对 `file` 参数做 `is_relative_to` 检查，防止 `../../` 逃逸出 skill 目录。
不暴露任何文件系统路径给 LLM，无法访问 config.yaml / mcp.yaml / conversations/。

### 8. LLM Client (`llm_client.py`)

核心调用循环。tools 来源 = 内置 tools + MCP tools。

```python
class LLMClient:
    async def chat(self, 
                    system_prompt: str,
                    messages: list[dict],
                    tools: list[dict] | None,
                    builtin_tools: BuiltinTools | None,
                    mcp_manager: MCPManager | None) -> str:
        """
        完整的 chat 循环：
        1. 发送 messages + tools 给 LLM
        2. 如果返回 tool_calls:
           - 内置 tool → BuiltinTools.call_tool()
           - MCP tool → MCPManager.call_tool()
        3. 结果追加 → 重新调用 LLM
        4. 重复直到 LLM 返回纯文本
        5. 返回最终文本回复
        """
```

### 9. Commands (`commands.py`)

斜杠命令处理：

```python
COMMANDS = {
    "/config": "查看当前群组配置",
    "/config set <key> <value>": "修改配置",
    "/skill list": "列出可用 skills",
    "/skill info <name>": "查看 skill 详情",
    "/mcp list": "列出 MCP tools",
    "/mcp status": "查看 MCP server 连接状态",
    "/help": "显示帮助",
    "/reset": "重置当前话题的对话历史",
}
```

## Data Flow

### 正常对话流程

```
飞书用户发消息
  → Transport 收到事件
  → Router 判断触发规则 (should_respond)
  → 识别 chat_id + root_id
  → ProjectStore 获取/创建 Project
  → Project 获取/创建 Conversation
  → 组装上下文:
      system_prompt = AGENTS.md + Skills 列表描述
      messages = Conversation.get_context()
      tools = BuiltinTools.get_tools_for_llm() [read_skill] + MCPManager.get_tools_for_llm()
  → LLMClient.chat() (可能包含多轮 tool 调用: read_skill 或 MCP tool)
  → 所有消息追加到 Conversation (history.jsonl)
  → Transport 发送最终回复到飞书 (指定 root_id 保持话题内)
```

### 管理指令流程

```
@机器人 /skill list
  → Router 识别为管理指令
  → Commands 处理器匹配并执行
  → 直接返回结果（不经过 LLM）
```

## Key Trade-offs

1. **文件系统 vs 数据库**：选择文件系统，简单直观，与 skill/AGENTS.md 文件天然兼容，代价是不适合超大规模
2. **滑动窗口 vs 摘要压缩**：选择滑动窗口，实现简单，代价是丢失早期上下文
3. **群组级权限 vs 用户级权限**：选择群组级，MVP 够用，代价是不能细粒度控制
4. **同步 tool loop vs 流式**：MVP 用同步 loop，整体回复，代价是长 tool chain 时用户等待久
5. **专用 tool (read_skill) vs 通用 tool (read_file)**：MVP 选择专用 `read_skill`——project 目录中敏感文件占多数（config/mcp/conversations），无沙箱下通用 read_file 安全面过大；V2 引入 Docker 沙箱后再切通用 tool
6. **内置 tools + MCP 分层 vs 全 MCP**：内置 tool 处理 agent 自身能力（读 skill），MCP 处理域能力（外部 API/数据库）；清晰分层，MCP server 不需要访问 bot 本地文件系统
