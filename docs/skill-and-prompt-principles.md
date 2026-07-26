# Skill / Prompt / Agent / Capability 设计原则（组合式）

## 一句话区分

| 层 | 负责 | 不负责 |
|---|---|---|
| Pilot Workflow | 阶段、状态、合法边、Action、门禁、完成条件 | 领域分析细节 |
| Policy | 全局稳定规则 | 具体任务步骤 |
| Capability | 可复用原子工程能力 | 工作流推进 |
| Action Method | 当前 Action 的领域方法 | 其他阶段 / advance |
| Prompt | 一次有界任务 | 完整 Workflow |
| Agent Role | 角色身份、读写边界、输出责任 | 场景路由和状态推进 |
| Generated | 宿主运行产物 | 人工维护业务源 |

## 源目录

| 路径 | 内容 |
|---|---|
| `skills/policies/` | 全局 Policy |
| `skills/capabilities/` | 原子 Capability |
| `skills/actions/` | Action Method |
| `skills/roles/` | Role 合同 |
| `skills/workflows/` | 薄入口 Skill |
| `prompts/tasks/` | 有界 task prompt |
| `agents/` | Agent YAML |
| `generated/` | Composer 产物（可丢弃） |

## Composer

```text
python scripts/compose_runtime.py --repo .
# 或
python scripts/compile_skills.py --repo .
```

安装只部署 `generated/<host>/{skills,agents,prompts}`。

## 证据与 Lease（2026-07-26 沉淀）

- **高置信 / `source_verified`** 规则只写在公共 `skills/policies/{evidence,code-access,source-authority}` + 共享校验（如 `uo.scripts.source_evidence`），Action prompt **只引用、不另立例外**。  
- **CBM 工具全名与失败回退** 写在 `skills/capabilities/cbm-navigation`，不写进单个 extract-plan 特例。  
- **Lease 不变量**：`allowed_write_paths ⊆ allowed_read_paths`（签发层强制）。  
- 嵌入源码的 YAML：优先 `evidence_window_sha256`；加载层对 `|` literal 做缩进 sanitize（`yaml_literal_sanitize`）。  
- **大 IR**：`uo.scripts.ir_summary`（`section_lines` / `must`）+ `ascendc_pilot.ir_summary`（stub `MUST_READ_ORDER`）；policy 在 `code-access`。Action 只填本步 summary 字段形状。

## 八问（落在 Capability / Action Method）

Capability / Action Method 应回答：何时用、输入、方法、输出、硬限制、停止条件。  
**不得**描述 Pilot advance / complete / 完整 phase WHILE。
