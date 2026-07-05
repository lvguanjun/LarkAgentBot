# Fix topic creation and p2p persistence

## Goal

修复飞书机器人处理普通消息时没有成功创建话题的问题，并确保群聊与 p2p 的 conversation history 都按同一套话题维度持久化，避免无话题消息混入错误的 fallback conversation。

## Background

- 用户提供的飞书话题资料已沉淀到任务研究文档 `research/feishu-thread-topic.md`。资料说明：在消息形式群中，调用回复消息接口并传入 `reply_in_thread=true` 可将某一消息创建为话题；发送/回复响应和接收消息事件可获得 `thread_id`。
- 本地 SDK 事件模型 `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/event_message.py` 包含 `thread_id` 字段；当前 `src/lark_agent/transport/lark/adapter.py` 未读取该字段，只保留 `root_id`。
- `src/lark_agent/app.py:50` 和 `src/lark_agent/app.py:108` 始终把 `reply_to_message_id=message.message_id` 传给 sender。
- `src/lark_agent/transport/lark/sender.py:31` 到 `src/lark_agent/transport/lark/sender.py:47` 在有 `reply_to_message_id` 时使用 reply API，但只在 `root_id is not None` 时设置 `reply_in_thread=True`。
- `src/lark_agent/router.py:35` 到 `src/lark_agent/router.py:40` 当前用 `root_id`、p2p `chat_id` 或 `"main"` 作为内部 thread id，没有真实 `thread_id` 优先级；这里的 `root_id` / p2p 特判是当前实现现状，不是目标行为。
- p2p 的 project 目录应按用户身份稳定隔离。当前 adapter 的 `sender_id` 优先取 Feishu `open_id`，因此 p2p project key 使用 `sender_id`；group project key 继续使用 `chat_id`。

## Requirements

1. 触发普通 LLM 回复的消息，无论 `chat_type` 是 group 还是 p2p，发送层都必须使用飞书 reply API，并设置 `reply_in_thread=true`，使该消息进入话题语义。
2. 已经处在飞书话题中的消息必须继续回复到同一话题，不创建新的话题。
3. 飞书 adapter 必须保留事件中的 `thread_id`；conversation id 只能由真实 `thread_id` 或创建话题后的发送结果 `thread_id` 决定。
4. 首条无话题消息被创建为话题后，本轮 user/assistant/tool 历史应持久化到真实话题 conversation；如果发送响应没有返回 `thread_id`，必须 fail closed：不写入普通 conversation history，并让错误在日志/异常中可见。不得用 `root_id`、`message_id`、`conversations/main` 或 p2p `chat_id` 猜测替代。
5. Project 目录 key 与 conversation id 分离：
   - group project key 使用 `chat_id`。
   - p2p project key 使用 `sender_id`，也就是 adapter 归一化出的用户 open_id 优先值。
   - conversation id 仍由真实 `thread_id` 决定，不使用 p2p `chat_id`、`root_id` 或 `message_id` 作为默认 conversation id。
6. p2p 和群聊在话题创建、conversation id 解析、conversation history 写入上不做 chat_type 特判；差异只允许存在于 project key 选择和既有触发规则，例如 p2p 默认响应、群聊需要 mention 或已激活话题。
7. 管理命令仍不写入普通 conversation history；管理命令是否创建话题不作为本任务重点，只要现有命令响应不破坏普通 LLM 话题创建即可。
8. 所有 Feishu/Lark SDK 细节继续限制在 `src/lark_agent/transport/lark/`，核心层只能依赖 `transport/base.py` 的内部 dataclass/protocol。

## Out of Scope

- 不实现群消息形式查询、创建话题形式群或修改群配置。
- 不实现历史数据迁移；已落入 `conversations/main` 的旧记录保留原状。
- 不实现跨进程持久化 dedupe 或 per-thread 并发队列。
- 不引入数据库或新的顶层运行时目录；p2p 仍落在现有 `data/groups/<project_key>/` 布局下。

## Acceptance Criteria

- [ ] 单元测试证明 group 和 p2p 的普通 LLM 回复都会发起 `reply_in_thread=true` 的回复，而不是普通平铺回复。
- [ ] 单元测试证明 adapter 会从 Feishu 事件读取 `thread_id`，router/app 使用 `thread_id` 作为 conversation id。
- [ ] 单元测试证明已在线程中的消息回复同一话题，并按该话题 ID 写入 `history.jsonl`。
- [ ] 单元测试证明新建话题的首轮 LLM/tool 历史最终写入发送结果返回的 `thread_id` conversation，而不是 `conversations/main`、`root_id`、`message_id` 或 p2p `chat_id` conversation。
- [ ] 单元测试证明创建话题成功但发送结果缺少 `thread_id` 时不会写入普通 conversation history，并会暴露明确错误。
- [ ] 单元测试证明 p2p 普通消息与群聊普通消息走同一套新话题持久化路径。
- [ ] 单元测试证明 p2p project 目录使用 `sender_id`，group project 目录使用 `chat_id`，两者都位于 `data/groups/<project_key>/`。
- [ ] 现有消息路由、管理命令、Skills/MCP tool loop 持久化测试继续通过。
- [ ] `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` 通过。
- [ ] `UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src` 通过。

## Notes

- 本任务可保持 PRD-only；实现边界集中在 `transport/base.py`、`transport/lark/adapter.py`、`transport/lark/sender.py`、`router.py`、`app.py` 及对应测试。
- `research/feishu-thread-topic.md` 只记录外部飞书话题资料摘要；本地 SDK 和当前实现证据保留在本 PRD 的 Background 与技术设计中。
