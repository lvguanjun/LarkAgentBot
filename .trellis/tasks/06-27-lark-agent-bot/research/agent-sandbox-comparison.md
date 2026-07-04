# Research: Agent Sandbox & Permission Isolation

- **Query**: How do OpenClaw, Codex, and other agents handle permission isolation for tool execution?
- **Scope**: external
- **Date**: 2026-06-27

## Findings

### OpenClaw

OpenClaw (CherryHQ/cherry-studio ecosystem) implements a layered permission architecture with three orthogonal controls:

#### 1. Sandbox (where tools run)
- Configuration: `agents.defaults.sandbox` or per-agent `agents.list[].sandbox`
- **Modes**: `off` (tools run on host), `non-main` (only non-main sessions sandboxed), `all` (everything sandboxed)
- **Backends**: `docker`, `ssh`, `openshell`
  - Docker: uses container namespaces via `/var/run/docker.sock`
  - SSH: executes in a remote workspace accessed via SSH
  - OpenShell: either `mirror` (sync local↔remote) or `remote` (remote canonical, no sync back)
- **Scope** (isolation granularity): `session` (per-session container), `agent` (per-agent container, default), `shared` (single container)
- **Workspace Access**: `none` (default, no workspace mount), `ro` (read-only at `/agent`), `rw` (read-write at `/workspace`)
- Auto-prune: `idleHours`, `maxAgeDays`

#### 2. Tool Policy (which tools are allowed)
- Global: `tools.allow` / `tools.deny`
- Per-agent: `agents.list[].tools.allow` / `agents.list[].tools.deny`
- Per-provider: `tools.byProvider[provider].allow/deny`
- Sandbox-specific: `tools.sandbox.tools.allow` / `tools.sandbox.tools.deny`
- Precedence: tool policy is the hard stop — sandbox cannot bring back a denied tool

#### 3. Elevated (exec escape hatch)
- `tools.elevated` allows `exec` to run outside sandbox when user is sandboxed
- Not skill-scoped, does not override tool allow/deny
- Levels: `/elevated on` (with approvals), `/elevated full` (skip approvals)
- Controlled by `tools.elevated.allowFrom`

#### Security Model
- One user per host/gateway recommended
- For multi-user hostile isolation: separate OS users/hosts + separate gateways
- Per-agent access profiles for multi-agent routing

### Codex Sandbox

OpenAI Codex CLI (github.com/openai/codex) uses OS-level sandboxing written in Rust (`codex-rs/linux-sandbox`):

#### Implementation Stack (layered)
1. **Bubblewrap (bwrap)** — primary filesystem sandbox
   - Constructs isolated filesystem view via bind mounts
   - `--unshare-user` (user namespace isolation)
   - `--unshare-pid` (PID namespace isolation)
   - `--unshare-net` (network namespace when network restricted)
   - Read-only by default, explicit writable roots
   - Protects metadata dirs (`.git`, `.agents`, `.codex`)
2. **PR_SET_NO_NEW_PRIVS** — applied in-process before seccomp/landlock
3. **seccomp** — network filter (blocks `AF_UNIX`/`socketpair` in proxy mode)
4. **Landlock LSM** — legacy fallback when user namespaces unavailable (e.g., restricted containers)

#### Permission Profiles (policy layer)
Modern system (`permissions.NAME` in `config.toml`):
- Filesystem rules: writable roots, read-only paths, unreadable paths
- Network rules: `enabled` boolean + domain allowlist (`permissions.NAME.network.domains`)
- Managed proxy mode: `--unshare-net` + internal TCP→UDS→TCP bridge for allowed endpoints

Legacy system (`sandbox_mode`):
- `read-only`: no writes allowed
- `workspace-write`: writes only within workspace (default)
- `danger-full-access`: no restrictions

#### Approval Policy (orthogonal to sandbox)
- `untrusted`: ask for non-safe commands
- `on-request`: ask when crossing sandbox boundary
- `on-failure`: pause on errors only
- `never`: fully autonomous

#### Key Design Insight
Codex separates sandbox (enforcement) from approval (UX flow). The sandbox defines hard boundaries; the approval policy decides when to ask the human. This two-axis model avoids conflating "what is safe" with "what needs confirmation."

### Other Approaches

#### Claude Code (Anthropic)
Uses a **rule-based permission model** without OS-level sandboxing:

