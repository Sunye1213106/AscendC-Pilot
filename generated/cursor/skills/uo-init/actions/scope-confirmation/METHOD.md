# scope_confirmation — 范围确认（Pilot prepare 完成后的 primary 交互）

> 勿在本文件推进 Pilot 阶段；只执行 prepare 后返回的 interactive_steps。  
> **`acp` / `acp uo-scope` 是真实 CLI。禁止把本 METHOD 当成手工清单去 Glob 源码。**  
> **禁止再次 `acp run-action scope_confirmation`（prepare）或把 primary 当 subagent 派发。**

## Purpose

确认分析范围并建立 MCP 窄索引。架构中立入口必须保留；`--architecture` 只过滤有效实现分支。

身份字段一律来自 Runtime Bundle：

```text
project=<PROJECT_ROOT>
architecture=<ARCHITECTURE>
run_id=<RUN_ID>
workflow_id=<WORKFLOW_ID>
action_id=<ACTION_ID>
actor_id=<ACTOR_ID>
```

## 职责划分

| 步骤 | 谁 | 命令 | 产物 |
|---|---|---|---|
| 1 | Pilot | `acp uo-scope scan --project <PROJECT_ROOT> --architecture <ARCHITECTURE>` | **唯一合法计数表**（含 sibling/parent `common/`） |
| 2 | 人+Agent | **原样粘贴** scan 输出 → AskQuestion → `acp uo-scope checkpoint --decision …` | `scope_confirmed.yaml` |
| 3–5 | Pilot | `build-evidence` → `closure` → `stage` | build 证据 / confirmed / `index_stage` |
| 6 | MCP | `index_repository`(仅 `index_stage`，mode=fast) | CBM 图（MCP cache）；记下返回的 `project` 名 |
| 7 | Pilot | `acp uo-scope record-index --cbm-project <name>` | **`uo/cbm/index_meta.json`**（`indexed_via=mcp`） |
| 8–9 | Pilot | `finalize` → `run-action <ACTION_ID> --finalize` | `runs/<RUN_ID>/scope/receipt.yaml` |

**MCP 不会写出 `index_meta.json`。** 跳过步骤 7 时 `uo-scope finalize` 与 Action finalize 均硬失败。  
正式产物路径为 `uo/runs/<RUN_ID>/scope/scope_confirmed.yaml`（**不是** `uo/summary/`，也不是旧 run 的 `runs/*/`）。
