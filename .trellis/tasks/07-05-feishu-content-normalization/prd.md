# Feishu/Lark 消息内容归一化

## 目标

将飞书/Lark 接收到的 `message.content` 从“只支持少数格式”升级为稳定的内部消息内容模型，让命令解析、LLM 输入、历史记录和后续工具扩展都基于同一个可测试的归一化契约。

## 背景与证据

- 用户在群聊中发送 `@bot /help` 时，飞书 text 消息内容为 `{"text":"@_user_1 /help"}`，当前若直接用 `text.startswith("/")` 会导致命令失效。
- 用户提供的真实 post 日志中，富文本内容包含 `tag: "at"`、`tag: "img"`、`tag: "text"`、`tag: "emotion"`；当前实现若把 `at` 当普通文字，会把 bot 名字带入命令或 LLM 输入。
- `research/feishu-message-content-structure.md` 是用户提供的飞书开放平台“接收消息内容结构”任务内调研快照，记录了飞书接收消息内容的完整结构，包括 `text`、`post`、`image`、`file`、`folder`、`audio`、`media`、`sticker`、`interactive`、红包、日程、群/个人名片、系统消息、位置、视频通话、任务、投票、合并转发等。
- 当前 `src/lark_agent/transport/lark/adapter.py` 只支持 `text`、`image`、`post`；其他 `message_type` 返回 `None`，会被 runner 当作 unsupported event 忽略。
- 当前 `post` 展平逻辑只处理 `text/a/at/img/image` 和通用容器字段，未明确处理 `emotion`、`hr`、`code_block`、`media`、`note`、卡片元素等语义。
- 当前会话已有一组局部修复改动：新增 `MentionPart`，让 router 能剥离开头 bot mention，并让 app 写入 LLM 的用户文本使用归一化结果。本任务将把这组改动纳入完整方案继续扩展。

## 需求

1. 建立 SDK 无关的内部 content part 模型，覆盖飞书文档中接收消息内容的主要结构。
2. Lark adapter 必须将已知 `message_type` 归一化为内部 part，而不是在可表达时直接丢弃整条消息。
3. post / interactive 等嵌套富文本结构必须保留用户可读顺序，至少保留文本、链接显示文本、mention、图片、视频/媒体、emoji、分割线、代码块、按钮/选择器等可读提示。
4. 命令解析与 LLM 输入应使用明确的 projection，不再让各调用点自行解释原始飞书 payload。
5. 群聊开头 bot mention 应从命令文本和 LLM 用户文本中移除；消息中部或非 bot mention 不应被错误删除。
6. 附件类内容在没有下载能力前必须以稳定占位文本和 key 元数据表达，不能假装已经读取附件内容。
7. 不支持或结构异常的内容应有明确行为：无法解析 JSON 或缺少关键 ID 时可忽略；已知但无法展开全部语义的类型应尽量生成可读 summary。
8. 测试必须覆盖 `research/feishu-message-content-structure.md` 中代表性结构，而不仅是 `/help` 的局部场景。
9. 为调试真实事件解析问题，归一化成功后应输出可对比日志，让开发者能把飞书事件中的原始 `message.content` 与内部归一化结果、文本投影对应起来。
10. 对比日志必须有大小边界，不能因为未来图片、视频、文件或卡片字段出现大体积内容（例如 base64、超长 JSON、长文本）而把日志打爆。

## 非目标

- 本任务不实现图片、文件、音频、视频的实际下载或 OCR/语音识别。
- 本任务不调用飞书 API 解析群名片、个人名片、日程、任务、投票等 ID 背后的详细信息。
- 本任务不改变发送消息格式，只处理接收消息到内部模型和文本投影。
- 本任务不实现完整审计日志、日志持久化、采样系统或敏感信息脱敏策略，只为归一化链路增加有边界的调试对比日志。

## 范围决策

- 本次 MVP 覆盖任务内调研快照 `research/feishu-message-content-structure.md` 中列出的所有已知消息类型。
- 覆盖方式是“归一化为内部 part 或可读 summary”，不做飞书外部 API 查询，也不下载附件。
- 对于无法完整结构化表达的业务卡片类消息，必须至少生成稳定、可读、包含关键字段的 summary，避免整条消息被 unsupported 逻辑丢弃。
- 归一化对比日志默认使用 `INFO` 级别，方便在当前默认日志配置下直接排查真实事件。
- 归一化对比日志应优先记录 message_id、chat_id、message_type、原始 content 预览、归一化 part 预览、默认文本 projection 预览；所有可能包含用户内容的字段都应截断并标明是否被截断。
- 现有原始事件日志中的 `message.content` 也必须改为有界预览，避免新增归一化日志安全但旧日志仍全量输出。

## 验收标准

- [ ] `@_user_1 /help` 在已 mention bot 的群聊中能识别为 `/help` 命令。
- [ ] post 中 `at + image + text + emotion` 能归一化为不含开头 bot 名字、包含图片占位、包含后续文字/emoji 语义的 LLM 输入。
- [ ] `file/folder/audio/media/sticker` 等附件类消息不会被直接忽略，能形成带 key/name/duration 等字段的内部 part 和可读文本投影。
- [ ] `post` 的 `code_block/hr/emotion/media` 至少有稳定文本投影，不会静默消失。
- [ ] `interactive` 卡片能按元素顺序提取可读文本、按钮/选项/图片等占位信息。
- [ ] 日程、群/个人名片、系统消息、位置、视频通话、任务、投票、合并转发等业务类型能生成稳定 summary。
- [ ] 归一化成功后有一条日志能对比原始 content 与归一化结果；日志对原始 content、part/result、projection 都有明确长度上限，并能标识截断。
- [ ] 无效 JSON、未知 chat type、缺少 message_id/chat_id/sender_id 仍按现有安全策略忽略。
- [ ] 全量测试通过：`UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`。
- [ ] 编译检查通过：`UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src`。