- **Evaluation order**: deny → ask → allow (first match wins)
- **Rule types**:
  - Bare tool name (`Bash`) — removes tool from context entirely
  - Scoped pattern (`Bash(rm *)`) — blocks matching calls only
- **Permission modes**: `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`
- **Settings scopes**: user-level, project-level, managed (enterprise)
- **PreToolUse hooks**: arbitrary code runs before permission check, can deny/allow/force-prompt
- **No OS sandboxing**: relies on Claude not attempting denied actions + rule enforcement

Notable: "permission rules are enforced by Claude Code, not by the model" — prompt instructions shape intent, rules enforce boundaries.

#### E2B (Firecracker microVMs)
- Purpose-built for AI agent code execution
- Each sandbox = Firecracker microVM with its own Linux kernel
- Boot time: <100ms, <5MB memory overhead
- SDK-first: `Sandbox.create()` → `sandbox.run_code()` → tear down
- Network modes: allow-all, deny-all, user-defined rules
- Secrets passed as environment variables
- Self-hostable (Terraform + Nomad + Consul on GCP/AWS with KVM support)

#### Modal (gVisor)
- Serverless platform with gVisor-based isolation (user-space kernel intercepting syscalls)
- Sub-second cold starts
- GPU pass-through (critical differentiator for ML agents)
- Sandbox API similar to E2B pattern

#### Daytona (Container-based)
- Container-based with network policies
- Fastest cold-start (~5-15s for full dev environments)
- Persistent environments
- GPU pass-through

#### Comparison Table

| System | Isolation Level | Multi-tenant Safe | Cold Start | GPU | Self-host |
|--------|----------------|-------------------|------------|-----|-----------|
| OpenClaw | Container (Docker) or SSH | Per-agent containers | Seconds | No | Yes |
| Codex | OS-level (namespaces + seccomp) | Single-user only | Instant (local) | N/A | Yes (local) |
| Claude Code | Rule-based (no OS sandbox) | Single-user only | N/A | N/A | Yes (local) |
| E2B | MicroVM (Firecracker) | Yes (kernel-level) | <100ms | No | Yes (complex) |
| Modal | gVisor | Yes | <1s | Yes | No |
| Daytona | Container | Partial | 5-15s | Yes | Yes |

## Implications for Our Bot

Our scenario: multi-user Feishu chat bot running LLM agent with tools (MCP + custom skills). Key requirements:

1. **Multi-tenant isolation is critical** — multiple users share the bot, each user's tool executions must be isolated from others. This rules out local-only single-user models (Codex, Claude Code approach).

2. **Layered model from OpenClaw is architecturally relevant**:
   - Separate "where tools run" (sandbox) from "what tools are allowed" (policy) from "when to escalate" (approval)
   - Per-user tool policy (allow/deny) can restrict which MCP tools each user can invoke
   - Sandbox scope can be per-user or per-session

3. **For code/script execution**, E2B-style microVM approach is the gold standard for multi-tenant:
   - Per-user ephemeral sandbox, kernel-level isolation
   - Fast boot time suitable for chat interaction latency
   - However: adds operational complexity and cost

4. **Practical middle ground for our bot**:
   - Tool-level: allow/deny policy per user role (admin vs normal user)
   - Execution-level: Docker containers per session for any shell/code execution
   - Network-level: deny-all outbound by default, allowlist for MCP endpoints
   - No OS sandbox needed for pure API tools (read-only MCP queries) — policy layer is sufficient

5. **Approval flow** (from Codex's insight):
   - Separate safety enforcement (hard deny) from UX flow (ask user)
   - Sensitive operations → require user confirmation in Feishu before executing
   - Safe operations (read-only queries) → auto-approve

## Caveats / Not Found

- OpenClaw docs are public but the project is relatively new; production deployment patterns are sparse
- Codex sandbox is Linux-only and designed for single-user local CLI — no multi-tenant story
- Claude Code has no OS sandboxing; pure trust model relying on rule enforcement at application layer
- E2B self-hosting requires complex infra (Terraform + KVM); managed service has per-minute billing
- No research found on Feishu/Lark-specific bot sandboxing patterns or best practices
- OpenClaw's "Cherry Studio" (GUI) uses the same underlying runtime; no separate GUI-specific permission model found
