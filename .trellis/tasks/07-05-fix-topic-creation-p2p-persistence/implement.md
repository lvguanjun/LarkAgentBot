# Implement: 修复话题创建与 p2p 持久化

## Checklist

0. 实现前读取任务研究文档
   - `.trellis/tasks/07-05-fix-topic-creation-p2p-persistence/research/feishu-thread-topic.md`

1. 更新 `transport/base.py`
   - 增加 `IncomingMessage.thread_id`。
   - 增加 `SendResult`。
   - 扩展 `MessageSender.send_text()` 返回值和 `reply_in_thread` 参数。

2. 更新飞书 adapter/sender
   - `LarkMessageEventAdapter` 读取 `message.thread_id`。
   - `LarkMessageSender` 使用显式 `reply_in_thread` 参数。
   - `LarkMessageSender` 从 response `data` 提取 `message_id`、`root_id`、`thread_id`。

3. 更新 router
   - `get_existing_thread_id()` 只返回 `thread_id`。
   - 没有 `thread_id` 时不要返回 `root_id`、p2p `chat_id` 或 `MAIN_THREAD_ID` 作为普通 conversation id。
   - 线程激活使用真实 `thread_id`。

4. 更新 app 编排
   - 解析 project key：group 使用 `message.chat_id`，p2p 使用 `message.sender_id`。
   - 将本轮消息先保存在内存列表中。
   - LLM/tool loop 使用 `conversation.get_context() + turn_messages`。
   - 普通 LLM 回复统一设置 `reply_in_thread=true`，不按 `chat_type` 分支。
   - 发送后根据 `SendResult.thread_id` 确定新话题 final conversation id。
   - 如果发送结果缺少 `thread_id`，fail closed，不写普通 conversation history。
   - 写入 final conversation。
   - 管理命令保持不写普通 history。

5. 更新测试
   - adapter 覆盖 `thread_id`。
   - sender 覆盖显式 `reply_in_thread` 和 response result。
   - router 覆盖 `thread_id` 优先级。
   - app 覆盖 group 无话题消息创建话题后写入 topic history。
   - app 覆盖 p2p 无话题消息使用同一套创建话题和 topic history 逻辑。
   - app 覆盖发送结果缺少 `thread_id` 时不写普通 history 且暴露明确错误。
   - app 覆盖 p2p project 目录使用 `sender_id`，group project 目录使用 `chat_id`。
   - app 覆盖已在线程消息继续写同一 topic。
   - 调整已有 fake sender 断言。

## Validation

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

## Rollback Points

- 如果 `BotApp` 延迟持久化导致 tool loop 上下文错误，先回滚 app 编排改动，保留 transport/base 的协议扩展和 adapter/sender 测试。
- 如果 sender response 提取在 fake/SDK 对象上不稳定，将提取逻辑收敛为私有 helper 并用对象属性访问测试覆盖。
