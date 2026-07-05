# 配置实践研究

## 问题

项目是否应继续以 `config.yaml` 作为主配置入口，还是迁移到 `pydantic-settings`
的环境变量 / `.env` 模型？

## 结论

推荐迁移到环境变量 / `.env` 主路径，不保留 `config.yaml` 兼容入口。

## 依据

### Pydantic Settings

官方文档将 `BaseSettings` 描述为从环境变量加载配置的 settings 模型。字段可以有
代码默认值，环境变量提供覆盖值；`pydantic-settings` 负责类型转换和校验。

参考：<https://docs.pydantic.dev/latest/concepts/pydantic_settings/>

设计含义：

- 非敏感默认值应放在 settings class 中。
- 本地开发可以通过 `.env` 提供变量。
- 生产部署可以直接注入真实环境变量。
- YAML 可以作为自定义 source，但不是主路径所必需。
- 本项目的变量名适合使用 `env_prefix="LARK_AGENT_"` 与
  `env_nested_delimiter="__"`。双下划线专门表示嵌套层级，字段名中的单下划线
  例如 `api_key`、`max_messages` 可以保持不变。

### Dotenv

用户决策显式指定 `.env` 文件，并通过 `pydantic-settings` 的 dotenv 支持读取。
项目代码不自行实现“仓库根目录”或“配置文件邻近目录”的查找规则。

设计含义：

- settings model 指定 `env_file=".env"`。
- 真实进程环境变量优先于 `.env`，保持生产环境变量优先。
- 测试通过临时工作目录或显式环境变量隔离 `.env` 行为。

### Twelve-Factor Config

Twelve-Factor App 建议把随部署变化的配置存放在环境变量中，而不是放在代码或
分散的配置文件中。

参考：<https://12factor.net/config>

设计含义：

- 飞书凭证、LLM API key、部署差异都应走环境变量。
- 新用户不需要同时维护 YAML 和 `.env` 两套配置。

## 对本任务的要求

- `config.yaml` 应从应用级配置主路径中移除。
- README 应把 `.env.example -> .env` 写成本地开发推荐流程。
- `src/lark_agent/main.py` 应移除 `--config` 旧入口。
- `src/lark_agent/config.py` 应由 `pydantic-settings` 接管环境变量 / `.env` 解析、
  类型转换和错误报告。
