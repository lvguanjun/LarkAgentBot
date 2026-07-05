# Support image messages

## Goal

让机器人在收到飞书图片或含图片的富文本消息时，把图片作为 OpenAI 兼容的多模态输入交给模型，而不是只发送文本占位符。

首版目标是支持图文消息：保留文本顺序，下载飞书图片，以本地附件形式保存图片内容，在发送给 OpenAI 时拼成 base64/data URL，并在 TODO 中记录未来支持用户自带上传接口获取 URL。

## Confirmed Facts

- `TODO.md` 当前待办包含“图片下载、OCR 或 vision 模型支持”，这次只落地 vision 图文消息，不做 OCR。
- `src/lark_agent/transport/lark/adapter.py` 已经能把飞书 `image` 消息和 `post` 富文本 `img`/`image` 节点转换成 `ImagePart(file_key=...)`。
- `src/lark_agent/transport/base.py` 当前 `IncomingMessage.to_openai_message()` 只返回字符串 content，`ImagePart` 会被投影为 `[用户发送了一张图片]`。
- `tests/test_app.py` 现有测试 `test_image_part_is_downgraded_to_text_placeholder` 明确覆盖了当前降级行为，实施本任务时需要更新为多模态行为。
- `src/lark_agent/app.py` 当前对普通 LLM 消息使用 `router.normalized_text_content(message)` 构造 `{"role": "user", "content": user_text}`；这会丢失图片结构。
- `src/lark_agent/llm_client.py` 对 OpenAI `messages` 基本透传，核心风险不在 OpenAI client，而在消息结构构造、图片下载和历史持久化格式。
- 代码规范要求 Feishu/Lark SDK 相关逻辑留在 `transport/lark/`，核心模块通过 SDK-independent dataclass/protocol 测试。
- `trellis-research` 调研未发现飞书 bot 入站图片可直接转换为 OpenAI 可访问的公网 URL；飞书/Lark SDK 暴露的是鉴权下载二进制接口。

## Requirements

- R1: 支持飞书 `image` 消息和 `post` 富文本中混排的图片节点。
- R2: 用户消息传给 LLM 时使用 OpenAI chat completions 兼容的 content list：文本片段为 `{"type": "text", "text": ...}`，图片片段为 `{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<...>"}}`。
- R3: 图片下载必须通过可注入的边界完成，测试不依赖真实飞书、OpenAI 或网络。
- R4: 图片下载失败时不能让整条消息静默消失；首版应保留可读文本占位，让模型知道用户发过图片但图片不可用。
- R5: 普通 conversation history 必须能持久化并回放多模态用户消息，且不破坏现有 tool call / tool result 历史分组。
- R5.1: `history.jsonl` 不应直接保存大段 base64；首版历史里保存稳定图片索引，本地保存图片内容，上下文回放时再拼接回 OpenAI content list。
- R6: 命令识别和管理命令仍使用纯文本投影，发送图片不应误触发命令处理。
- R7: `TODO.md` 需要记录未来支持用户自带上传接口获取 URL，例如 WebDAV 或其他通用上传接口；首版不实现内置图床，也不接入用户自带图床。

## Acceptance Criteria

- [ ] 飞书图片消息进入 app 后，Fake LLM 收到的 user message content 是 OpenAI 兼容 list，而不是字符串占位。
- [ ] 飞书 post 图文混排进入 app 后，文本和图片在 LLM content list 中保持原始顺序。
- [ ] 图片下载成功时，OpenAI content list 中的图片 URL 使用 data URL/base64。
- [ ] 图片下载失败时，LLM 仍收到文本占位，历史仍可正常保存，BotApp 不因单张图片失败而崩溃。
- [ ] 管理命令路径不下载图片、不发送多模态 content。
- [ ] JSONL conversation history 能保存并读取可回放的图片索引，且回放给 LLM 时能还原为 OpenAI content list。
- [ ] 单元测试覆盖 adapter 已有图片键解析、app 多模态构造、下载失败降级、命令路径不下载、历史持久化。
- [ ] `TODO.md` 记录后续支持用户自带上传接口获取图片 URL。

## Decisions

- D1: 图片下载失败时，继续调用模型并把失败图片替换成文本占位，例如 `[用户发送了一张图片，但图片下载失败]`，不因单张图片失败阻断整条图文消息。
- D2: 不在 `history.jsonl` 中直接保存 base64。首版保存本地图片索引，并在组装上下文时从本地内容恢复成 data URL/base64。
- D3: 首版不实现图床或用户上传接口；未来只考虑用户自带上传接口（例如 WebDAV 或通用上传接口）返回 URL，作为后续会话再设计。

## Open Questions

- 当前无阻塞开放问题。
