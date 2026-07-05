# Feishu/Lark 消息内容归一化实施计划

## 当前状态

- 已有未提交局部修复：
  - `MentionPart`
  - post `at` 转 mention part
  - router 剥离群聊开头 bot mention
  - app/command 使用归一化文本
  - 对应 regression tests
- 本实施会在这些改动基础上扩展，不回滚局部修复。

## 实施步骤

1. 扩展 `src/lark_agent/transport/base.py`
   - 增加 file/media/sticker/link/code/divider/emoji/location/summary 等 part dataclass。
   - 更新 `ContentPart` union。
   - 更新 `IncomingMessage.text_content()`，为每个 part 提供稳定可读投影。

2. 重构 `src/lark_agent/transport/lark/adapter.py`
   - 保留现有 event 基础字段解析。
   - 扩展 `_content_parts()` 支持 `research/feishu-message-content-structure.md` 中所有已知 `message_type`。
   - 将 post/interactive 展开逻辑拆成小 helper，避免一个函数承担所有 tag。
   - 保留未知类型返回 `None`。

3. 增加归一化对比日志
   - 在 `src/lark_agent/transport/lark/runner.py` 中把原始 `content` 日志改为有界预览。
   - 在 adapter 成功返回 `IncomingMessage` 后输出 `INFO` 级别对比日志。
   - 日志预览包含原始 content、归一化 part 和默认文本 projection，并统一截断。

4. 调整 router projection
   - 确认 `MessageRouter.normalized_text_content()` 对新增 part 不需要知道所有类型，只依赖默认 projection。
   - 补消息中部 mention 保留测试。

5. 更新 app/commands 如有必要
   - 保持 command handler 接收可选 normalized text。
   - 确认 LLM history 使用 normalized text，不调用原始 `to_openai_message()`。

6. 补测试
   - Adapter:
     - text mention placeholder
     - post: at/img/text/emotion/code_block/hr/media
     - image/file/folder/audio/media/sticker
     - interactive 卡片元素
     - hongbao/calendar/share_chat/share_user/system/location/video_chat/todo/vote/merge_forward
     - invalid JSON/unknown type 仍按预期处理
   - Router:
     - 群聊开头 placeholder mention 命令
     - post `MentionPart` 开头剥离
     - 消息中部 mention 保留
   - App:
     - post 图片/emoji/文本进入 LLM 的 projection。
   - Runner:
     - 原始 event content 日志被截断。
     - 归一化成功日志包含原始 content 预览、归一化 part 预览、文本 projection 预览。

7. 更新 code-spec
   - 根据最终实现同步 `.trellis/spec/backend/directory-structure.md` 中的 Feishu/Lark content contract。

## 验证命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest tests/test_lark_websocket.py tests/test_router.py tests/test_app.py
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
git diff --check
```

## 风险文件与回滚点

- `src/lark_agent/transport/base.py`: 内部 contract 改动最大；如果 tests 大面积失败，先缩小 part union 和 projection。
- `src/lark_agent/transport/lark/adapter.py`: 解析分支多；每新增类型必须有至少一个测试。
- `src/lark_agent/router.py`: 只允许处理开头 bot mention，不应承担各消息类型语义。

## 完成条件

- PRD 验收标准全部满足。
- 全量测试与 compileall 通过。
- 外部调研快照保存在 `research/feishu-message-content-structure.md`，实现依据该快照；仓库根目录的临时 `message_content.md` 不作为长期来源。
