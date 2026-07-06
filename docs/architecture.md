# 项目架构说明

本文档用于学习和理解当前代码结构。它不是要求后续开发必须机械套用很多层，而是帮助快速看懂：一条飞书消息如何进入系统、经过哪些类、最后如何回复并保存上下文。

## 一句话概览

当前项目可以理解为：

```text
飞书事件
  -> 飞书适配层转换成内部消息
  -> BotApp 编排完整业务流程
  -> Project / Conversation 准备项目上下文和历史
  -> LLMClient / ToolDispatcher 调模型和工具
  -> 飞书发送层回复用户
  -> Conversation 保存历史
```

最重要的边界是：

```text
BotApp 不直接依赖飞书原始事件或飞书 SDK。
飞书层负责把飞书世界翻译成内部统一模型和协议。
```

## 简化分层

实际理解时先按 4 层看即可：

```text
入口/适配层
  main.py
  transport/base.py
  transport/lark/*

应用业务层
  app.py
  router.py
  commands.py

领域支撑层
  project.py
  conversation.py
  agents_conf.py
  skills.py
  images.py

基础设施层
  llm_client.py
  mcp/*
  config.py
```

这些层不是硬边界。更实用的判断方式是：

```text
外部格式进 Adapter
业务流程进 App / Service
业务概念和规则进 Domain-ish 对象
外部调用进 Infrastructure
```

## 类级别主流程

### 1. 启动装配

入口在 `src/lark_agent/main.py`。

`build_runner()` 负责把对象组装起来：

```text
load_config()
  -> AppConfig

lark.Client
  -> 飞书 SDK client

LarkMessageSender
  -> 发送普通文本

LarkImageDownloader
  -> 下载飞书图片

LarkMessageReactor
  -> 添加/删除 emoji reaction

LarkCardStreamer
  -> 创建、发送、更新、关闭飞书流式卡片

LLMClient
  -> 调 OpenAI-compatible 模型

BotApp
  -> 机器人核心业务流程

LarkWebSocketBotRunner
  -> 飞书 WebSocket 运行器
```

`main.py` 的职责是接线，不负责具体业务处理。

### 2. 飞书事件进入系统

类：`LarkWebSocketBotRunner`

位置：`src/lark_agent/transport/lark/runner.py`

职责：

```text
连接飞书 WebSocket
注册消息事件处理器
收到飞书原始 event
生成 dedupe_key 并去重
调用 LarkMessageEventAdapter 转换消息
异步调用 BotApp.handle_message()
```

核心调用关系：

```text
LarkWebSocketBotRunner.handle_event(event)
  -> adapter.dedupe_key(event)
  -> dedupe_cache.seen_or_mark(dedupe_key)
  -> adapter.to_incoming_message(event)
  -> app.handle_message(message)
```

### 3. 飞书事件转换成内部消息

类：`LarkMessageEventAdapter`

位置：`src/lark_agent/transport/lark/adapter.py`

职责：把飞书原始 event 转成核心层统一认识的 `IncomingMessage`。

飞书消息可能是：

```text
text
post
image
file
audio
media
interactive
location
system
todo
```

适配后统一变成：

```python
IncomingMessage(
    message_id=...,
    chat_id=...,
    chat_type="group" | "p2p",
    sender_id=...,
    content=[TextPart(...), ImagePart(...), MentionPart(...)],
    mentions=[...],
    root_id=...,
    thread_id=...,
    raw_event=event,
)
```

`IncomingMessage` 定义在 `src/lark_agent/transport/base.py`。从这一步开始，核心业务不再处理飞书原始 JSON。

### 4. 进入 BotApp 核心流程

类：`BotApp`

位置：`src/lark_agent/app.py`

入口方法：

```python
async def handle_message(self, message: IncomingMessage) -> str | None:
```

它是一条消息的主业务流程编排者。

主要步骤：

```text
1. MessageRouter 判断是否应该响应
2. ProjectStore 找到当前聊天对应的 Project
3. 如果是管理命令，交给 ManagementCommandHandler
4. 如果是普通对话，添加处理中 reaction
5. 读取 Conversation、AGENTS.md、Skills、MCP 配置
6. 构造当前用户消息
7. 构造 system prompt 和工具列表
8. 调 LLMClient
9. 如果模型请求工具，交给 ToolDispatcher 调用，再继续调模型
10. 用 LarkCardStreamer 或 LarkMessageSender 回复
11. 将本轮 user / assistant / tool 消息保存到 Conversation
12. 标记 thread 已激活
13. 更新 reaction 状态
```

