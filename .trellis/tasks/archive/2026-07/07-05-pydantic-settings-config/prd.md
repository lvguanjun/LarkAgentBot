# Pydantic Settings 配置系统

## 目标

将当前手写 YAML 配置加载升级为基于 `pydantic-settings` 的配置系统，使项目以环境变量 / `.env` 为主要配置入口：

- settings class 中的代码默认值作为非敏感默认配置。
- `.env` / 真实环境变量作为本地和部署环境的配置入口。
- 明确、可测试的类型校验、优先级和文档说明。

核心用户价值是降低真实飞书机器人部署时的配置风险：使用者不需要同时维护 `config.yaml` 和 `.env` 两套配置；密钥不写进仓库，部署环境通过标准环境变量覆盖配置。

## 背景与已确认事实

- 当前配置由 `src/lark_agent/config.py` 手写 dataclass 和 YAML 解析实现，字段包括 `data_dir`、`lark.app_id`、`lark.app_secret`、`lark.bot_id`、`llm.model`、`llm.api_key`、`llm.base_url`、`conversation.max_messages`。证据：`src/lark_agent/config.py:10`。
- 当前 `load_config(path="config.yaml", data_dir=None)` 会读取 YAML，并支持调用方通过参数覆盖 `data_dir`。证据：`src/lark_agent/config.py:37`。
- 当前相对 `data_dir` 会按 `config.yaml` 所在目录解析，而不是固定按进程工作目录解析。证据：`src/lark_agent/config.py:40`。
- 当前 CLI 只暴露 `--config` 参数，默认读取 `config.yaml`。证据：`src/lark_agent/main.py:49`。
- 当前测试只覆盖 YAML 读取、`data_dir` 参数覆盖和相对路径解析。证据：`tests/test_config.py:6`。
- 当前 README 已将真实飞书配置写成 `config.yaml` 示例，并提示 `lark.app_secret`、`llm.api_key` 等敏感值不要提交。证据：`README.md:134`。
- 当前依赖中没有 `pydantic` 或 `pydantic-settings`。证据：`pyproject.toml:10`。
- 项目处于开发阶段，根目录 `AGENTS.md` 规定不实现任何形式的向后兼容代码路径；所有改动应遵循当前最佳实践并保持全量最新。
- Pydantic Settings 官方基础用法是：继承 `BaseSettings` 后，未通过初始化参数传入的字段会从环境变量读取，没有匹配环境变量时使用默认值。参考：Pydantic Settings 官方文档 <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>。
- Pydantic Settings 官方支持 `env_prefix` 和 `env_nested_delimiter`。使用双下划线作为嵌套分隔符可以把层级分隔和字段名里的单下划线分开，避免把 `API_KEY`、`APP_ID`、`MAX_MESSAGES` 这类字段继续误拆。参考：Pydantic Settings 官方文档 <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>。
- Pydantic Settings 支持自定义 source，因此 YAML 可以实现为额外配置源；但这不是必须路径，也会增加“YAML + `.env` 两套配置”的使用者心智负担。
- Twelve-Factor App 对会随部署变化的配置建议使用环境变量，而不是分散的配置文件。参考：<https://12factor.net/config>。
- 用户已决策：`.env` 文件显式指定为当前工作目录下的 `.env`，由 `pydantic-settings` 的 dotenv 支持读取；不在本项目内自行设计 `.env` 目录发现规则。

## 第一性原理

问题不是“YAML 是否足够好”，而是“真实部署是否需要两套配置源”。如果使用者既要维护 YAML 又要维护 `.env`，配置系统就比当前更难理解。

必须成立的事实：

- 机器人启动前需要拿到飞书凭证和 LLM 凭证。
- 密钥不应提交到 Git。
- 本地开发者需要一个容易复制和理解的配置路径，最好只填一个文件。
- 生产环境通常通过环境变量注入密钥和部署差异。
- 当前代码已有 `AppConfig`、`LarkConfig`、`LLMConfig`、`ConversationConfig` 作为内部配置对象；实现可以保留等价字段访问形状以减少无关改动，但不得为了兼容旧 YAML 配置路径保留过时入口。

由此推导出的最小方案：使用 `pydantic-settings` 从真实环境变量、指定 `.env` 文件和代码默认值构建配置；不要继续把 YAML 作为新用户的主配置路径。

## 需求

### R1. 移除 YAML 配置入口

实现后，应用级配置不再从 `config.yaml` 读取，也不保留 YAML fallback。`src/lark_agent/main.py` 不应继续暴露 `--config` 作为旧 YAML 配置入口。

内部代码可以继续使用 `config.lark.app_id`、`config.llm.api_key` 等字段访问形状，以保持代码结构清晰；这属于内部重构边界，不是对旧配置文件的兼容。

### R2. 环境变量 / `.env` 作为主配置入口

`.env.example` 应成为新用户复制和填写配置的主入口。代码中的 settings 默认值提供非敏感默认配置，例如 `data_dir`、`llm.model`、`conversation.max_messages`。

