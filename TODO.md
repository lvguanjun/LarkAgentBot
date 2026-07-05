# TODO

这个文件是开发者备忘录，用来记录项目初期实现中还没做、暂缓做、已经完成的粗粒度事项。

它不是 PRD、设计文档或执行计划。准备开始其中某一项时，再单独创建 Trellis task。

## 下一步推荐

- [x] 管理命令：`/help`、`/config`、`/skill list`、`/mcp list`、`/reset`

## 待办

- [x] 补充 live bot 真实飞书配置与启动说明
- [ ] 为 `/config set` 设计安全的白名单字段
- [ ] Webhook 接入
- [ ] 图片下载、OCR 或 vision 模型支持
- [ ] 飞书卡片消息和交互
- [ ] 生产部署说明：systemd、容器镜像或其他部署方式

## 暂不做

- [ ] Skills 脚本执行
- [ ] 通用 `exec` / `write_file` 内置工具
- [ ] 通用文件读取工具
- [ ] 用户级权限控制
- [ ] 跨进程或重启后的持久化事件去重

## 已完成

- [x] Python 包骨架、配置加载和测试基础设施
- [x] Transport-independent bot core
- [x] 群组/私聊到 Project 的目录映射
- [x] 话题到 Conversation 的 JSONL 持久化
- [x] AGENTS.md fallback system prompt
- [x] Skills 发现和 `read_skill`
- [x] OpenAI-compatible tool loop
- [x] MCP 配置加载、tool 发现和调用
- [x] 运行时 `data/` Git ignore 和默认资源模板
- [x] Feishu WebSocket 长连接适配、消息转换和文本回复