### 5. 消息路由

类：`MessageRouter`

位置：`src/lark_agent/router.py`

职责：

```text
判断消息是否应该回复
判断是否是命令
清理群聊开头的 mention
记录已激活 thread
```

响应规则：

```text
私聊 p2p
  总是响应

群聊 group
  提到机器人时响应

群聊 thread
  如果该 thread 已经被机器人激活，后续消息继续响应

命令
  私聊中以 / 开头即可
  群聊中必须提到机器人，并且清理 mention 后以 / 开头
```

## Project 与 project_key

类：`ProjectStore`、`Project`

位置：`src/lark_agent/project.py`

`ProjectStore` 负责把聊天映射到本地项目目录。`BotApp` 通过 `_project_key()` 选择 key：

```python
def _project_key(message: IncomingMessage) -> str:
    if message.chat_type == "p2p":
        return message.sender_id
    return message.chat_id
```

规则：

```text
私聊 p2p
  使用 sender_id 作为 project_key
  表示“这个用户的个人上下文”

群聊 group
  使用 chat_id 作为 project_key
  表示“这个群的共享上下文”
```

例子：

```text
群聊消息
  chat_type = "group"
  chat_id = "oc_group_a"
  sender_id = "ou_user_1"
  project_key = "oc_group_a"

私聊消息
  chat_type = "p2p"
  chat_id = "oc_private_x"
  sender_id = "ou_user_1"
  project_key = "ou_user_1"
```

最终目录：

```text
data/groups/<project_key>/
```

虽然目录名叫 `groups`，当前实现中私聊也会放在这里，只是 key 用的是 `sender_id`。

## Project 提供的上下文入口

`Project` 表示一个聊天空间的本地上下文，提供：

```text
get_agents_md()
  读取 AGENTS.md

get_skills_registry()
  发现可用 Skills

get_mcp_config()
  读取 MCP 配置

get_conversation(thread_id)
  获取某个 thread 的会话历史
```

对应目录结构：

```text
data/
  defaults/
    AGENTS.md
    .agents/
      skills/
      mcp.yaml

  groups/
    <project_key>/
      AGENTS.md
      .agents/
        skills/
        mcp.yaml
      conversations/
        <thread_id>/
          history.jsonl
```

## 命令流程

类：`ManagementCommandHandler`

位置：`src/lark_agent/commands.py`

当 `MessageRouter.is_command(message)` 为真时，`BotApp` 不走模型流程，而是进入命令处理：

```text
BotApp.handle_message()
  -> MessageRouter.is_command()
  -> ManagementCommandHandler.handle()
  -> MessageSender.send_text()
```

当前命令：

```text
/help
/config
/skill list
/mcp list
/reset
```

## 普通对话流程

普通对话会进入 LLM 流程。

### 1. 准备上下文

`BotApp` 会从 `Project` 读取：

```text
Conversation
  当前 thread 的历史

AGENTS.md
  system prompt 主体

SkillsRegistry
  可用技能列表，以及 read_skill 工具的数据来源

MCPConfig
  当前项目可用 MCP server 配置
```

### 2. 构造用户消息

函数：`build_user_message()`

位置：`src/lark_agent/images.py`

职责：

```text
把 IncomingMessage.content 转成 OpenAI-style user message
如果包含图片，使用 ImageDownloader 下载图片
图片保存到项目 attachments 目录
历史里保存 image_ref
发给模型前再展开成 data URL
```

### 3. 准备工具

类：`BuiltinTools`、`ToolDispatcher`、`MCPManager`

位置：

```text
src/lark_agent/tools.py
src/lark_agent/mcp/manager.py
```

工具分两类：

```text
内置工具
  read_skill

MCP 工具
  mcp__<server>__<tool>
```

`ToolDispatcher` 统一对外暴露：

```text
get_tools_for_llm()
call_tool(name, args)
```

这样 `BotApp` 不需要知道工具到底来自内置能力还是 MCP server。

### 4. 调模型

类：`LLMClient`

位置：`src/lark_agent/llm_client.py`

职责：封装 OpenAI-compatible 调用。

主要方法：

