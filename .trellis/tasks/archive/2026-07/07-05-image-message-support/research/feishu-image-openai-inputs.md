# Research: Feishu/Lark image resources to OpenAI image inputs

- Query: Can Feishu/Lark bot-message image resources be exposed as public URLs for OpenAI `image_url`, or should the bot download via Feishu APIs and send Base64/data URLs to OpenAI?
- Scope: mixed
- Date: 2026-07-05

## Findings

### Decision

Use Feishu/Lark authenticated download APIs, then send OpenAI a Base64 data URL for the current image turn.

I found no Feishu/Lark evidence that inbound bot-message image keys become public, unauthenticated URLs. The evidence points the other way: message content carries `image_key` / `file_key` identifiers, while the Lark OpenAPI SDK exposes download endpoints that return binary streams (`IO[Any]`) plus optional filename, not a shareable URL.

### Feishu/Lark API evidence

- Official Feishu Open Platform page `Download image - Server API - Feishu Open Platform`: `https://open.feishu.cn/document/server-docs/im-v1/image/get`. The page shell was accessible but not line-readable in this environment; the generated SDK below gives the exact endpoint contract.
- SDK version in this repo: `pyproject.toml` requires `lark-oapi>=1.7.0`; installed package inspected at `.venv/lib/python3.13/site-packages/lark_oapi`.
- `GetImageRequest` uses `GET /open-apis/im/v1/images/:image_key` and tenant token auth: `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/get_image_request.py:22`.
- The image API successful response is handled as binary bytes in `response.file = io.BytesIO(resp.content)` with `file_name` parsed from headers, not a URL: `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/resource/image.py:77`.
- `GetImageResponse` only models `file` and `file_name`: `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/get_image_response.py:8`.
- `GetMessageResourceRequest` uses `GET /open-apis/im/v1/messages/:message_id/resources/:file_key`, supports tenant or user token auth, and includes a `type` query parameter: `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/get_message_resource_request.py:24`.
- The message resource API also returns binary bytes in `response.file = io.BytesIO(resp.content)` plus `file_name`, not a URL: `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/resource/message_resource.py:59`.
- `GetMessageResourceResponse` only models `file` and `file_name`: `.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/get_message_resource_response.py:8`.

Practical implication: for an inbound image message with `image_key`, the simplest path is probably `im.v1.image.aget(GetImageRequest.image_key(...))`. For rich post/image content where Feishu semantics require message-scoped resource lookup, the alternative is `im.v1.message_resource.aget(GetMessageResourceRequest.message_id(...).file_key(...).type("image"))`. Both paths are authenticated downloads, not URL generation.

### OpenAI input evidence

- OpenAI official "Images and vision" docs show Chat Completions accepts `content` arrays containing `{"type": "image_url", "image_url": {"url": ...}}` with a fully-qualified image URL: `https://developers.openai.com/api/docs/guides/images-vision` lines 932-945.
- The same official docs show Chat Completions with `image_url.url` set to a Base64 data URL such as `data:image/jpeg;base64,...`: lines 1101-1112.
- The docs explicitly list image input methods: fully qualified URL, Base64-encoded data URL, or File API file ID: lines 1165-1169.
- Responses API has the parallel shape `{"type": "input_image", "image_url": "data:image/jpeg;base64,..."}`: lines 1381-1391 and 1447-1457.

Practical implication for this repo, which currently uses Chat Completions, is to build a user message like:

```python
{
    "role": "user",
    "content": [
        {"type": "text", "text": "这张图说了啥"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,<downloaded bytes>"},
        },
    ],
}
```

### Repo patterns and constraints

- Transport boundary: `transport/base.py` owns SDK-independent content parts. `ImagePart` currently stores only `file_key` plus `alt_text`; no bytes, MIME type, URL, or download state: `src/lark_agent/transport/base.py:16`.
- Text projection intentionally downgrades images to `[用户发送了一张图片]`: `src/lark_agent/transport/base.py:135`.
- `IncomingMessage.to_openai_message()` currently returns a string-only content payload, so multimodal support should not rely on that helper as-is: `src/lark_agent/transport/base.py:131`.
- Lark adapter converts plain `image` messages to `ImagePart(file_key=...)`: `src/lark_agent/transport/lark/adapter.py:88`.
- Rich post `img` / `image` tags also become `ImagePart(file_key=...)`: `src/lark_agent/transport/lark/adapter.py:272`.
- `IncomingMessage` retains the parent `message_id`, which is enough to call message-resource download if needed: `src/lark_agent/transport/lark/adapter.py:40`.
- `BotApp.handle_message()` currently computes `user_text = router.normalized_text_content(message)` and sends `{"role": "user", "content": user_text}` to the LLM, so image support needs a new message-content assembly step before `turn_messages`: `src/lark_agent/app.py:52` and `src/lark_agent/app.py:70`.
- `LLMClient.complete_message()` forwards the `messages` list unchanged into `client.chat.completions.create`, so it can carry Chat Completions multimodal content arrays once `BotApp` supplies them: `src/lark_agent/llm_client.py:51`.
- `Conversation` persists arbitrary JSON dicts, so it can technically store multimodal messages, but persisting Base64 data URLs would bloat `history.jsonl`: `src/lark_agent/conversation.py:17`.
- Existing tests encode the current behavior as text downgrade: `tests/test_app.py:592`.
- Existing app tests show the image placeholder is what reaches the LLM today: `tests/test_app.py:360`.
- `LarkMessageSender` already wraps `client.im.v1.message`; an analogous downloader can wrap `client.im.v1.image` and/or `client.im.v1.message_resource` while staying inside `transport/lark`: `src/lark_agent/transport/lark/sender.py:20`.
- `main.build_runner()` builds one shared Lark client and injects the sender into `BotApp`; the same construction point can inject a Lark image downloader without adding SDK imports to core modules: `src/lark_agent/main.py:43`.
- Runner callbacks schedule `BotApp.handle_message` in the background, so downloading inside app handling does not block the SDK event callback path: `src/lark_agent/transport/lark/runner.py:68`.

### Related specs

- Backend directory structure says `transport/base.py` owns SDK-independent message/sender contracts and `transport/lark/` owns all `lark-oapi` imports: `.trellis/spec/backend/directory-structure.md`.
- Feishu/Lark transport contract says known image/file/media messages should become structured parts or summaries, and attachment parts store only Feishu-provided keys/metadata without implying download/OCR/transcription: `.trellis/spec/backend/directory-structure.md`.
- Quality guidelines require external clients to stay injectable so tests do not need live credentials or network access: `.trellis/spec/backend/quality-guidelines.md`.

## Caveats / Not Found

- I did not find a Feishu/Lark public URL API for inbound bot-message images. The official image download page was accessible only as a page title in this environment; exact endpoint/return details were verified through the installed SDK generated by Lark OpenAPI.
- Feishu may have separate file preview/share APIs in other product areas, but they are not the practical path for bot message images because OpenAI must fetch a public unauthenticated URL, while Feishu message/image downloads are token-authenticated binary APIs.
- MIME type handling is not modeled by the SDK response objects. Implementation should infer from response headers if available, otherwise from bytes or filename, and only emit supported `data:image/<type>;base64,...` URLs.
- Avoid persisting full Base64 image data in conversation history unless explicitly required; it will inflate `history.jsonl` and token context. A likely design is to send the data URL only in the current LLM turn, then persist the text/placeholder form for future context.
