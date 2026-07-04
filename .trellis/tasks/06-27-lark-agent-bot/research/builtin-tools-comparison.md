# Research: 主流编程 Agent 内置 Tools 对比

- **Query**: Codex CLI、Claude Code、Cursor 分别有哪些内置 tools？对我们的飞书 bot 有何参考意义？
- **Scope**: external
- **Date**: 2026-07-04

## Findings

### Codex CLI (v0.136)

来源: [Codex Built-In Tool Surface](https://codex.danielvaughan.com/2026/06/03/codex-cli-built-in-tool-surface-complete-reference-shell-file-search-image-multi-agent/)、[Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)

#### 文件系统
- `read_file` — 读取文件内容
- `list_dir` — 列出目录内容
- `glob_file_search` — 按 glob 模式搜索文件
- `rg` (ripgrep) — 正则搜索文件内容

#### 文件编辑
- `apply_patch` — 所有文件修改的唯一工具，使用 patch 格式

#### 命令执行
- `shell` — 在沙箱内执行 shell 命令

#### 搜索 & 信息
- `web_search` — 网页搜索
- `tool_search` — BM25 语义搜索，搜索 agent 自身的 tool catalogue

#### 图片
- `view_image` — 查看图片
- `image_gen` — 使用 gpt-image-2 生成图片

#### 计划 & 目标
- `update_plan` — 更新任务计划
- `create_goal` / `get_goal` — Goal Mode（v0.137 GA）下的目标管理

#### 多 Agent 编排 (Multi-Agents v2)
- `spawn_agent` — 创建子 agent
- `send_input` — 向子 agent 发送消息
- `wait_agent` — 等待子 agent 完成
- `close_agent` — 关闭子 agent
- `resume_agent` — 恢复子 agent
- `spawn_agents_on_csv` — 批量创建 agent（CSV 驱动）

#### 工具管理
- MCP tools 通过 `config.toml` 配置，以 `mcp__<server>__<tool>` 命名注册
- `multi_tool_use.parallel` — 并行调用多个工具

---

### Claude Code (~45 tools, 19 unconditional)

来源: [Claude Code Internals - Tools](https://claude-code-explain.helmcode.com/tools/)、[Built-in Tools Reference](https://cc.bruniaux.com/guide/tools-reference/)、[arxiv 论文: Design Space of AI Agent Systems](https://arxiv.org/html/2604.14228v1)

总量: 通过 `assembleToolPool()` 组装，最多 54 个工具（19 个无条件，35 个按 feature flag / 用户类型条件加载），再与 MCP tools 合并。

#### 文件系统 & 代码智能
- `Read` — 读取文件（支持文本、图片、PDF、Notebook）
- `Write` — 创建或覆盖文件
- `Edit` — 字符串替换编辑
- `NotebookEdit` — Jupyter 单元格编辑
- `Glob` — 文件名模式搜索
- `Grep` — ripgrep 正则搜索
- `LSP` — 语言服务器：跳转定义、查找引用、类型错误

#### 命令执行
- `Bash` — 执行 shell 命令（需权限）
- `PowerShell` — Windows 原生支持
- `Monitor` — 后台命令流式输出（v2.1.98+）
- `REPL` — 交互式环境（conditional）

#### 网络
- `WebSearch` — 网页搜索
- `WebFetch` — 抓取 URL 并转 Markdown

#### Agent & 团队
- `Agent` — 创建子 agent（独立 context window）
- `SendMessage` — 向子 agent 或团队成员发消息
- `Workflow` — 编排多个子 agent 的动态工作流
- `TeamCreate` / `TeamDelete` — Agent 团队管理（experimental）

#### 任务 & 计划
- `TodoWrite` — 任务清单管理
- `TaskCreate` / `TaskUpdate` / `TaskStop` / `TaskOutput` — 结构化任务管理
- `EnterPlanMode` / `ExitPlanMode` — 切换计划模式
- `EnterWorktree` / `ExitWorktree` — Git worktree 切换

#### 定时 & 自动化 (conditional)
- `CronCreate` / `CronDelete` / `CronList` — 定时任务
- `RemoteTrigger` — 远程触发

#### 用户交互 & Skill
- `AskUserQuestion` — 向用户提问
- `Brief` — 简要输出
- `SkillTool` — 加载和使用 Skill
- `SlashCommand` — 斜杠命令

#### MCP 集成
- `MCPTool` — 调用 MCP server 工具
- `ListMcpResources` / `ReadMcpResource` — MCP 资源访问
- `McpAuth` — MCP 认证

#### 权限模型
- 无 OS 级沙箱，靠规则执行（deny → ask → allow，first match wins）
- 工具分为 "Permission Required" 和 "No Permission"
- `CLAUDE_CODE_SIMPLE` 模式下只保留 Bash + Read + Edit

---

### Cursor IDE Agent

来源: [Cursor Docs - Agent Overview](https://cursor.com/docs/agent/overview)、[Learn Cursor](https://www.learncursor.dev/learn/cursor-agents/agent-overview)、[Community Forum](https://forum.cursor.com/t/agent-tools-list/31197)

#### 搜索
- `codebase_search` — 语义搜索（基于索引）
- `file_search` / `Glob` — 文件名搜索
- `grep_search` / `Grep` — 正则内容搜索

#### 文件操作
- `read_file` / `Read` — 读取文件（支持图片）
- `edit_file` / `StrReplace` — 编辑文件
- `Write` — 创建文件
- `delete_file` / `Delete` — 删除文件
- `list_dir` — 列目录

#### 命令执行
- `run_terminal_command` / `Shell` — 执行终端命令

#### 网络
- Web search — 搜索网页
- Web fetch — 抓取网页内容

#### 浏览器 (Cursor 独有)
- Browser — 导航、点击、截图，用于验证 UI 变更

#### 图片
- Image generation — 图片生成

#### 用户交互
- Ask questions — 向用户提问（支持多选）

#### 任务管理
- `TodoWrite` — 任务清单
- `Task` — 子 agent 调度（多种 subagent_type）

#### 模式
- Agent / Ask / Plan / Debug 四种模式，不同模式暴露不同 tools
- Plan 模式: 只读 + 计划
- Ask 模式: 只读 + 搜索

---

## Cross-Cutting Pattern

三个产品的内置 tools 可以归纳为 **4 层**：

```
Layer 1: 文件系统   read + write/edit + glob + grep + list_dir
Layer 2: 命令执行   shell / bash / exec
Layer 3: 信息获取   web_search + web_fetch + semantic_search
Layer 4: 编排      subagent + plan + todo + task
```

Layer 1-2 是所有编程 Agent 的基础，Layer 3-4 是增强层。

### 共性
- **所有产品的核心都是 read + write + exec + search** 四件套
- MCP 作为外部 tool 扩展机制，均已支持
- 都有某种形式的 subagent / task 编排
- 都区分"需要权限"和"不需要权限"的 tools

### 差异
- **Codex** 最重视 multi-agent 编排（6 个 agent 工具），文件编辑只有一个 `apply_patch`
- **Claude Code** tools 数量最多（~45），覆盖最广，包括 LSP、Workflow、Cron 等
- **Cursor** 独有浏览器控制（UI 验证），语义搜索基于本地索引

## Implications for Our Bot

### 与编程 Agent 的本质区别

这三个产品都是**编程 Agent**——围绕"操作代码库"设计。我们的飞书 bot 不是编程 Agent：

- 不需要 `write/edit`（bot 不修改文件）
- 不需要 `glob/grep/LSP`（bot 不搜代码）
- 不需要 `apply_patch`（bot 不写代码）
- 不需要 `subagent`（单 agent 够用）

### MVP 内置 tool 建议（调研初稿）

```
MVP:   read_file(path)  — scoped 到 project 目录，用于读取 Skills / references
V2:    + exec(command)   — 带沙箱，用于执行 Skills 脚本
V3:    按需扩展（web_search、subagent 等）
```

域能力（查数据库、调 API、发通知等）全部通过 MCP tools 提供，不内置。

### 最终收敛决策

后续 PRD/Design 已将 MVP 内置 tool 从通用 `read_file(path)` 收敛为专用
`read_skill(name, file?)`：

- `read_file(path)` 虽然通用，但 project 目录同时包含 `config.yaml`、`mcp.yaml`
  和 `conversations/` 等敏感或内部状态文件，MVP 无沙箱时安全面过大。
- `read_skill(name, file?)` 只暴露 skill name 和 skill 内 reference 文件读取能力，
  路径解析由应用内部完成，更符合 MVP 的只读 Skills 目标。
- `exec`、通用 `read_file`、写文件和搜索能力保留到具备沙箱与权限策略后的 V2+。

### 可借鉴的设计

1. **权限分层**（来自 Claude Code）：区分"自动执行"和"需确认"的 tools
2. **tool_search**（来自 Codex）：当 tools 数量多时，用 BM25 搜索找到相关 tool，避免 prompt 过长
3. **SkillTool**（来自 Claude Code）：专门的 Skill 加载工具，而非通用 read_file

## Caveats

- Cursor 的内部 tool 名称来自社区论坛整理（非官方文档），实际可能有变化
- Claude Code 的 conditional tools（35 个）依赖 feature flag，普通用户不一定可见
- Codex Multi-Agents v2 是较新功能，production 实践报告较少
- 三个产品都在快速迭代，tool 列表可能很快过时
