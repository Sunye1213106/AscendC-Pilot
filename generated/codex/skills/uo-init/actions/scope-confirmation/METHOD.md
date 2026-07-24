# scope_confirmation — 范围确认（Pilot 托管）

> 勿在本文件推进 Pilot 阶段；只执行 `acp next` 给出的 `scope_confirmation`。  
> **`acp` / `acp uo-scope` 是真实 CLI。禁止把本 METHOD 当成手工清单去 Glob 源码。**

## Purpose

确认分析范围并建立 MCP 窄索引。架构中立入口必须保留；`--architecture` 只过滤有效实现分支。

## 前置（不得跳过）

若 `acp next` 仍返回 `prepare_layout`，或 `.ascendc-pilot/uo/manifest.yaml` 不存在：

```text
acp run-action prepare_layout --project <算子目录>
```

**禁止**在未 prepare 时直接 scope / 读 arch35 源码“建库”。

## 职责划分

| 步骤 | 谁 | 命令 | 产物 |
|---|---|---|---|
| 0 | Engine | `prepare_layout`（上表） | `$UO_ROOT/` + manifest |
| 1 | Pilot | `acp uo-scope scan --architecture <arch>` | **唯一合法计数表**（含 sibling/parent `common/`） |
| 2 | 人+Agent | **原样粘贴** scan 输出 → AskQuestion → `acp uo-scope checkpoint --decision …` | `scope_confirmed.yaml` |
| 3–5 | Pilot | `build-evidence` → `closure` → `stage` | build 证据 / confirmed / `index_stage` |
| 6 | MCP | `index_repository`(仅 `index_stage`，mode=fast) | CBM 图（MCP cache）；记下返回的 `project` 名 |
| 7 | Pilot | `acp uo-scope record-index --cbm-project <name>` | **`uo/cbm/index_meta.json`**（`indexed_via=mcp`） |
| 8–9 | Pilot | `finalize` → `run-action scope_confirmation --finalize` | `runs/*/scope/receipt.yaml` |

**MCP 不会写出 `index_meta.json`。** 跳过步骤 7 时 `uo-scope finalize` 与 Action finalize 均硬失败。  
正式产物路径为 `uo/runs/<run>/scope/scope_confirmed.yaml`（**不是** `uo/summary/`）。

`--project` = 算子目录（如 `…/flash_attention_score_grad`），不是 `ops-transformer` 父仓。

命名对照（勿混用）：
- `op_name` / `index_meta.op_name` = 算子包名（目录名），如 `flash_attention_score_grad`
- MCP `name` / `--cbm-project` = stage 提示的索引项目名，常带 `-scope` 后缀（如 `flash_attention_score_grad-scope`）——**这是对的**，传给 `record-index`
- KB 目录恒为 `.ascendc-pilot/uo`（dirname=`uo`）；finalize **不会**拿 `uo` 去比对 `op_name`

## 关于 common/

扫描脚本会自动：

1. 算子旁 sibling `../common`（对本仓即 `attention/common`）
2. 或父级 `common/`（最多向上 3 层，可到仓库根 `ops-transformer/common`）

Agent **不得**只在算子目录内 Glob；漏 `common/` 一律视为本步失败，应重跑 scan，而不是手补路径表。

## Hard Constraints

- MUST：AskQuestion 前粘贴 **scan 命令 stdout**（含 `Detected AscendC common library` / 计数行）；禁自编 op_host 数
- MUST：等人确认后再 checkpoint
- MUST NOT：Glob/Read 列举源码来“做范围表”
- MUST NOT：直调任何 `uo.scripts.*.py`
- MUST NOT：把父仓当 `repo_path` 丢给 MCP；确认前开始结构抽取
- MUST NOT：自动 `continue`；派 explore/generalPurpose 预扫

## Failure Handling

- `stop` → `SCOPE_STOPPED`
- scan 无 common 但磁盘存在 sibling common → 报 `SCOPE_SCAN_MISSED_COMMON`，重跑/查路径
- stage / MCP / record-index 失败 → `TOOL_FAILURE`（禁整仓兜底索引；禁手写 `index_meta.json`）
