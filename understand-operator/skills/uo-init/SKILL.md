---
name: uo-init
description: >-
  端到端构建 AscendC 算子分层 KB。/uo-init 或要求建库时用。
  Phase0 人工确认 → 入口/plan（脚本+有界 LLM）→ 分层抽取 → resolve → 门禁 → 导出。
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--full]"
---

# Skill: uo-init

## Purpose

空仓库 / 未建库 → **定稿** `$PROJECT_ROOT/.understand-operator/$OP_NAME/`（integrity + kb-review 通过）。

## Trigger

- 适用：`/uo-init`、明确要求「建库 / 初始化 KB」
- 不适用：已有 fresh KB 的问答（`/uo-query`）、增量（`/uo-update`）、代码审查（`/uo-code-review`）

## Inputs

| 权威 | 说明 |
|---|---|
| `PROJECT_ROOT` | 算子包根（含 `op_host`/`op_kernel`；禁改到多算子父仓） |
| `OP_NAME` | 算子名 |
| 用户 Phase0 确认 | `continue \| revise \| stop \| manual_supplement` |

辅助只读：`spec/ownership.yaml`、`prompts/common/*`、`prompts/init/*`。  
人读长叙事：`docs/uo-init-workflow.md`（Step 明细）。  
命令块权威：`prompts/init/workflow.md`。

## Outputs

**正式：** `manifest.yaml`、`ir/**`、`tiling/**`、`kernel/**`、`indexes/kb_graph.sqlite`、
`checks/{integrity,confidence_gate,final}.yaml`、`summary/human_overview.md`、
可选 `summary/confidence_report.md`、`review/kb_product_review.yaml`。

**中间：** `runs/<id>/phase0/**`、`ir/*_patch.yaml`、`ir/input_derivable_gaps.yaml`、
`ir/entrypoint_candidates.yaml`、`ir/extract_plan_candidates.yaml`。

**禁止生成：** `contracts/**`（测项合同只在 TG）、伪造 high 闭合、完整 `host_derivation_chain` dump、父仓级 CBM 索引。

## Invariants

- sibling `common/` 存在 → confirmed 必须含裁剪后非空 `common/`
- MCP 仅索引 `$UO_ROOT/cbm/index_stage`；`indexed_via: mcp`
- 建库期子代理 **仅** `uo-semantic-resolve`、`uo-kb-review`；**禁** `/uo-query`
- 闭合 KEY 必须 `confidence: high`；否则继续任务 E 或写满 `confidence_report.md`
- 抽取机制：CBM + **花括号定界函数体 + 定向正则**（非完整 C++ AST）
- 幂等：同 scope 重跑可覆盖未人工锁定产物；禁静默改用户已确认 scope
- 语言：`prompts/common/language.md`

## Tool Policy

### MUST use

- Phase0：`prepare_operator` → `macro_scope_scan` → AskQuestion → `review_checkpoint`
- 确认后：`stage_cbm_scope` → MCP `index_repository` → `--write-index-meta` → `finalize_phase0`
- Extract：脚本入口 →（低置信）LLM 任务 A → 脚本扩 plan → LLM 任务 C → `build_layered_kb`
- Gaps open / confidence≠high → 任务 E → `classify_input_derivable` → `check_final_confidence`
- 源码证据：`prompts/common/cbm.md`

### MAY use

- `revise` / `manual_supplement` 后重扫 scope
- kb-review fail 后按 `rework_stage` 局部返工（≤2）

### MUST NOT

- 自动 `continue` Phase0；建库期派 `/uo-query`；整盘搜脚本
- 写 `contracts/**`；dump `operator_graph` / 完整 `exhaustive`；本地 CBM CLI
- 低置信伪标 `true`/`high`；跳过 `--write` / `--confirm-patch` 空跑 LLM

## Workflow

变量：`SCRIPT_DIR=$PLUGIN_ROOT/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.understand-operator/$OP_NAME`。  
派发：`prompts/init/dispatch.md` · Todo：`prompts/init/progress.md`。

### Phase 0: 范围确认 + 窄索引

