# 运行时 data 目录 Git 忽略与模板迁移

## Goal

消除运行时 `data/` 目录误提交风险，将可提交的默认资源迁移到 `templates/defaults/`，让真实群组消息、本地默认配置、个人偏好和潜在敏感 MCP 配置默认不进入 Git。

用户价值：开发者可以安全运行飞书机器人，不会因为 `git status` 或误操作把群聊/私聊历史、群组配置、本地默认人格或连接配置提交到仓库。

## Background

- 父任务已决策：`data/` 是本地运行时目录，整体不上仓；默认资源模板统一放在 `templates/defaults/`。
- 当前 `.gitignore:1` 到 `.gitignore:6` 只忽略虚拟环境、缓存和 Python 产物，尚未忽略 `data/`。
- 当前 Git 已追踪的 `data/` 文件只有 `data/defaults/AGENTS.md`。
- `README.md:42` 到 `README.md:66` 描述运行时数据写入 `data/`，其中对话历史位于 `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`。
- 父任务 R9 约定对话历史持久化到 `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl`；这类文件可能包含真实群组消息。

## Requirements

### R1: 忽略运行时数据

- `.gitignore` 必须忽略整个运行时 `data/` 目录。
- 新生成的 `data/groups/<chat_id>/conversations/<thread_id>/history.jsonl` 不应出现在 `git status --short` 中。
- 本地修改 `data/defaults/AGENTS.md` 不应出现在 `git status --short` 中。

### R2: 迁移可提交默认资源模板

- 当前已追踪的默认资源 `data/defaults/AGENTS.md` 必须迁移到 `templates/defaults/AGENTS.md`。
- `templates/defaults/` 的目录结构必须对应运行时 `data/defaults/`，方便开发者复制初始化。
- 模板内容必须去标识化，不包含真实群组消息、真实群组配置、真实 MCP 密钥或个人化默认人格。

### R3: 文档说明初始化流程

- README 必须说明 `data/` 是本地运行时目录，不应提交。
- README 必须说明从 `templates/defaults/` 初始化本地 `data/defaults/` 的方式。
- README 中的目录结构示例必须区分“仓库模板目录”和“本地运行时目录”。

## Acceptance Criteria

- [x] `data/` 被 `.gitignore` 忽略。
- [x] `data/defaults/AGENTS.md` 不再作为可提交默认资源保留在运行时路径，提交后将从 Git 追踪集中移除。
- [x] `templates/defaults/AGENTS.md` 作为新的去标识化默认助手模板加入仓库。
- [x] 创建 `data/groups/chat-1/conversations/thread-1/history.jsonl` 后，`git status --short` 不列出该文件。
- [x] `git check-ignore -v --no-index data/defaults/AGENTS.md` 确认本地默认资源路径会被 `data/` 规则忽略。
- [x] README 说明模板复制到本地运行时 defaults 的流程。
- [x] 现有测试通过：`UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`。

## Out of Scope

- 不改变运行时代码查找路径：代码仍读取 `data/defaults/` 和 `data/groups/`。
- 不实现自动初始化命令；本任务只提供模板和 README 手动步骤。
- 不修改 MCP 功能、飞书 WebSocket 功能或管理命令。

## Notes

- 这是轻量子任务，PRD-only 足够。
- 实现时需要注意 Git 已追踪文件不会仅因 `.gitignore` 自动停止追踪；必须通过 Git 索引迁移让 `data/defaults/AGENTS.md` 变为 `templates/defaults/AGENTS.md`。
- 该任务应先于 MCP 子任务完成，避免后续 MCP 配置模板或本地配置继续落在运行时 `data/` 路径中。
