# Pydantic Settings 配置系统设计

## 目标

用 `pydantic-settings` 和其 dotenv 支持替换当前手写 YAML 配置加载。新配置系统
以环境变量 / `.env` 为主入口，代码默认值提供非敏感默认配置，不保留
`config.yaml` 或 CLI `--config` 兼容路径。

## 边界

### 修改范围

- `src/lark_agent/config.py`
- `src/lark_agent/main.py`
- `src/lark_agent/commands.py` 中配置摘要如果字段形状变化需要同步
- `tests/test_config.py`
- 受 `main.py` 参数变化影响的测试
- `pyproject.toml` / `uv.lock`
- README、`.env.example`、TODO

### 不修改范围

- Feishu WebSocket 事件处理和发送逻辑
- LLM tool loop
- MCP server 配置体系 `.agents/mcp.yaml`
- conversation JSONL 存储
- `/config set`

## 配置模型

保留内部配置分组，便于调用方继续读清晰字段：

```python
config.lark.app_id
config.lark.app_secret
config.lark.bot_id
config.llm.model
config.llm.api_key
config.llm.base_url
config.conversation.max_messages
config.data_dir
```

这些对象可以从 dataclass 迁移为 Pydantic model / settings model。关键是内部访问形状
清晰，不为旧 YAML 入口保留兼容代码。

## 环境变量

使用统一 `LARK_AGENT_` 前缀，并用双下划线 `__` 表示嵌套配置层级：

```text
LARK_AGENT_DATA_DIR=data
LARK_AGENT_LARK__APP_ID=cli_xxx
LARK_AGENT_LARK__APP_SECRET=xxx
<legacy bot id env>=ou_xxx
LARK_AGENT_LLM__API_KEY=sk-xxx
LARK_AGENT_LLM__BASE_URL=
LARK_AGENT_LLM__MODEL=gpt-4.1-mini
LARK_AGENT_CONVERSATION__MAX_MESSAGES=40
```

实现优先使用 `pydantic-settings` 标准配置映射到内部分组：

```python
SettingsConfigDict(
    env_prefix="LARK_AGENT_",
    env_file=".env",
    env_nested_delimiter="__",
)
```

`__` 只表示嵌套层级，单个 `_` 保留给字段名本身，例如 `API_KEY`、`APP_ID`、
`MAX_MESSAGES`。`.env` 和生产环境变量使用同一套公开变量名，不支持一套短名、
一套前缀名。

## 加载流程

`load_config()` 的推荐流程：

1. 实例化 Pydantic settings，settings 配置显式指定 `env_file=".env"`。
2. 如果调用方传入显式 `data_dir` 参数，用它覆盖 settings 中的 `data_dir`。
3. 将相对 `data_dir` 解析为绝对路径。
4. 返回应用内部配置对象。

## 优先级

从高到低：

1. 显式函数参数，例如 `load_config(data_dir=...)`。
2. 真实进程环境变量。
3. `pydantic-settings` 从 `.env` 读取的值。
4. 代码默认值。

真实进程环境变量必须高于 `.env`，避免 `.env` 意外覆盖生产注入值。

## CLI 变化

`python -m lark_agent.main` 不再接受 `--config`。

理由：

- 项目处于开发阶段，不保留旧 YAML 入口兼容。
- 主配置来自环境变量 / `.env`。
- 减少用户误以为仍需要同时维护 YAML 和 `.env`。

## 路径规则

`LARK_AGENT_DATA_DIR` 的默认值为 `data`。

相对 `LARK_AGENT_DATA_DIR` 建议按当前工作目录解析为绝对路径。这和环境变量 / `.env` 主路径一致，
避免继续依赖已移除的 `config.yaml` 所在目录。

## 错误处理

Pydantic validation error 应在启动阶段暴露。需要覆盖：

- `CONVERSATION_MAX_MESSAGES` 不是整数。
- `LARK_AGENT_LLM__API_KEY` 正确映射到 `config.llm.api_key`。
- `LARK_AGENT_DATA_DIR` 为空或无法合理解析时的行为。
- 缺少飞书 live bot 必需字段时，继续由 `validate_lark_config()` 给出明确缺失项。

## 文档

README 应更新为：

- 配置入口是 `.env.example -> .env` 或真实环境变量。
- `config.yaml` 不再是应用级配置方式。
- 启动命令不包含 `--config`。
- 说明真实环境变量高于 `.env`，`.env` 高于默认值。

## 迁移说明

不提供兼容代码，但 README 可以用文档说明如何从旧 `config.yaml` 手动迁移到 `.env`：

```yaml
lark:
  app_id: cli_xxx
```

迁移为：

```env
LARK_AGENT_LARK__APP_ID=cli_xxx
```

这只是文档迁移提示，不是运行时兼容层。

## 风险

- `.env` 按当前工作目录下的 `.env` 解析。README 需要建议在项目根目录启动，或在部署环境中直接注入真实环境变量。
- 移除 `--config` 会导致旧命令失败；这是符合当前项目开发阶段规则的破坏性更新。
- 测试必须隔离环境变量，避免开发者本机变量污染测试结果。