- **Entry：** 用户触发 `/uo-init`
- **Actions：** 见 `references/phase0.md`；命令块见 `prompts/init/workflow.md`
- **Artifacts：** `scope_confirmed.yaml`、`cbm/index_meta.json`
- **Exit：** `scope_confirmed` 存在且 `indexed_via: mcp`
- **Failure：** 用户 `stop` → `PHASE0_STOPPED`；缺脚本 → `INVALID_INPUT`

### Phase 1: Extract

- **Entry：** Phase0 Exit 满足
- **Actions：** 见 `references/extract.md`（脚本找入口 → 有界 LLM → plan → `build_layered_kb`）
- **Artifacts：** `ir/entrypoints.yaml`、`ir/extract_plan.yaml`、layered IR、`ir/input_derivable*.yaml`、`ir/unresolved.yaml`
- **Exit：** `build_layered_kb` 成功
- **Failure：** 入口/plan 无法确认 → `UNRESOLVED_SEMANTICS`；脚本失败 → `TOOL_FAILURE`

### Phase 2: Resolve + 门禁 + 导出

- **Entry：** Phase1 Exit 满足
- **Actions：** 见 `references/resolve.md`（任务 B/E → classify → confidence → export → integrity）
- **Artifacts：** `checks/confidence_gate.yaml`、`indexes/kb_graph.sqlite`、`checks/integrity.yaml`
- **Exit：** unresolved 无开放项；`confidence_gate` ∈ {pass, reported}；integrity pass
- **Failure：** 无法 high → `CONFIDENCE_REPORTED`（须写原因，禁伪闭合）；integrity fail → `VALIDATION_FAILURE`

### Phase 3: KB 产物审查

- **Entry：** Phase2 Exit 满足
- **Actions：** 派 `uo-kb-review`（`tpl_kb_review.md`）→ pass 则 `export_human_views.py`
- **Artifacts：** `review/kb_product_review.yaml`、`summary/human_overview.md`
- **Exit：** `verdict=pass` 且 human_views 已写
- **Failure：** fail 且返工耗尽 → 停并展示 findings

## Semantic Escalation

| 适合脚本 | 适合 LLM（`uo-semantic-resolve`） |
|---|---|
| 范围扫描、入口候选、plan 扩面、分层抽取、classify、export、integrity | 入口消歧（A）、plan 角色（C）、FP 抽样（B）、断边（E） |

- 每批断边 cap 8；约 ≤12 tools/批
- 证据最低要求：CBM snippet + `path:line`
- **禁**用 `/uo-query` 替代任务 E

## Failure Taxonomy

`INVALID_INPUT` · `PHASE0_STOPPED` · `TOOL_FAILURE` · `UNRESOLVED_SEMANTICS` ·
`NOT_INPUT_DERIVABLE` · `CONFIDENCE_REPORTED` · `VALIDATION_FAILURE` · `SUBAGENT_RESUME_UNAVAILABLE`

## Quality Gate

- [ ] Phase0 有人工确认记录
- [ ] `ir/entrypoints.yaml` 已确认；`ir/extract_plan.yaml` 已 apply
- [ ] `ir/unresolved.yaml` 无开放项
- [ ] `checks/confidence_gate.yaml` ∈ {pass, reported}；reported 则原因非 TODO
- [ ] `check_kb_integrity` pass；`uo-kb-review` verdict=pass
- [ ] sqlite fresh；无伪造 high；无 `contracts/**`

## Stop Conditions

- 用户 `stop` / Phase0 未确认 → **STOP**
- `SCRIPT_DIR` / `prompts` 缺失 → **STOP**（提示 `install.ps1`）
- integrity / review fail 且返工耗尽 → **STOP**（展示 findings，禁止猜测闭合）

## Examples

- 正常：scope continue → 高置信入口自动确认 → plan apply → gates pass → review pass
- 低置信入口：任务 A 从候选选一 → `--confirm-patch` 回流
- 无法 high：写 `confidence_report.md`，`confidence_gate=reported`，不伪标 high
