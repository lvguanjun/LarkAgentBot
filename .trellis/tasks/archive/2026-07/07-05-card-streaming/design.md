# 技术设计：飞书卡片消息流式输出与表情交互

## 架构概览

变更涉及三层：Transport 协议层、LLM 客户端层、App 业务层。

```
BotApp.handle_message
  ├─ MessageReactor     ← 新增：表情回复
  ├─ CardStreamer        ← 新增：CardKit 卡片生命周期
  ├─ MessageSender      ← 保持不变：文本降级通道
  └─ LLMClient          ← 扩展：新增 stream_message
```

## 1. Transport 层新增协议（base.py）

### 1.1 MessageReactor

```python
class MessageReactor(Protocol):
    async def add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        """添加表情，返回 reaction_id（用于后续删除）"""
        ...

    async def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        """删除指定的表情回复"""
        ...
```

### 1.2 CardStreamer

```python
class CardStreamer(Protocol):
    async def create_streaming_card(self) -> "StreamingCardState":
        """创建 CardKit 卡片实体（streaming_mode=true），返回状态对象"""
        ...

    async def send_card(
        self,
        chat_id: str,
        card_id: str,
        *,
        reply_to_message_id: str | None = None,
        reply_in_thread: bool = False,
    ) -> SendResult:
        """发送卡片消息到会话"""
        ...

    async def update_card_content(
        self, card_id: str, element_id: str, content: str, sequence: int
    ) -> None:
        """流式更新卡片文本组件"""
        ...

    async def close_streaming(self, card_id: str, sequence: int) -> None:
        """关闭流式模式"""
        ...
```

### 1.3 StreamingCardState

```python
@dataclass
class StreamingCardState:
    card_id: str
    element_id: str = "md_main"
    sequence: int = 0

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence
```

不是 Protocol，而是一个 mutable 状态对象，跟踪 card_id、element_id 和 sequence 自增。

## 2. Lark Transport 实现

### 2.1 LarkMessageReactor（新文件：reactor.py）

使用 `client.im.v1.message_reaction` 的 `acreate` 和 `adelete` 方法。所有调用 catch exception 后 log warning，不向上传播。

### 2.2 LarkCardStreamer（新文件：card_streamer.py）

使用 `client.cardkit.v1.card` 和 `client.cardkit.v1.card_element` 模块：

- `create_streaming_card`: 创建卡片实体，JSON 2.0 schema，`streaming_mode=true`，单个 `markdown` 组件（`element_id="md_main"`），无 header
- `send_card`: 使用 `CreateMessageRequest`，`msg_type="interactive"`，content 为 `{"type":"card","data":{"card_id":"..."}}`
- `update_card_content`: 调用 `card_element.acontent`
- `close_streaming`: 调用 `card.asettings` 设置 `streaming_mode=false`

卡片 JSON 结构（无 header）：

```json
{
  "schema": "2.0",
  "config": {
    "update_multi": true,
    "streaming_mode": true,
    "summary": {"content": "[生成中]"},
    "streaming_config": {
      "print_frequency_ms": {"default": 50},
      "print_step": {"default": 2},
      "print_strategy": "fast"
    }
  },
  "body": {
    "elements": [
      {"tag": "markdown", "content": "", "element_id": "md_main"}
    ]
  }
}
```

### 2.3 LarkMessageSender 不变

保持现有 `send_text` 方法，作为降级通道。

## 3. LLM 客户端扩展

### 3.1 stream_message 方法

在 `LLMClient` 中新增：

```python
async def stream_message(
    self,
    system_prompt: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[StreamChunk, None]:
    ...
```

### 3.2 StreamChunk 数据结构

```python
@dataclass
class StreamChunk:
    delta_text: str = ""
    tool_calls_delta: list[dict[str, Any]] | None = None
    finish_reason: str | None = None
```

### 3.3 实现要点

- 使用 `client.chat.completions.create(..., stream=True)` 获取 async iterator
- 每个 chunk 提取 `delta.content` 和 `delta.tool_calls`
- tool_calls 需要跨 chunk 累积（index-based 合并 function name 和 arguments）
- 最后一个 chunk（`finish_reason` 非空）包含完整的累积 tool_calls

### 3.4 自定义 client 协议兼容

如果注入了自定义 `client`（测试用），且没有 `stream_message` 方法，则降级为 `complete_message` 后将结果包装为单个 StreamChunk 返回。

## 4. BotApp 变更

### 4.1 新增依赖

```python
class BotApp:
    def __init__(
        self,
        config: AppConfig,
        *,
        sender: MessageSender,
        llm_client: LLMClient,
        reactor: MessageReactor | None = None,       # 新增
        card_streamer: CardStreamer | None = None,     # 新增
        ...
    ) -> None:
```