```text
complete_message()
  非流式返回 assistant message

stream_message()
  流式返回文本 delta，并累计 tool call delta
```

`BotApp` 传给模型的主要内容：

```text
system_prompt
  AGENTS.md + Skills 列表

messages
  Conversation.get_context() + 当前用户消息

tools
  BuiltinTools + MCPManager 暴露出来的工具 schema
```

### 5. 工具调用循环

模型可能返回 `tool_calls`。`BotApp` 的处理逻辑是：

```text
调用 LLMClient
  -> 如果没有 tool_calls，得到最终回复
  -> 如果有 tool_calls：
       逐个交给 ToolDispatcher.call_tool()
       将工具结果作为 role=tool 消息追加到 turn_messages
       再次调用 LLMClient
  -> 最多循环 MAX_TOOL_ITERATIONS 次
```

这能支持：

```text
模型先 read_skill 读取技能说明
再根据技能说明继续回答
```

也能支持：

```text
模型调用 MCP 工具
拿到 MCP 结果后继续生成最终回复
```

## 回复用户

回复有两种方式。

### 流式卡片

类：`LarkCardStreamer`

位置：`src/lark_agent/transport/lark/card_streamer.py`

真实运行时 `main.py` 会注入 `card_streamer`，所以普通对话优先走流式卡片：

```text
create_streaming_card()
send_card()
update_card_content()
close_streaming()
```

`BotApp` 会在模型流式输出时不断更新卡片内容。

### 普通文本

类：`LarkMessageSender`

位置：`src/lark_agent/transport/lark/sender.py`

如果没有配置 `card_streamer`，`BotApp` 会用：

```text
send_text()
```

这条路径也方便测试和后续接入不支持卡片的平台。

## 保存历史

类：`Conversation`

位置：`src/lark_agent/conversation.py`

职责：

```text
append()
  追加一条消息到 history.jsonl

clear()
  清空当前 thread 历史

get_full_history()
  读取完整历史

get_context()
  按 max_messages 截取上下文窗口
```

保存路径：

```text
data/groups/<project_key>/conversations/<thread_id>/history.jsonl
```

保存内容包括：

```text
user message
assistant message
assistant tool_calls message
tool result message
```

`Conversation.get_context()` 会尽量避免把 assistant tool_call 和对应 tool response 拆散，避免后续发给模型的上下文不完整。

## 类级别完整链路

```text
main.build_runner()
  -> AppConfig
  -> lark.Client
  -> LarkMessageSender
  -> LarkImageDownloader
  -> LarkMessageReactor
  -> LarkCardStreamer
  -> LLMClient
  -> BotApp
  -> LarkWebSocketBotRunner

LarkWebSocketBotRunner.handle_event()
  -> TTLSeenCache
  -> LarkMessageEventAdapter
  -> IncomingMessage
  -> BotApp.handle_message()

BotApp.handle_message()
  -> MessageRouter
  -> ProjectStore
  -> Project
  -> ManagementCommandHandler        # 命令路径
  -> Conversation                    # 普通对话路径
  -> AgentsConf
  -> SkillsRegistry
  -> MCPConfig
  -> MCPManager
  -> BuiltinTools
  -> ToolDispatcher
  -> LLMClient
  -> LarkCardStreamer / LarkMessageSender
  -> Conversation.append()
```

## 读代码建议

建议按这个顺序阅读：

```text
1. src/lark_agent/main.py
   看对象如何组装

2. src/lark_agent/transport/base.py
   看核心层统一消息模型和协议

3. src/lark_agent/transport/lark/runner.py
   看飞书事件如何进入系统

4. src/lark_agent/transport/lark/adapter.py
   看飞书 event 如何转换成 IncomingMessage

5. src/lark_agent/app.py
   看完整业务主流程

6. src/lark_agent/project.py
   看聊天空间如何映射到本地项目上下文

7. src/lark_agent/conversation.py
   看历史如何保存和截取

8. src/lark_agent/tools.py 和 src/lark_agent/mcp/
   看工具调用如何组织

9. src/lark_agent/llm_client.py
   看模型调用如何封装
```

先抓住三个主角：

```text
LarkWebSocketBotRunner
  负责把飞书事件送进来

LarkMessageEventAdapter
  负责把飞书事件翻译成 IncomingMessage

BotApp
  负责完整业务处理流程
```

其它类基本都是 `BotApp` 在处理过程中调用的协作对象。
