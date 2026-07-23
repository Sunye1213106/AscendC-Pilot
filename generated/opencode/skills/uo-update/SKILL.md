---
disable-model-invocation: true
---

﻿---
name: uo-update
description: >-
  增量刷新 AscendC 算子 KB：相对上次 revision 重建同构 KB，并写出专用 diff/ 供 PR 测消费。
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--base <rev>] [--head <rev>]"
---

# Skill: uo-update

## Harness control plane（唯一权威）

本 Skill **不**拥有阶段/门禁/完成态。每一轮只做：

1. `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run）或读 `harness status`
2. `harness next --project $PROJECT_ROOT` → 取 `phase_label_zh`、`allowed_actions`、`open_items`
3. 按返回的 **一个** `action_id` 执行对应领域方法（见 references / prompts）
4. 需要时 `harness advance <next_phase>` / `harness rework --reason <code>`
5. 终态仅 `harness complete`；禁止自行宣布 done / `passed`

Gate 失败 → 保持 phase，status=`rework_required` 或 `human_required`；勿当作立即 blocked。


## Purpose

已有 KB + 代码变更 → **同构新 KB** + 可消费的 `diff/**`（PR 测优先读 diff）。

## Trigger

- 适用：代码变更后刷新 KB；需要 `diff/**`；或只要只读变更摘要（原 `/uo-diff`，现并入本工作流）
- 不适用：首次建库（`/uo-init`）；缺陷/需求审查（`/uo-code-review`）

人读 Step 明细：`docs/uo-update-workflow.md`。  
阶段合同：`prompts/update/workflow.md`。  
只读摘要模式：跑完 `detect_kb_changes.py` 后展示结果并 **STOP**（不写持久 `diff/**` 产品包，除非用户明确要求 update 完整产物）。

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
- 新增不确定项：`uo-semantic-resolve` 任务 A/B/C；KEY 用 `uo-key-resolve`（同 init）

### MUST NOT

- 无 manifest / unknown revision 时继续
- 跳过 Phase0 门禁；静默扩大 scope
- 占用本 skill 做代码审查

## Workflow

变量：`SCRIPT_DIR=$PLUGIN_ROOT/engines/uo/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.ascendc-agent/uo`。

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

- **Actions：** 仅新增不确定项派任务 A/B/C；KEY 派 `uo-key-resolve` triage→分流 → 对应回流脚本
- **Exit：** 开放语义项已处理或记入 reported

### Phase 7: 门禁 + diff 产物

- **Actions：** classify → confidence → integrity → `export_diff_product`
- **Artifacts：** `diff/**`、receipt
- **Exit：** integrity pass；diff index 可读
- **Failure：** `VALIDATION_FAILURE`

## Semantic Escalation

与 init 相同划分：脚本做 diff/plan/rebuild/门禁；LLM 用 A/B/C + `uo-key-resolve`。  
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