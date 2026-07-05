# Pydantic Settings 配置系统实施计划

## 前置检查

- 读取 `.trellis/spec/backend/index.md`。
- 读取 `.trellis/spec/backend/quality-guidelines.md`。
- 读取 `.trellis/spec/backend/directory-structure.md`。
- 读取 `.trellis/spec/guides/index.md`。

## 实施步骤

1. 添加依赖
   - 使用 `uv add --python 3.13 pydantic-settings python-dotenv` 更新 `pyproject.toml`
     和 `uv.lock`。

2. 重写配置模型
   - 在 `src/lark_agent/config.py` 中引入 `pydantic-settings`。
   - 移除 YAML 读取和 `_read_yaml` / `_mapping`。
   - 定义 settings 模型，使用 `env_prefix="LARK_AGENT_"`、
     `env_nested_delimiter="__"` 映射嵌套配置。
   - 保持内部 `config.lark.*`、`config.llm.*`、`config.conversation.*` 分组访问。
   - 使用 settings 配置指定 `env_file=".env"`，并处理显式 `data_dir` 覆盖。

3. 更新 CLI
   - 移除 `src/lark_agent/main.py` 中的 `--config` 参数。
   - 改为 `load_config()` 无参数加载。

4. 新增 `.env.example`
   - 覆盖 `LARK_AGENT_DATA_DIR`、`LARK_AGENT_LARK__*`、`LARK_AGENT_LLM__*`、
     `LARK_AGENT_CONVERSATION__MAX_MESSAGES`。
   - 使用占位值，不写真实密钥。

5. 更新 README
   - 移除 `config.yaml` 主配置说明。
   - 增加 `.env.example -> .env` 流程。
   - 更新 live bot 启动命令。
   - 说明配置优先级和旧 YAML 到 `.env` 的手动迁移方式。

6. 更新测试
   - 替换 YAML 加载测试。
   - 增加默认值测试。
   - 增加 `.env` 加载测试。
   - 增加真实环境变量覆盖 `.env` 测试。
   - 增加 `LARK_AGENT_LLM__API_KEY` / `LARK_AGENT_CONVERSATION__MAX_MESSAGES`
     这类双下划线嵌套映射测试。
   - 增加显式 `data_dir` 覆盖测试。
   - 增加无效整数值报错测试。
   - 更新受 `--config` 移除影响的 main-entry 测试。
   - 测试中使用 `monkeypatch` 隔离相关环境变量。

7. 清理旧文件引用
   - 搜索 `config.yaml`、`--config`、`yaml`、`PyYAML`。
   - 如果应用级配置不再使用 `PyYAML`，评估是否移除 `pyyaml` 依赖；注意 MCP 或其他模块是否仍需要 YAML。
   - 删除仓库根 `config.yaml` 旧示例文件，避免误导用户继续使用 YAML 配置入口。

## 验证命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest
UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src
```

## 回滚点

- 依赖添加后，如果实现失败，可先回滚 `config.py`、`main.py`、README 和测试，再决定是否保留依赖更新。
- 删除 `config.yaml` 前确认 README 和测试不再引用它。

## 完成标准

- PRD 验收标准全部满足。
- 没有应用级 YAML 配置读取路径。
- README 不再要求用户维护两套配置。
- 测试在隔离环境变量后稳定通过。
