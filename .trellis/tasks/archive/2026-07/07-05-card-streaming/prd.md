# 飞书卡片消息流式输出与表情交互

## Goal

将 bot 回复从纯文本消息升级为飞书卡片消息，支持 CardKit 流式输出 LLM 响应，并在收到消息时通过表情回复让用户知道 bot 正在处理。

## Background

当前 bot 使用纯文本消息回复（`send_text`），存在以下问题：
- 用户发消息后无即时反馈，不知道 bot 是否在处理
- 回复不支持 markdown 渲染（代码块、表格等）
- 长回复需要等 LLM 全部输出完才能看到

飞书提供了 CardKit 流式更新 API，可以实现类似 ChatGPT 的打字机效果。

## Requirements

### R1: 消息接收表情反馈

- 收到用户消息并决定响应后，立即给用户消息添加 emoji 表情（`Typing`）
- 处理完成后，移除处理中表情，添加完成表情（`DONE`）
- 表情操作失败不应阻塞主流程（静默降级）

### R2: 卡片消息回复

- bot 回复改用飞书交互式卡片（`interactive` 类型），使用 JSON 2.0 schema
- 卡片不使用 header，直接展示 markdown 内容体
- 卡片包含 markdown 组件，支持渲染 LLM 输出中的标题、列表、代码块、粗体等
- 管理命令（`/help` 等）的回复仍用纯文本，不改为卡片

### R3: CardKit 流式输出

- 使用 CardKit 流式 API（创建卡片实体 → 发送卡片 → 流式更新文本 → 关闭流式模式）
- LLM 改为 streaming 调用，token 到达后累积文本，每 300-500ms 调用 CardKit content API 更新
- 流式更新使用全量文本（非增量），sequence 严格递增
- 流式结束后关闭 streaming_mode，做一次兜底更新确保内容完整
- 对未闭合的 markdown 标记（如代码块 ```）在发送前自动补全

### R4: 工具调用状态展示

- LLM 进行 tool call 时，在卡片 markdown 底部追加状态提示（如 `> 🔧 正在调用: tool_name`）
- tool call 完成后移除该状态提示，继续展示后续 LLM 输出
- 流式完成后最终卡片不包含工具调用的中间状态文本

### R5: 长内容处理

- 如果累积文本接近 30 KB 卡片限制，截断并在末尾追加提示"⚠️ 内容过长已截断"
- 不做分条消息补发（后续迭代再考虑）

### R6: 错误处理

- 未注入 `card_streamer` 时，使用纯文本回复（兼容未配置 CardKit 的场景）
- CardKit API 运行时失败（权限缺失、网络异常等）直接 log error，不静默降级为文本
- 表情操作失败不阻塞主流程（静默降级）

## Non-requirements

- 卡片中的交互按钮（如审批、确认）— 后续迭代
- 折叠面板展示工具调用详情 — 后续迭代（streaming_mode 下不支持非文本组件更新）
- 分条消息补发超长内容 — 后续迭代
- 卡片模板管理 — 使用内联 JSON，不引入模板系统

## Constraints

- 飞书 JSON 2.0 卡片需要客户端版本 ≥ 7.20
- `streaming_config` 需要客户端版本 ≥ 7.23
- 卡片体积上限 30 KB，最多 200 个元素
- CardKit 单卡片操作频率上限 10 次/秒（streaming_mode 下不计入全局 QPS）
- 需要新增应用权限：`cardkit:card:write`

## Acceptance Criteria

- [ ] 收到消息后 500ms 内给消息添加 Typing 表情
- [ ] bot 回复使用卡片消息，markdown 正确渲染（标题、代码块、列表）
- [ ] LLM 流式输出时卡片内容实时更新，具有打字机效果
- [ ] 工具调用期间卡片显示工具调用状态
- [ ] LLM 输出完成后卡片内容完整，无残留状态文本
- [ ] 完成后 Typing 表情被替换为 DONE 表情
- [ ] 未注入 card_streamer 时使用纯文本回复
- [ ] 管理命令仍使用纯文本回复
- [ ] 现有测试不被破坏
