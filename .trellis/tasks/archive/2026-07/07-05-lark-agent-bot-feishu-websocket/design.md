# Design: 飞书 WebSocket 长连接接入

## Architecture

本任务只新增 live transport 层和最小启动装配，不改变现有核心链路：

```text
lark.ws.Client
  -> EventDispatcherHandler.register_p2_im_message_receive_v1
  -> LarkMessageEventAdapter.to_incoming_message(...)
  -> BotApp.handle_message(...)
  -> LarkMessageSender.send_text(...)
  -> client.im.v1.message.areply/acreate
```

边界原则：

- `BotApp` 继续只接收 `IncomingMessage`，只依赖 `MessageSender`。
- WebSocket adapter 不读取 AGENTS.md、Skills、MCP，也不实现触发规则。
- 飞书 SDK 对象隔离在 `transport/websocket.py` 和 `main.py` 中，便于用 fake SDK 对象测试。

## Components

### `transport/websocket.py`

建议包含以下公开对象：

- `LarkMessageSender`
  - 实现 `MessageSender`。
  - 构造时接收 `lark.Client` 或最小 fake-compatible message API。
  - `send_text(...)` 负责构造 `ReplyMessageRequest` 或 `CreateMessageRequest`。

- `LarkMessageEventAdapter`
  - 纯转换逻辑：`to_incoming_message(event: P2ImMessageReceiveV1) -> IncomingMessage | None`。
  - 私有 helper 解析 text/post/image content JSON。
  - 不调用网络，不调用 `BotApp`。

- `LarkWebSocketBotRunner`
  - 构造 `EventDispatcherHandler`。
  - 将 SDK 同步事件回调桥接到 `BotApp.handle_message()`。
  - 构造并启动 `lark.ws.Client`。
  - 事件回调必须 ack-first：同步回调只做转换和后台 task 投递，然后立即返回，让 SDK 尽快写回事件响应帧。

### `main.py`

最小启动流程：

1. `load_config("config.yaml")`
2. 校验 `lark.app_id`、`lark.app_secret`、`lark.bot_id`
3. 构造 `lark.Client.builder().app_id(...).app_secret(...).build()` 作为 OpenAPI sender client
4. 构造 `LarkMessageSender`
5. 构造 `LLMClient(config.llm)`
6. 构造 `BotApp(config, sender=..., llm_client=...)`
7. 构造并启动 `LarkWebSocketBotRunner`

## Message Conversion

### text

飞书 text content 通常是 JSON 字符串，MVP 只依赖 `text` 字段：

```json
{"text":"hello"}
```

转换为：

```python
[TextPart("hello")]
```

### image

飞书 image content 使用 `image_key` 或兼容字段。转换为：

```python
[ImagePart(file_key=image_key)]
```

### post

post content 按富文本结构中的元素顺序拍平：

- `tag == "text"`：取 `text`
- `tag == "a"`：优先取文本；链接 URL 不单独保真
- `tag == "at"`：保留展示文本或 key
- `tag == "img"` / image-like element：取 `image_key` / `file_key` 生成 `ImagePart`
- 其他 tag：忽略或保留可读文本字段

如果解析失败，返回 `None` 并记录错误；不把非法 JSON 注入 LLM。

## Mentions and IDs

`mentions` 转换为字符串列表，收集以下字段中存在的值：

- `mention.id.open_id`
- `mention.id.user_id`
- `mention.id.union_id`

这样 `config.lark.bot_id` 可以配置为实际部署环境中最稳定的 ID。README 后续应说明推荐使用 bot open_id。

`sender_id` 同样优先使用 `sender.sender_id.open_id`，再 fallback 到 `user_id` / `union_id`。

## Reply Strategy

`BotApp` 当前调用：

```python
sender.send_text(chat_id, reply, root_id=message.root_id, reply_to_message_id=message.message_id)
```

因此 sender 规则为：

- 有 `reply_to_message_id`：使用 reply API。
- `root_id is not None`：`reply_in_thread=True`。
- 没有 `reply_to_message_id`：使用 create API，`receive_id_type="chat_id"`，`receive_id=chat_id`。

MVP 不做 Markdown；`send_text` 只发 text 类型。

## Error Handling

- 转换错误：记录并跳过该事件。
- `BotApp.handle_message()` 异常：在后台 task 的 done callback 中记录；不向 SDK 事件回调抛出。
- 发送错误：由 sender 抛出，runner 捕获并记录。
- WebSocket 连接重连：沿用 SDK 自带 `auto_reconnect=True`。

## Ack and Background Processing

`lark_oapi.ws.Client` 在处理 DATA frame 时会调用 `event_handler._do_without_validation(...)`，并在该调用返回后写回响应帧。因为 LLM 和 MCP 调用可能明显超过飞书 3 秒事件响应窗口，注册到 SDK 的事件回调不能同步等待 `BotApp.handle_message()`。

推荐实现：

```python
def on_message(event: P2ImMessageReceiveV1) -> None:
    dedupe_key = adapter.dedupe_key(event)
    if dedupe_key is None or self._dedupe.seen(dedupe_key):
        return
    message = adapter.to_incoming_message(event)
    if message is None:
        return
    self._dedupe.mark(dedupe_key)
    task = asyncio.get_running_loop().create_task(app.handle_message(message))
    self._tasks.add(task)
    task.add_done_callback(self._on_task_done)
```

`_on_task_done` 负责移除 task 并记录异常。这样飞书 ack 和实际机器人回复解耦：ack 表示“事件已接收”，不是“AI 回复已完成”。

## Event Deduplication

ack-first 只能避免因为处理太慢导致飞书重试，但不能保证同一事件永不重复到达。Runner 需要在投递后台任务前做本进程内幂等判断。

去重策略：

- `LarkMessageEventAdapter.dedupe_key(event)` 返回稳定字符串。
- key 优先级：事件 header 中的 `event_id` / `uuid`（如果 SDK model 暴露）→ `event.message.message_id`。
- 如果没有稳定 key，跳过该事件并记录 warning；不要把无法幂等的事件交给 LLM。
- `LarkWebSocketBotRunner` 维护 bounded TTL set，例如默认保留 10 分钟或最多 4096 个 key。
- 重复 key 命中时，事件回调直接返回，不创建后台 task，不写 JSONL，不发送回复。

这个 MVP 去重只覆盖单进程运行期间的短时间重复投递。跨进程、多副本或重启后的持久化去重需要独立运行时状态设计，放到后续任务。

## Test Strategy

- 事件转换测试使用 SDK model builder 或轻量 fake object。
- sender 测试用 fake message API 记录传入的 request object，不触发 HTTP。
- runner 测试验证事件回调会把可转换事件投递为后台 task 并立即返回；不启动真实 `lark.ws.Client.start()`。
- runner 测试同一 dedupe key 重复触发时只调用一次 fake `BotApp.handle_message()`，且重复回调仍立即返回。
- main 测试只覆盖配置校验 helper，避免启动阻塞 WebSocket。

## Compatibility Notes

- 当前项目 `requires-python = ">=3.13"`，不需要保留 Python 3.11 兼容。
- SDK WebSocket `Client.start()` 是阻塞调用；`main.py` 可以直接阻塞运行，测试中不得调用真实 `start()`。
- 不改变 `IncomingMessage` dataclass，不改变已有 JSONL 格式。
