# Feishu/Lark 消息内容归一化设计

## 架构边界

- 归一化范围以任务内调研快照
  `research/feishu-message-content-structure.md` 为准。
- `src/lark_agent/transport/lark/adapter.py` 负责把飞书 SDK event payload 解码为 SDK 无关的 `IncomingMessage`。
- `src/lark_agent/transport/base.py` 负责定义内部 content part 模型和默认文本投影。
- `src/lark_agent/router.py` 负责命令触发、线程触发和群聊开头 bot mention 的命令/LLM 文本归一化。
- `src/lark_agent/app.py` 只消费 router 给出的归一化用户文本，不直接解释飞书原始 payload。

## 内部内容模型

保留已有类型并扩展为可覆盖飞书已知消息结构：

- `TextPart(text)`
- `MentionPart(user_id, user_name)`
- `ImagePart(file_key, alt_text)`
- `FilePart(file_key, file_name, kind)`
- `MediaPart(file_key, image_key, file_name, duration, kind)`
- `StickerPart(file_key)`
- `LinkPart(text, href)`
- `CodeBlockPart(language, text)`
- `DividerPart(text)`
- `EmojiPart(emoji_type)`
- `LocationPart(name, longitude, latitude)`
- `SummaryPart(kind, title, fields)`

说明：

- `SummaryPart` 用于日程、名片、系统消息、视频通话、任务、投票、合并转发、红包、卡片控件等不需要专门行为但必须可读的结构。
- 附件 part 只保存飞书返回的 key/name/duration 等元数据，不声明已经读取附件内容。
- 后续如要下载文件或 OCR 图片，应基于这些 part 增加工具层能力，而不是修改 Lark adapter 去联网。

## 消息类型映射

| 飞书 message_type | 内部表示 |
| --- | --- |
| `text` | `TextPart`，保留 `@_user_N` placeholder，由 router 剥离开头 bot mention |
| `post` | 按富文本顺序展平为 text/link/mention/image/media/emoji/divider/code/summary |
| `image` | `ImagePart` |
| `file` / `folder` | `FilePart(kind="file"|"folder")` |
| `audio` | `MediaPart(kind="audio")` |
| `media` | `MediaPart(kind="media")` |
| `sticker` | `StickerPart` |
| `interactive` | 从 `title` 和 `elements` 中按顺序提取可读 part；按钮、选择器等控件转为 `SummaryPart` |
| `hongbao` | `SummaryPart(kind="hongbao")` 或 `TextPart("[红包]")` |
| `share_calendar_event` / `calendar` / `general_calendar` | `SummaryPart(kind=<type>, fields=summary/start_time/end_time)` |
| `share_chat` / `share_user` | `SummaryPart(kind=<type>, fields=chat_id/user_id)` |
| `system` | 用 template 和字段生成 `SummaryPart(kind="system")` |
| `location` | `LocationPart` |
| `video_chat` | `SummaryPart(kind="video_chat")` |
| `todo` | `SummaryPart(kind="todo")`，其中 summary post 递归使用富文本 projection |
| `vote` | `SummaryPart(kind="vote")` |
| `merge_forward` | `SummaryPart(kind="merge_forward")` |

未知 `message_type` 仍返回 `None`，因为没有文档契约可保证语义。

## 文本 Projection

`IncomingMessage.text_content()` 是默认 LLM 可读投影，规则：

- 文本和链接保留可读文本；链接可表达为 `text (href)`。
- 图片使用 `[用户发送了一张图片]`。
- 文件/视频/音频/表情/位置/业务卡片使用稳定中文占位，包含关键字段。
- post 的行级结构应保留换行，避免多行内容完全粘连。
- code block 使用带语言和代码内容的可读文本，至少不丢失代码文本。

`MessageRouter.normalized_text_content()` 在默认投影基础上处理群聊开头 bot mention：

- 已确认 bot 被 mention 的群聊，删除开头 `MentionPart` 或 text placeholder `@_user_N`。
- 只删除开头连续 mention 与空白，不删除消息中部 mention。
- 私聊和未 mention bot 的群聊保持原始默认投影。

命令解析使用 router projection；LLM history 使用同一 projection，避免命令和普通问答不一致。

## 归一化日志

`LarkWebSocketBotRunner.handle_event()` 在 adapter 归一化成功后输出一条 `INFO`
级别对比日志，便于把飞书事件中的原始 `message.content` 与内部归一化结果对应起来。

日志字段：

- `message_id`
- `chat_id`
- `message_type`
- `raw_content_preview`
- `normalized_parts_preview`
- `text_projection_preview`

所有 preview 字段都使用同一个硬上限截断，并在截断时追加标记。现有“收到事件”日志中的原始
`content` 也必须使用同一预览函数，避免图片/视频/文件或卡片字段未来出现 base64、长 JSON、
长文本时把日志打爆。

日志不记录下载后的附件内容、OCR 内容或语音转写；本任务只记录飞书 payload 中已有的 content
字符串预览，以及内部 part 的元数据预览。

## 错误与兼容策略

- 无法解析 JSON：保持现有行为，返回 `None` 并 warning log。
- 缺少 message_id/chat_id/sender_id：保持现有行为，返回 `None`。
- 已知类型缺少关键 key：尽量生成 summary；如果完全无法表达内容，返回 `None`。
- 不增加向后兼容路径；项目处于 active development，直接更新当前内部 contract。

## 测试策略

- `tests/test_lark_websocket.py` 覆盖 adapter 对每类代表性 payload 的归一化。
- `tests/test_router.py` 覆盖 mention 剥离、命令识别、消息中部 mention 保留。
- `tests/test_app.py` 覆盖 app 写入 LLM 的文本 projection。
- 保留现有 unsupported、dedupe、sender、runner 测试行为。

## 取舍

- 选择“一次性覆盖已知类型的可读 summary”，而不是只支持最常见聊天类型，原因是 adapter 边界需要完整、可预测，避免真实群聊里业务卡片/位置/投票被静默忽略。
- 不在本任务实现附件下载/OCR/语音识别，原因是这些需要新外部 API、权限和异步工具流，属于独立能力。
