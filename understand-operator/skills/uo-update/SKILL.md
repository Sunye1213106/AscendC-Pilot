---
name: uo-update
description: >-
  增量刷新 AscendC 算子 KB：相对上次 revision 重建同构 KB，并写出专用 diff/ 供 PR 测消费。
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--base <rev>] [--head <rev>]"
---

# Skill: uo-update

## Purpose

已有 KB + 代码变更 → **同构新 KB** + 可消费的 `diff/**`（PR 测优先读 diff）。

## Trigger

- 适用：代码变更后刷新 KB；需要 `diff/**`
- 不适用：首次建库（`/uo-init`）；只要口头摘要（`/uo-diff`）；缺陷/需求审查（`/uo-code-review`）

人读 Step 明细：`docs/uo-update-workflow.md`。  
阶段合同：`prompts/update/workflow.md`。

## Inputs

| 权威 | 说明 |
|---|---|
| `$UO_ROOT/manifest.yaml` | 须存在且 `source.revision` ≠ `unknown` |
| 曾 extract 的 IR | 至少跑过分层抽取 |
| 可选 `--base` / `--head` | PR 对比修订 |

辅助：`skills/uo-init/references/{phase0,extract,resolve}.md`、`prompts/init/dispatch.md`、`tpl_*.md`。

## Outputs

**正式：** 与 init 同构的新 KB + `diff/{index,change_set,impact,unresolved}.yaml`。  
**中间：** `summary/update_plan.yaml`、`runs/<id>/update/receipt.yaml`。  
**禁止：** 改写已批准 TG plan；写测试 CSV；静默吞 scope 外文件。

## Invariants

- 新 KB 与 `/uo-init` 同构；下游优先读 `diff/`，不确定再回查 KB
- `needs_phase0_review` 时必须人确认，禁自动 continue
- 未定稿边禁止改派 `/uo-query`（除非 integrity 已过）
- 幂等：同 base/head 重跑应语义等价覆盖未锁定产物

## Tool Policy

### MUST use

- `detect_kb_changes.py` → `plan_kb_update.py` →（条件）Phase0 确认 → `update_operator.py`
- 门禁：`classify` → `check_final_confidence` → `check_kb_integrity` → `export_diff_product`

### MAY use

- 分步 `build_layered_kb.py --layers …`
- 新增不确定项：`uo-semantic-resolve` 任务 A/B/C/E（同 init）

### MUST NOT

- 无 manifest / unknown revision 时继续
- 跳过 Phase0 门禁；静默扩大 scope
- 占用本 skill 做代码审查

## Workflow

变量：`SCRIPT_DIR=$PLUGIN_ROOT/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.understand-operator/$OP_NAME`。

### Phase 1: 校验已有 KB

- **Entry：** 用户触发 `/uo-update`
- **Exit：** manifest 合法且曾 extract
- **Failure：** `NO_EXISTING_KB` / `UNKNOWN_REVISION` → **STOP**，提示 `/uo-init`

### Phase 2: 检测变更

- **Actions：** `detect_kb_changes.py`
- **Artifacts：** `diff/change_set.yaml`
- **Exit：** change_set 已写

### Phase 3: 生成并展示 update_plan

- **Actions：** `plan_kb_update.py`；向用户展示 `mode` / `affected_layers` / `needs_phase0_review`
- **Artifacts：** `summary/update_plan.yaml`
- **Exit：** plan 已展示

### Phase 4: 条件 Phase0 复审

- **Entry：** `needs_phase0_review=true`
- **Actions：** AskQuestion `continue|revise|stop`；扩 scope 同 init Phase0；重建带 `--confirm-phase0`
- **Exit：** 用户 continue 且 scope/索引就绪；或本 phase 跳过（无需复审）
- **Failure：** `stop` → **STOP**

### Phase 5: 按层重建 KB

- **Actions：** `update_operator.py`（或分步 rebuild）；入口/plan 变更复用 init Extract
- **Exit：** 同构新 KB 写出

### Phase 6: 有界语义补全（按需）

- **Actions：** 仅新增不确定项派任务 A/B/C/E → 对应回流脚本
- **Exit：** 开放语义项已处理或记入 reported

### Phase 7: 门禁 + diff 产物

- **Actions：** classify → confidence → integrity → `export_diff_product`
- **Artifacts：** `diff/**`、receipt
- **Exit：** integrity pass；diff index 可读
- **Failure：** `VALIDATION_FAILURE`

## Semantic Escalation

与 init 相同划分：脚本做 diff/plan/rebuild/门禁；LLM 仅 A/B/C/E。  
未定稿禁止 `/uo-query`。

## Failure Taxonomy

`NO_EXISTING_KB` · `UNKNOWN_REVISION` · `PHASE0_STOPPED` · `TOOL_FAILURE` ·
`UNRESOLVED_SEMANTICS` · `CONFIDENCE_REPORTED` · `VALIDATION_FAILURE`

## Quality Gate

- [ ] update_plan 已展示；scope 外文件未静默吞入
- [ ] 需要时 Phase0 有确认记录
- [ ] integrity pass；`diff/index.yaml` 存在
- [ ] sqlite / overview 已刷新

## Stop Conditions

- 无合法 KB / revision → **STOP**
- Phase0 `stop` → **STOP**
- integrity fail → **STOP**（展示 checks，禁止猜闭合）
