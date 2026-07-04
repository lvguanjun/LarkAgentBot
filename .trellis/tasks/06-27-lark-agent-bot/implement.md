# Implementation Plan

## Phase 1: 基础骨架

### 1.1 项目初始化
- [ ] 创建 `pyproject.toml`，声明依赖：`lark-oapi`, `openai`, `mcp`, `pyyaml`
- [ ] 创建包结构 `src/lark_agent/`
- [ ] 创建全局配置 `config.yaml` 和 `src/lark_agent/config.py`

### 1.2 Transport Layer
- [ ] `transport/base.py`: `IncomingMessage` 数据类 + `MessageSender` 协议
- [ ] `transport/websocket.py`: 飞书 WebSocket 长连接实现
- [ ] 验证：能收到飞书消息并打印

### 1.3 消息路由
- [ ] `router.py`: 触发规则判断 (@ 检测、话题激活状态、私聊识别)
- [ ] 验证：群聊 @时响应，不 @时忽略

## Phase 2: 核心对话能力

### 2.1 Project & Conversation
- [ ] `project.py`: Project 类，管理群组目录和配置 fallback
- [ ] `conversation.py`: JSONL 读写、滑动窗口截断（按完整轮次）
- [ ] `agents_conf.py`: AGENTS.md 加载

### 2.2 LLM Client
- [ ] `llm_client.py`: OpenAI 兼容 API 调用，含 tool 循环
- [ ] 验证：能与 LLM 对话，history 正确持久化

### 2.3 端到端对话
- [ ] `main.py`: 串联所有组件
- [ ] 验证：飞书中 @机器人能完成多轮对话，话题内上下文保持

## Phase 3: Skills & MCP

### 3.1 Skills
- [ ] `skills.py`: SKILL.md frontmatter 解析、三层加载、system prompt 注入
- [ ] 创建 `data/defaults/skills/` 示例 skill
- [ ] 验证：skills 列表出现在 system prompt，LLM 可引用

### 3.2 MCP
- [ ] `mcp_manager.py`: MCP Client 连接管理、tools 发现、tool 执行
- [ ] tools → OpenAI function 格式转换
- [ ] 验证：配置 MCP server 后 LLM 能调用工具

## Phase 4: 管理指令

### 4.1 Commands
- [ ] `commands.py`: `/help`, `/config`, `/skill list`, `/mcp list`, `/reset`
- [ ] 验证：管理指令能正确执行并返回结果

## Validation Commands

```bash
# 安装依赖
pip install -e .

# 启动机器人
python -m lark_agent.main

# 验证配置
python -c "from lark_agent.config import load_config; print(load_config())"
```

## Risky Areas

- 飞书 WebSocket 长连接的稳定性和重连机制
- MCP stdio transport 的进程管理（子进程生命周期、异常处理）
- 滑动窗口截断 tool_call/tool_result 配对的边界情况
- 并发消息处理（同一话题多人同时发消息）
