# 更新 Python 版本要求和直接依赖版本

## 目标

将项目的 Python 版本要求提升到 `>=3.13`，并把 `pyproject.toml` 中声明的运行时直接依赖和开发直接依赖版本约束更新为当前默认包源可获取的最新稳定版本，使项目配置和锁文件共同反映新的运行基线。

## 背景与已确认事实

- 当前 `pyproject.toml` 的 `[project] requires-python` 是 `>=3.11`。
- 当前 `pyproject.toml` 的 `[project] dependencies` 包含：
  - `lark-oapi>=1.4.0`
  - `mcp>=1.0.0`
  - `openai>=1.0.0`
  - `PyYAML>=6.0.0`
- `[project.optional-dependencies] dev` 当前包含：
  - `pytest>=8.0.0`
  - `pytest-asyncio>=0.23.0`
- 项目根目录存在 `uv.lock`。
- 用户已确认本任务只更新直接依赖，不手动处理间接依赖。
- 用户已确认开发直接依赖也要更新。
- 用户已确认最终提交需要包含 `uv.lock` 更新。
- 用户已确认后续所有开发改动如需新增或升级库，不应拘泥于 `pyproject.toml` 里的旧版本约束；应按 Python 3.13 通过 `uv` 获取可用的最新稳定版本，不凭模型知识写死版本。
- 仓库现有验证命令包含：
  - `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`
  - `UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src`

## 需求

- 将 `pyproject.toml` 中的 Python 版本要求更新为 `>=3.13`。
- 将 `pyproject.toml` 中 `[project] dependencies` 的直接依赖版本约束更新为默认包源可获取的最新稳定版本。
- 将 `pyproject.toml` 中 `[project.optional-dependencies] dev` 的直接开发依赖版本约束更新为默认包源可获取的最新稳定版本。
- 不手动编辑间接依赖。
- 使用 `uv sync --extra dev` 或等效 `uv` 解析流程同步更新 `uv.lock`。
- 遵守 `.trellis/spec/backend/quality-guidelines.md` 的依赖管理规范：新增或升级依赖时通过 `uv` 按 Python 3.13 解析版本，不根据已有版本约束或记忆手写版本。
- 最终提交必须包含 `pyproject.toml` 和 `uv.lock` 的变更。

## 技术说明

- `uv.lock` 不会因为单独编辑 `pyproject.toml` 自动变化；需要运行 `uv sync --extra dev`、`uv lock` 或等效 `uv` 解析流程刷新锁文件。
- 本任务不手动指定或编辑间接依赖版本；间接依赖由 `uv` 根据新的直接依赖约束解析并写入 `uv.lock`。
- 当前任务以及后续开发中，如需新增或更新直接依赖，应优先使用 `UV_CACHE_DIR=.uv-cache uv add --python 3.13 ...`、`UV_CACHE_DIR=.uv-cache uv add --python 3.13 --optional dev ...` 或等效 `uv` 命令解析版本。
- 实现完成后需要检查测试和编译情况。

## 验收标准

- [x] `pyproject.toml` 的 `requires-python` 为 `>=3.13`。
- [x] `pyproject.toml` 的运行时直接依赖版本约束已更新到执行时可获取的最新稳定版本。
- [x] `pyproject.toml` 的开发直接依赖版本约束已更新到执行时可获取的最新稳定版本。
- [x] 依赖版本更新遵守 `.trellis/spec/backend/quality-guidelines.md` 中的 Python 3.13 解析基线。
- [x] 没有手动修改间接依赖声明。
- [x] `uv.lock` 已通过 `uv` 解析流程同步更新，并包含在最终变更中。
- [x] `uv sync --extra dev` 或等效同步命令执行成功。
- [x] `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` 执行成功。
- [x] `UV_CACHE_DIR=.uv-cache uv run --extra dev python -m compileall src` 执行成功。
