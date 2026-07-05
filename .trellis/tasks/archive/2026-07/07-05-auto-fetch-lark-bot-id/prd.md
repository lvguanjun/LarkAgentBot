# 自动获取 Lark 机器人 ID

## Goal

启动真实飞书机器人时，不再要求用户手动在 `.env` 中维护机器人 ID。应用应使用已有 `LARK_AGENT_LARK__APP_ID` 和
`LARK_AGENT_LARK__APP_SECRET` 调用飞书「获取机器人信息」接口，取返回的
`bot.open_id` 作为内部 mention 路由使用的机器人 ID。

这样可以减少首次配置步骤，也避免 `.env` 中 bot id 和飞书实际机器人身份不一致。

## Confirmed Facts

- 规划时 `src/lark_agent/main.py` 在启动时通过 `validate_lark_config()` 要求
  `lark.app_id`、`lark.app_secret` 和 `lark.bot_id` 均存在。
- 现有 `BotApp` 会用 `config.lark.bot_id` 初始化 `MessageRouter`，用于判断群聊
  mention 是否命中机器人。
- 已新增并验证 `src/lark_agent/transport/lark/bot_info.py`，可通过 `lark-oapi`
  通用 `Client.request(BaseRequest)` 调用 `https://fsopen.bytedance.net/open-apis/bot/v3/info`
  并解析 `bot.open_id`。
- 规划时 `README.md` 仍说明手动运行脚本后把机器人 ID 写回 `.env`，
  需要随启动逻辑调整。

## Requirements

- 启动入口 `python -m lark_agent.main` 只强制要求 `lark.app_id` 和
  `lark.app_secret`。
- 启动构建 runner 时自动调用飞书 bot info 接口，使用返回的 `bot.open_id` 作为
  运行时 `config.lark.bot_id`。
- 获取 bot info 失败、返回非 0 code 或缺少 `bot.open_id` 时应快速失败，并保留
  清晰错误信息。
- 保留手动 `python -m lark_agent.transport.lark.bot_info` 脚本，作为配置诊断工具。
- `README.md` 需要改为说明机器人 ID 已不需要手动配置；手动脚本
  仅用于排查机器人身份。
- `.env.example` 不应包含机器人 ID 环境变量。
- `load_config()` 不应从环境变量或 `.env` 读取机器人 ID；运行时值只能由 bot info
  API 注入。
- 不引入新的配置格式或兼容旧配置路径。

## Acceptance Criteria

- [x] `validate_lark_config()` 不再因缺少 `lark.bot_id` 报错，但仍要求
  `lark.app_id` 和 `lark.app_secret`。
- [x] `build_runner()` 会把获取到的 bot `open_id` 注入 `BotApp` 使用的配置。
- [x] 单元测试覆盖自动获取 bot id 的 runner 构建路径，且不访问真实飞书网络。
- [x] 手动 bot info 脚本测试继续通过。
- [x] README 的配置和启动说明与新行为一致。
- [x] `.env.example` 不包含机器人 ID 环境变量。
- [x] 配置加载测试覆盖旧机器人 ID 环境变量不会进入 `config.lark.bot_id`。
- [x] 仓库中不再出现旧机器人 ID 环境变量名。
- [x] 后端测试和编译检查通过。
