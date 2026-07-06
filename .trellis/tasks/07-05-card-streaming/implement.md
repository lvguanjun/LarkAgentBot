# 执行计划：飞书卡片消息流式输出与表情交互

## 实现顺序

按依赖关系自底向上：Transport 协议 → Transport 实现 → LLM 客户端 → App 层 → 入口集成。

### Step 1: Transport 协议层扩展

**文件**: `src/lark_agent/transport/base.py`

- [ ] 新增 `StreamingCardState` dataclass（mutable，card_id + element_id + sequence + next_sequence()）
- [ ] 新增 `MessageReactor` Protocol（add_reaction, remove_reaction）
- [ ] 新增 `CardStreamer` Protocol（create_streaming_card, send_card, update_card_content, close_streaming）

**验证**: 类型检查通过，现有测试不受影响

### Step 2: LarkMessageReactor 实现

**文件**: 新建 `src/lark_agent/transport/lark/reactor.py`

- [ ] 实现 `add_reaction`：使用 `CreateMessageReactionRequest` + `Emoji.builder()`，返回 reaction_id
- [ ] 实现 `remove_reaction`：使用 `DeleteMessageReactionRequest`
- [ ] 所有 API 错误 catch + log warning，不向上抛出
- [ ] 更新 `transport/lark/__init__.py` 导出

**验证**: 单元测试 mock lark client 验证调用

### Step 3: LarkCardStreamer 实现

**文件**: 新建 `src/lark_agent/transport/lark/card_streamer.py`

- [ ] 实现 `create_streaming_card`：构建卡片 JSON（schema 2.0, streaming_mode, markdown element），调用 `cardkit.v1.card.acreate`
- [ ] 实现 `send_card`：构建 `{"type":"card","data":{"card_id":"..."}}` content，调用 `im.v1.message.acreate` 或 `.areply`
- [ ] 实现 `update_card_content`：调用 `cardkit.v1.card_element.acontent`
- [ ] 实现 `close_streaming`：调用 `cardkit.v1.card.asettings` 设置 streaming_mode=false
- [ ] 定义 `CardStreamError` 异常类
- [ ] 更新 `transport/lark/__init__.py` 导出

**验证**: 单元测试 mock lark client 验证各步骤调用参数

### Step 4: LLM 客户端流式支持

**文件**: `src/lark_agent/llm_client.py`

- [ ] 新增 `StreamChunk` dataclass（delta_text, tool_calls_delta, finish_reason）
- [ ] 新增 `stream_message` 异步生成器方法
- [ ] OpenAI 路径：使用 `stream=True` + async for 遍历 chunks，累积 tool_calls by index
- [ ] 自定义 client 降级路径：如无 stream_message 方法，调用 complete_message 后 yield 单个 chunk

**验证**: 单元测试验证 stream 输出和 tool_calls 累积逻辑

### Step 5: App 层流式主流程

**文件**: `src/lark_agent/app.py`

- [ ] 新增 `StreamThrottle` 工具类（interval_ms, should_update）
- [ ] 新增 `repair_markdown` 函数（修复未闭合的代码块围栏）
- [ ] 提取现有逻辑为 `_handle_text_reply`（保持当前行为不变）
- [ ] 新增 `_handle_streaming_reply` 方法：
  - 创建卡片 → 发送卡片 → 流式 LLM + 节流更新 → 工具调用状态展示 → 关闭流式
- [ ] 重构 `handle_message`：
  - 表情回复逻辑（Typing → DONE）
  - 有 card_streamer 走 streaming reply，无则走 text reply，不做运行时降级
  - 命令回复保持纯文本不变
- [ ] `BotApp.__init__` 新增 `reactor` 和 `card_streamer` 可选参数

**验证**: 现有 test_app.py 测试仍通过（因为 reactor/card_streamer 默认为 None，走 text 路径）

### Step 6: 入口集成

**文件**: `src/lark_agent/main.py`

- [ ] 在 `build_runner` 中创建 `LarkMessageReactor` 和 `LarkCardStreamer`，注入到 `BotApp`

**验证**: 手动启动 bot，发消息验证完整流程

### Step 7: 测试补充

- [ ] `tests/test_reactor.py`: reactor 添加/删除表情、错误静默处理
- [ ] `tests/test_card_streamer.py`: 卡片创建、发送、更新、关闭流式
- [ ] `tests/test_llm_streaming.py`: 流式 chunk 解析、tool_calls 累积
- [ ] `tests/test_app.py` 扩展: 流式回复主流程、降级逻辑、表情切换

## 回滚点

- Step 1-4 是纯新增，不影响现有行为
- Step 5 的关键回滚点：`_handle_text_reply` 提取完成后，BotApp 在 card_streamer 为 None 时自动走 text 路径
- Step 6 是最后的集成点，可以通过不注入 card_streamer 来禁用卡片功能
