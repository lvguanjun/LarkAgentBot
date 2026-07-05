# 图片消息支持设计

## 范围

本任务支持飞书/Lark 入站图片消息和富文本图文消息进入 OpenAI Chat Completions 多模态输入。首版不做 OCR，不做图床，不做用户自带上传接口；只在 TODO 中记录后续方向。

## 关键结论

- 飞书入站图片没有可直接给 OpenAI 抓取的公网 URL。调研结论见 `research/feishu-image-openai-inputs.md`。
- OpenAI Chat Completions 当前可接受 `content` list，其中图片使用 `image_url.url`，可传 `data:image/<type>;base64,...`。
- `history.jsonl` 不保存 base64。历史保存本地图片索引；组装 LLM 上下文时从本地二进制文件恢复成 data URL。

## 数据流

```text
Feishu event
  -> LarkMessageEventAdapter
  -> IncomingMessage.content: TextPart / MentionPart / ImagePart / ...
  -> MessageRouter strips leading bot mention as structured parts
  -> Image downloader downloads ImagePart by message_id + file_key
  -> Project image store writes binary file under project root
  -> BotApp builds current user message with OpenAI content list
  -> Conversation persists user message with text parts + local image refs
  -> Later context load expands local image refs back to OpenAI data URLs
```

## 边界与所有权

- `transport/base.py` 继续拥有 SDK-independent dataclasses/protocols。新增图片下载结果和下载器协议时不能引入 `lark-oapi`。
- `transport/lark/` 拥有真实飞书图片下载器，封装 `lark-oapi` 的 image/message resource API。
- 新的图片内容组装逻辑应在核心模块中实现，依赖 `IncomingMessage`、`ImageDownloader` 和项目目录，不依赖飞书 SDK。
- `conversation.py` 保持 JSONL 读写和窗口选择职责，不解析飞书 payload，不下载图片。
- `app.py` 只编排：判断命令、构造当前 turn、扩展历史上下文、调用 LLM、发送回复、写历史。

## 持久化格式

历史中的用户消息仍是 OpenAI 风格 message dict，但图片不保存 data URL，而保存内部引用：

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "这张图说了啥"},
    {
      "type": "image_ref",
      "image_ref": {
        "path": "attachments/images/<digest>.bin",
        "mime_type": "image/png",
        "file_key": "img_xxx",
        "alt_text": "[用户发送了一张图片]"
      }
    }
  ]
}
```

发送给 OpenAI 前扩展为：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:image/png;base64,<encoded>"
  }
}
```

如果图片本地文件缺失或读取失败，扩展时降级为：

```json
{"type": "text", "text": "[用户发送了一张图片，但图片不可用]"}
```

## 本地图片存储

- 图片文件保存在项目根目录下的 `attachments/images/`。
- 文件名使用稳定 digest，来源包含 `message_id`、`file_key` 和图片内容，避免原始 key 直接成为路径。
- 图片内容保存为二进制文件；MIME type、file_key、alt_text 保存在 history 的 `image_ref` 中。
- 首版不做清理策略。删除 conversation history 不删除附件，避免误删其他线程仍引用的图片。

## 下载策略

- `ImageDownloader.download_image(message_id, file_key)` 返回 bytes、MIME type 和可选文件名。
- 飞书实现优先使用 image download；如失败或接口不适用于该 key，可尝试 message resource download。
- 下载失败只影响对应图片 part：当前 turn 和历史中用失败占位文本替代，不让整条图文消息失败。
- 管理命令路径不调用图片下载器。

## 群聊 mention 规范化

当前 `MessageRouter.normalized_text_content()` 会在群聊中去掉开头的 bot mention。多模态消息也必须复用同一语义：先得到“去掉开头 bot mention 后”的结构化 parts，再构造文本和图片 content list。

## TODO 记录

`TODO.md` 需要把“图床”描述成未来支持用户自带上传接口获取 URL，例如 WebDAV 或通用上传接口。项目不内置图床服务。

## 风险

- 本地图片文件会增长；首版不做清理，需要后续运维策略。
- 多模态历史回放会把旧图重新编码进 OpenAI 请求，成本和延迟会随图片数量增长。
- MIME type 可能无法从飞书响应直接获得；实现需从响应、文件名或字节头推断，无法判断时使用安全默认值。