### R3. 支持 `.env` 文件

项目应提供 `.env.example`，展示所有可用环境变量名和用途。真实 `.env` 文件不应提交。

`.env` 文件应通过 `pydantic-settings` 显式指定为 `.env`。该路径按进程当前工作目录解析，不在项目代码中自行实现“仓库根目录”或“配置文件邻近目录”的查找规则。

### R4. 支持真实环境变量覆盖

真实环境变量应能覆盖 `.env` 中的同名配置。覆盖范围至少包括：

- `data_dir`
- `lark.app_id`
- `lark.app_secret`
- `lark.bot_id`
- `llm.model`
- `llm.api_key`
- `llm.base_url`
- `conversation.max_messages`

### R5. 明确配置优先级

配置优先级必须可测试、可文档化。推荐优先级为：

1. 显式函数参数，例如当前已有的 `data_dir` 参数。
2. 真实进程环境变量。
3. `pydantic-settings` 从 `.env` 读取的值。
4. 代码默认值。

### R6. 增加类型校验和错误可读性

无效配置应在启动前失败，并给出可定位的错误。至少覆盖：

- `conversation.max_messages` 必须能解析为整数。
- `.env` 或真实环境变量中的无效值要失败，而不是静默吞掉。

### R7. 更新文档

README 中的配置说明和 live bot 启动说明应改为环境变量 / `.env` 优先的推荐实践：

- `.env` 或生产环境变量作为主配置入口，`.env` 由 `pydantic-settings` 指定读取。
- `.env.example` 作为可复制模板。
- 默认配置来自 settings class，而不是要求用户维护第二个配置文件。
- 说明最终优先级和常见排错路径。

### R8. 测试覆盖

测试必须覆盖：

- 未设置环境变量时使用代码默认值。
- `.env` 可以填充所有需要用户配置的字段。
- 真实环境变量优先于 `.env`。
- 显式 `data_dir` 参数仍优先于其他来源。
- 相对 `data_dir` 的解析规则与新的主配置入口一致，并在 README 中说明。
- 无效类型会报错。

## 非目标

- 不在本任务中实现 `/config set`。
- 不在本任务中设计运行时配置写回。
- 不在本任务中接入 secret manager、Kubernetes Secret、systemd EnvironmentFile 或容器部署说明。
- 不要求迁移 MCP server 的 `.agents/mcp.yaml` 配置体系；MCP server 自身已有 env 引用解析逻辑。
- 不改变 Feishu WebSocket、LLM 调用、router 或 conversation 行为。
- 不要求新用户同时维护 `config.yaml` 和 `.env`。
- 不保留 `config.yaml` 或 `--config` 的向后兼容路径。

## 验收标准

- [ ] `pyproject.toml` 和 lockfile 增加 Python 3.13 兼容的 `pydantic-settings` 与 `python-dotenv` 依赖。
- [ ] `load_config()` 使用 `pydantic-settings` 管理 `.env`、真实环境变量、类型转换和校验。
- [ ] 移除应用级 `config.yaml` 读取路径和 CLI `--config` 旧入口。
- [ ] 内部配置对象提供清晰的 `lark`、`llm`、`conversation` 分组字段访问。
- [ ] 新增 `.env.example`，包含所有当前应用级配置字段对应的环境变量。
- [ ] README 将 `.env` / 环境变量写成主配置入口，并说明真实环境变量、`.env`、显式参数和默认值之间的优先级。
- [ ] 测试覆盖 R8 中列出的配置加载场景。
- [ ] `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` 通过。
- [ ] `UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src` 通过。

## 已决策

### D1. 不保留 `config.yaml` 兼容路径

用户已决策：项目处于开发阶段，不保留 `config.yaml` 或 `--config` 的向后兼容路径。配置系统直接迁移到 `pydantic-settings` + `python-dotenv` + 环境变量的当前最佳实践形态。

### D2. 环境变量命名风格

用户已决策：使用统一 `LARK_AGENT_` 前缀，并使用双下划线 `__` 表示嵌套配置层级，例如：

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

决策原因：

- 和内部配置分组 `lark.app_id`、`llm.api_key`、`conversation.max_messages`
  的对应关系更直观。
- `LARK_AGENT_` 前缀降低真实进程环境变量命名冲突风险。
- `.env` 和生产环境变量使用同一套公开变量名，避免两套配置名。
- `.env.example` 更适合作为给使用者复制的配置清单。
- 实现优先使用 `pydantic-settings` 标准配置：
  `env_prefix="LARK_AGENT_"`、`env_nested_delimiter="__"`。这样不需要为每个字段手写
  alias，也能让 `API_KEY`、`APP_ID`、`MAX_MESSAGES` 中的单下划线保留为字段名的一部分。

### D3. `.env` 文件路径

用户已决策：显式指定 dotenv 文件为 `.env`。实现使用 `pydantic-settings` 的 dotenv
配置能力，不自行搜索父目录或配置文件相邻目录。
