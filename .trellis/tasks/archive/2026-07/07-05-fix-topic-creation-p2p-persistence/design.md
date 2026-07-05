# Design: 修复话题创建与 p2p 持久化

## Architecture

本任务修复飞书话题语义在 transport 边界和 app 编排中的信息丢失：

```text
Feishu receive event
  -> LarkMessageEventAdapter(thread_id/root_id)
  -> IncomingMessage
  -> MessageRouter.get_existing_thread_id()
  -> BotApp gathers turn messages
  -> MessageSender.send_text(reply_in_thread intent)
  -> SendResult(thread_id)
  -> Conversation persists under final conversation id
```

核心原则：

- 飞书 SDK 字段解析留在 `transport/lark/`。
- 核心层只依赖 `IncomingMessage`、`MessageSender` 和新的 SDK-independent 发送结果类型。
- `thread_id` 是唯一可信 conversation id；`root_id` / `message_id` 只可用于发送目标和诊断，不作为 history 目录名 fallback。
- p2p 和 group 在话题创建、conversation id 解析、conversation history 写入上使用同一套逻辑。
- p2p 和 group 的 project key 可以不同：group 使用 `chat_id`，p2p 使用 `sender_id`。
- 飞书话题语义依据任务研究文档 `research/feishu-thread-topic.md`。

## Data Contracts

### IncomingMessage

在 `transport/base.py` 扩展：

```python
thread_id: str | None = None
```

含义：

- `thread_id`：飞书真实话题 ID，优先作为内部 conversation id。
- `root_id`：飞书事件中的根消息 ID，保留用于兼容和发送时判断是否已在回复串中。

### SendResult

新增 SDK-independent dataclass：

```python
@dataclass(frozen=True)
class SendResult:
    message_id: str | None = None
    root_id: str | None = None
    thread_id: str | None = None
```

`MessageSender.send_text()` 返回 `SendResult`。Fake sender 可返回空结果；`LarkMessageSender` 从 reply/create response 的 `data` 里提取字段。

### MessageSender.send_text

扩展参数：

```python
reply_in_thread: bool = False
```

语义：

- `reply_to_message_id` 存在时走 reply API。
- `reply_in_thread=True` 时设置飞书 request body 的 `reply_in_thread=true`。
- `reply_in_thread` 不再由 `root_id is not None` 隐式推导。
- 无 `reply_to_message_id` 时仍走 create API；`reply_in_thread` 对 create API 不生效。

## Routing

`MessageRouter.get_existing_thread_id()` 改为：

1. `message.thread_id`

没有 `thread_id` 时返回 `None`，表示当前消息尚无可信 conversation id。线程激活状态也应使用真实 `thread_id`，避免 thread_id/root_id 混用。

## Project Key

`BotApp` 解析 project 时不应无条件使用 `message.chat_id`：

```python
project_key = message.sender_id if message.chat_type == "p2p" else message.chat_id
project = project_store.get_project(project_key)
```

理由：

- p2p 的本质隔离对象是用户，而不是群/会话容器。
- adapter 当前 `sender_id` 优先取 Feishu `open_id`，适合作为稳定用户维度 key。
- 不新增 `data/p2p/` 顶层目录，避免复制 defaults、Skills、MCP 等 project 资源查找规则；p2p 继续使用现有 `data/groups/<project_key>/` 布局。
- 这个分支只决定 project 目录，不决定 topic/conversation 行为。

## App Flow

### Existing Thread

当消息已有 `thread_id`：

1. 使用 resolved thread id 读取 conversation context。
2. 运行 LLM/tool loop。
3. 调用 sender，`reply_to_message_id=message.message_id`，`reply_in_thread=True`。
4. 将本轮 user/assistant/tool 消息写入 resolved thread id 的 history。

### New Topic

当消息通过触发规则进入普通 LLM 回复，且没有 `thread_id`：

1. 使用空上下文运行本轮 LLM/tool loop。
2. 调用 sender，`reply_to_message_id=message.message_id`，`reply_in_thread=True`，让飞书创建话题。
3. 从 `SendResult.thread_id` 获取真实话题 ID。
4. 如果 `SendResult.thread_id` 缺失，fail closed：抛出/记录明确错误，不把本轮消息写入普通 conversation history。
5. 将本轮消息写入最终 conversation id，禁止静默写入 `MAIN_THREAD_ID`、`root_id`、`message_id` 或 p2p `chat_id`。
6. 标记该 topic activated，后续同话题消息无需再次提及即可响应。

为了支持第 3 步，`BotApp` 不应在 LLM/tool loop 中立即 append 到磁盘。它可以先维护本轮 `turn_messages` 列表，并把 `conversation.get_context()` 与 `turn_messages` 拼接后传给 LLM；发送成功并确定 final conversation id 后再一次性写入。

这个流程不按 `chat_type` 分支；p2p 和 group 的区别只来自 project key 选择和路由触发条件，不来自话题创建或 conversation history 写入。

管理命令保持不写普通 conversation history。

## Compatibility

- 这是 active development 项目，不添加旧行为兼容开关。
- 旧 `conversations/main` 数据不迁移。
- 现有 fake sender / fake LLM 测试需要随协议更新。

## Risks

- 如果飞书 reply response 未返回 `thread_id`，首轮新话题不写 history。这样可能丢失一次已发送回复的本地记录，但避免把历史写到错误目录后再和后续真实 `thread_id` 分裂。
- 延迟持久化改变了“LLM 成功但发送失败”时的磁盘记录行为。当前任务以“正确话题持久化”为优先；发送失败不应写入错误 conversation。
