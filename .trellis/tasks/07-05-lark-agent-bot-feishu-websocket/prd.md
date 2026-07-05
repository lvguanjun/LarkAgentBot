# 飞书 WebSocket 长连接接入

## Goal

为现有 transport-independent bot core 增加真实飞书 WebSocket 长连接适配层，使机器人可以接收飞书消息事件、转换为内部 `IncomingMessage`，并通过现有 `BotApp` 完成路由、AGENTS.md、Skills、MCP、LLM 回复和 JSONL 持久化。

用户价值：当前核心能力已经可以本地测试，但不能作为真实飞书机器人运行；本任务完成后，开发者可以用 `config.yaml` 中的飞书应用配置启动一个可工作的 live bot。

## Background

- 父任务：`06-27-lark-agent-bot`。
- 已完成依赖：
  - `07-04-lark-agent-bot-core`：transport base、路由、Project/Conversation、AGENTS.md fallback、fake LLM 对话闭环。
  - `07-04-lark-agent-bot-skills`：Skills 发现、`read_skill`、bounded tool loop、tool-call JSONL 持久化。
  - `07-04-lark-agent-bot-agents-layout`：将 Skills/MCP 资源路径迁移到 `.agents/`。
  - `07-05-runtime-data-git-hygiene`：忽略运行时 `data/`，默认资源迁移到 `templates/defaults/`。
  - `07-05-lark-agent-bot-mcp`：MCP 配置加载、tool 发现、tool loop 分发和持久化。
- 现有 `IncomingMessage` / `MessageSender` 边界已经在 `src/lark_agent/transport/base.py:26` 到 `src/lark_agent/transport/base.py:59` 定义。
- 现有 `BotApp` 已经只依赖 `MessageSender` 和 `IncomingMessage`，并在 `src/lark_agent/app.py:39` 到 `src/lark_agent/app.py:107` 处理完整消息闭环。
- 现有 `LarkConfig` 包含 `app_id`、`app_secret`、`bot_id`，见 `src/lark_agent/config.py:10` 到 `src/lark_agent/config.py:14`。
- 本地 SDK 证据显示 `lark_oapi.VERSION == 1.7.0`；`lark.ws.Client` 通过直接构造接收 `app_id`、`app_secret`、`event_handler`，并由 `start()` 阻塞运行，见 `.venv/lib/python3.13/site-packages/lark_oapi/ws/client.py:117` 到 `.venv/lib/python3.13/site-packages/lark_oapi/ws/client.py:164`。
- 飞书消息事件模型 `EventMessage` 提供 `message_id`、`root_id`、`chat_id`、`chat_type`、`message_type`、`content`、`mentions` 等字段，见 `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/event_message.py:9` 到 `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/event_message.py:40`。

## Requirements

### R1: WebSocket 长连接启动

- 新增 `src/lark_agent/transport/websocket.py`。
- 使用 `lark_oapi.EventDispatcherHandler.builder(...).register_p2_im_message_receive_v1(...)` 注册消息事件处理器。
- 使用 `lark_oapi.ws.Client(app_id, app_secret, event_handler=...)` 建立 WebSocket 长连接。
- SDK `Client.start()` 是阻塞调用；实现需把阻塞边界封装在 runner 中，不能改变 `BotApp.handle_message()` 的 async 接口。
- WebSocket adapter 不实现业务路由、LLM、Skills 或 MCP 逻辑，只负责飞书事件和内部 transport 模型之间的转换。

### R2: 飞书事件转换为 `IncomingMessage`

- 支持 `message_type == "text"`：
  - 解析 `message.content` JSON 中的文本字段为 `TextPart`。
  - 保留 raw event 到 `IncomingMessage.raw_event`。
- 支持 `message_type == "post"`：
  - 将富文本内容拍平为 `TextPart` / `ImagePart` 序列。
  - 文本段按原顺序拼接；图片段保留 `file_key` 并使用现有图片占位语义。
- 支持 `message_type == "image"`：
  - 转换为 `ImagePart(file_key=...)`，不在本任务下载图片或做 vision。
- 不支持的消息类型应被忽略或返回 `None`，不得导致 WebSocket 事件处理器崩溃。
- `chat_type` 只映射为内部允许值：
  - 飞书群聊映射为 `"group"`。
  - 飞书私聊 / p2p 映射为 `"p2p"`。
  - 无法识别的类型应忽略。
- `root_id` 优先使用飞书 `message.root_id`；无 `root_id` 时保持 `None`，由现有 router 决定主会话或私聊 conversation。
- `mentions` 应提取被提及用户的可匹配 ID，至少包含 `open_id`；如 SDK 事件中同时存在 `user_id` / `union_id`，可一并纳入列表，确保可匹配 `config.lark.bot_id`。

### R3: 飞书文本回复发送器

- 实现一个 `MessageSender` 适配器，例如 `LarkMessageSender`。
- `send_text(chat_id, text, root_id=None, reply_to_message_id=None)` 优先使用飞书 reply API 回复原消息：
  - 当 `reply_to_message_id` 存在时，调用 `client.im.v1.message.areply(...)`。
  - 当需要在线程内回复时，设置 `reply_in_thread=True`；SDK request body 支持该字段，见 `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/reply_message_request_body.py:7` 到 `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/reply_message_request_body.py:19`。
