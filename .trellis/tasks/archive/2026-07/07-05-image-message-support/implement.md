# 图片消息支持实施计划

## 实施步骤

1. 更新 transport/core 边界
   - 在 `transport/base.py` 增加 SDK-independent 图片下载结果和下载器协议。
   - 给 router 增加结构化 parts 规范化方法，复用现有群聊开头 bot mention 去除规则。

2. 增加图片内容模块
   - 新增核心模块负责保存本地图片、生成 `image_ref`、把 `image_ref` 扩展为 OpenAI `image_url`。
   - 失败下载或失败回放时生成文本占位。
   - 使用二进制文件存储，不把 base64 写入 `history.jsonl`。

3. 接入 BotApp
   - 给 `BotApp` 注入可选 `ImageDownloader`。
   - 普通 LLM 路径构造多模态 current turn。
   - 历史上下文在调用 LLM 前扩展图片引用。
   - 管理命令路径继续只用文本投影，不下载图片。

4. 接入飞书下载器
   - 在 `transport/lark/` 增加下载器实现。
   - 在 `main.build_runner()` 中复用现有 Lark client 注入下载器。
   - 失败时抛出清晰异常，由核心图片组装逻辑降级。

5. 更新 TODO 和测试
   - 更新 `TODO.md`：当前图片 vision 支持完成后，记录未来用户自带上传接口获取 URL。
   - 更新现有图片占位测试，新增成功下载、失败下载、post 图文顺序、命令不下载、历史回放扩展测试。

## 验证命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

## 回滚点

- 如果飞书下载器 SDK 接口不匹配，先保留核心可注入下载器和测试 fake downloader，飞书真实下载器可单独回滚。
- 如果多模态历史扩展影响 tool call 历史，回滚 app 上下文扩展路径，保留 current turn 多模态支持。

## 检查项

- `history.jsonl` 中不能出现 `data:image/` 或长 base64 字符串。
- Fake LLM 收到的消息可以包含 `image_url` data URL。
- 没有新增 `lark-oapi` import 到核心模块。
- 图片失败路径可测试且不会吞掉整条文本消息。