### 4.2 handle_message 主流程重构

```
handle_message(message):
  if not should_respond: return
  if is_command: handle_command (不变)

  # 1. 表情反馈
  reaction_id = await reactor.add_reaction(message_id, "Typing")  # fire-and-forget style

  try:
    # 2. 尝试卡片流式回复
    if card_streamer:
      reply = await _handle_streaming_reply(message, ...)
    else:
      reply = await _handle_text_reply(message, ...)  # 当前逻辑，作为降级

    # 3. 表情切换
    if reaction_id:
      await reactor.remove_reaction(message_id, reaction_id)
    await reactor.add_reaction(message_id, "DONE")
  except Exception:
    # 确保降级
    ...
```

### 4.3 _handle_streaming_reply 流程

```
async def _handle_streaming_reply(message, ...):
  card = await card_streamer.create_streaming_card()
  send_result = await card_streamer.send_card(chat_id, card.card_id, ...)

  accumulated_text = ""
  throttle = StreamThrottle(interval_ms=400)

  for _ in range(MAX_TOOL_ITERATIONS):
    tool_calls = []
    iteration_text = ""

    async for chunk in llm_client.stream_message(system, messages, tools=tools):
      if chunk.delta_text:
        iteration_text += chunk.delta_text
        accumulated_text_with_delta = accumulated_text + iteration_text
        if throttle.should_update():
          await card_streamer.update_card_content(
            card.card_id, card.element_id,
            repair_markdown(accumulated_text_with_delta),
            card.next_sequence(),
          )
      if chunk.tool_calls_delta:
        merge_tool_calls(tool_calls, chunk)

    accumulated_text += iteration_text

    if not tool_calls:
      # 最终更新
      await card_streamer.update_card_content(
        card.card_id, card.element_id,
        accumulated_text,
        card.next_sequence(),
      )
      await card_streamer.close_streaming(card.card_id, card.next_sequence())
      break

    # 工具调用
    messages.append(assistant_message)
    for tc in tool_calls:
      status = f"\n\n> 🔧 正在调用: {tc.name}"
      await card_streamer.update_card_content(
        card.card_id, card.element_id,
        repair_markdown(accumulated_text + status),
        card.next_sequence(),
      )
      result = await tool_dispatcher.call_tool(tc.name, tc.args)
      messages.append(tool_result)

  return accumulated_text
```

### 4.4 StreamThrottle

简单的节流器：

```python
class StreamThrottle:
    def __init__(self, interval_ms: int = 400):
        self._interval = interval_ms / 1000
        self._last_update = 0.0

    def should_update(self) -> bool:
        now = time.monotonic()
        if now - self._last_update >= self._interval:
            self._last_update = now
            return True
        return False
```

### 4.5 repair_markdown

简单的 markdown 修复函数：

- 统计未闭合的 ``` 代码块围栏 → 如果奇数个，追加 ```
- 不处理其他 markdown 标记（粗体、斜体等影响小）

### 4.6 降级策略

- **`card_streamer` 为 None** → 走 `_handle_text_reply`（当前逻辑，提取为独立方法）
- **`card_streamer` 已注入但运行时失败** → 不做静默降级，log error 让用户排查配置问题
- `_handle_text_reply` 仅作为未启用卡片功能时的默认路径，不作为运行时回退

## 5. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `transport/base.py` | 修改 | 新增 `MessageReactor`、`CardStreamer`、`StreamingCardState` |
| `transport/lark/reactor.py` | 新建 | `LarkMessageReactor` 实现 |
| `transport/lark/card_streamer.py` | 新建 | `LarkCardStreamer` 实现 |
| `transport/lark/__init__.py` | 修改 | 导出新类 |
| `llm_client.py` | 修改 | 新增 `StreamChunk`、`stream_message` 方法 |
| `app.py` | 修改 | 重构 `handle_message`，新增流式逻辑 |
| `main.py` | 修改 | 构建并注入 reactor 和 card_streamer |
| `tests/` | 修改/新建 | 新增流式回复和表情回复测试 |

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 飞书客户端版本不支持 JSON 2.0/streaming | 服务端无法感知客户端版本，卡片渲染可能异常但不影响 API 调用 |
| CardKit API 权限未配置 | log error 提示用户配置权限，不静默降级 |
| 流式过程中网络中断 | 卡片停留在最后成功更新的状态，不影响对话持久化 |
| 30 KB 内容限制 | 截断 + 提示，避免 API 报错 |
| `complete_message` 自定义 client 不支持 streaming | 降级为非流式调用后包装 |
