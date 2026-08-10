# Skill / Prompt / Domain / Harness 设计原则

## 一句话区分

| 层 | 负责 | 不负责 |
|---|---|---|
| Pilot / Harness | 阶段、状态、合法边、Action、门禁、finalize | 领域分析细节 |
| Domain Skill | 「怎么做好这类任务」的稳定方法 | Runtime 身份、ACP 状态机 |
| Task Prompt | 一次有界任务的 targets / context | 完整 Workflow、证明长文 |
| Action Method | 指向 domain skill + 本步 I/O | 其他阶段 / advance |
| Capability | 底层工具纪律（导航、阅读、查询） | 认知主入口、工作流推进 |
| Policy | 全局稳定规则（证据、源码权威） | 具体任务步骤 |
| Agent Role | 角色身份、读写边界 | 场景路由和状态推进 |
| Generated | 宿主运行产物 | 人工维护业务源 |

## 源目录

| 路径 | 内容 |
|---|---|
| `skills/domain/` | **Agent 认知主入口**（progressive disclosure） |
| `skills/workflows/` | Pilot / primary 极薄入口（可含 ACP + Actions 表） |
| `skills/actions/` | 薄 Action Method |
| `skills/capabilities/` | 原子工具能力（非主算法） |
| `skills/policies/` | 全局 Policy |
| `prompts/tasks/` | 短 Task Prompt |
| `agents/` | Agent YAML（角色/边界运行时权威） |
| `generated/` | Composer 产物（可丢弃） |

## Progressive disclosure

```text
Level 1  name + description
            ↓ triggered
Level 2  domain/SKILL.md   （核心循环，≤200 行）
            ↓ only when needed
Level 3  references/ / _shared/
```

语义 Action 阅读链：

```text
Task Prompt  →  一个 Domain Skill  →  按需 references/_shared
```

**禁止** Domain Skill include 另一 Domain `SKILL.md`（跨领域用工作流派发任务 + 结构化产物交接）。  
**禁止** Prompt / Workflow 复述领域不变量（E 资格、证明 acceptance 等）。  
Lint：`scripts/check_skill_architecture.py`（已挂 CI / `check_contracts`）。

## Composer

```text
python scripts/compose_runtime.py --host opencode
# 或
python scripts/compose_runtime.py --repo .
python scripts/compile_skills.py --repo .
```

安装部署 `generated/<host>/{skills,agents,prompts}`（含 `skills/domain/`）。改 domain / policies / actions / prompts / agents 后必须 compose；CI 跑 `check_contracts` / `check_ownership_contracts` / `check_no_cbm`。

## 证据与 Lease

- **高置信 / `source_verified`** 规则只写在公共 `skills/policies/{evidence,code-access,source-authority}`；Action prompt **只引用**。
- **公共证据纪律（只写一次）**：查询未命中 ≠ 源码不存在。
- **源码导航失败回退** 写在 `skills/capabilities/source-navigation`。
- **Lease 不变量**：`allowed_write_paths ⊆ allowed_read_paths`（签发层强制）。
- Domain Skill / Capability / Action Method **不得**描述 Pilot advance / complete / 完整 phase WHILE。