- 当没有 `reply_to_message_id` 时，可使用 create message API 向 `chat_id` 发送文本消息。
- 发送内容使用飞书 `msg_type="text"`，`content` 为 JSON 字符串。
- 发送失败应抛出清晰异常；本任务不做复杂重试。

### R4: 事件处理并发边界

- 飞书事件接收存在 3 秒快速响应约束：事件 handler 必须尽快返回 SDK，让 SDK 可以在飞书要求的 3 秒窗口内完成 ack；不能等待 LLM、MCP tool、OpenAI API 或消息发送完成后才返回。
- `lark_oapi` WebSocket SDK 会在事件处理器返回后写回响应帧；因此注册到 `register_p2_im_message_receive_v1(...)` 的同步回调必须采用 ack-first 设计。
- 回调流程应为：转换事件 → 若可处理则投递后台 async task 调用 `BotApp.handle_message()` → 立即返回。
- 回调必须防止短时间重复处理同一事件；重复事件应被 ack 但不再次投递 `BotApp.handle_message()`，避免同一用户消息写入两次 JSONL 或回复两次。
- 去重 key 优先使用飞书事件 `event_id` / `uuid`（若事件模型可获得），否则使用 `message.message_id`；没有稳定 key 的事件不应进入 LLM 处理。
- MVP 去重范围为单进程内 bounded TTL 缓存，覆盖飞书重试、WebSocket 重连或 SDK 重放导致的短时间重复投递；跨进程/重启后的持久化去重不纳入本任务。
- 对同一进程内的 live bot，允许先用简单后台 task set 管理并发；不要求实现 per-thread 队列。
- 不得因为单条消息转换失败、LLM 失败或发送失败导致 WebSocket 连接进程直接退出；应记录错误并让事件 handler 返回。

### R5: 最小入口装配

- 新增最小 `src/lark_agent/main.py`，用于从 `config.yaml` 加载配置、构造 OpenAI-compatible `LLMClient`、构造飞书 sender、构造 `BotApp` 并启动 WebSocket runner。
- 配置缺少 `lark.app_id`、`lark.app_secret` 或 `lark.bot_id` 时，应在启动前给出明确错误。
- 本任务不要求打包 console script，但 `python -m lark_agent.main` 应可以作为本地启动方式。

### R6: 测试边界

- 单元测试必须不依赖真实飞书凭证、真实 WebSocket、真实飞书 API。
- 重点测试纯转换函数、sender request 构造、事件 handler 对 `BotApp` 的调用边界。
- 可以通过 fake lark client / fake message API 验证 `areply` 和 `acreate` 调用参数。

## Acceptance Criteria

- [ ] 存在 `src/lark_agent/transport/websocket.py`，并注册 `p2.im.message.receive_v1` 事件。
- [ ] text 消息事件能转换为 `IncomingMessage(content=[TextPart(...)])`，并保留 `message_id`、`chat_id`、`chat_type`、`sender_id`、`root_id`、`mentions`。
- [ ] post 消息事件能按顺序拍平文本和图片内容。
- [ ] image 消息事件能转换为 `ImagePart`，且不会触发图片下载。
- [ ] 不支持的消息类型或无法识别的 chat type 不会让事件 handler 崩溃。
- [ ] 飞书事件回调采用 ack-first 设计：不会等待 `BotApp.handle_message()`、LLM、MCP tool 或发送回复完成后才返回。
- [ ] 后台消息处理异常会被记录，不会传播到飞书事件回调并导致 SDK 对该事件返回失败。
- [ ] 同一事件/消息在 TTL 窗口内重复到达时，只会投递一次 `BotApp.handle_message()`；重复事件仍会快速 ack。
- [ ] 无稳定去重 key 的事件不会进入 LLM 处理，避免无法幂等的重复回复。
- [ ] `LarkMessageSender.send_text(...)` 在有 `reply_to_message_id` 时调用 reply API，并在话题回复场景设置 `reply_in_thread=True`。
- [ ] `LarkMessageSender.send_text(...)` 在没有 `reply_to_message_id` 时能构造 create message 请求。
- [ ] `python -m lark_agent.main` 有最小启动入口，并在缺少必要飞书配置时 fail fast。
- [ ] 新增测试不需要飞书凭证即可通过。
- [ ] 现有 core、Skills、MCP 测试继续通过。

## Out of Scope

- Webhook 接入。
- 管理命令 `/help`、`/config`、`/skill list`、`/mcp list`、`/reset`。
- 飞书卡片消息和交互。
- 图片下载、OCR、vision 模型接入。
- post 富文本的完整格式保真渲染；MVP 只拍平为文本和图片占位。
- 复杂重试、限流和 per-thread 并发队列。
- 跨进程或进程重启后的持久化事件去重。
- 生产部署脚本、systemd、容器镜像。

## Open Questions

当前没有阻塞规划的问题。默认将最小 `main.py` 纳入本子任务，因为没有入口会让 WebSocket adapter 难以作为真实机器人验证；管理命令仍放到后续子任务。
