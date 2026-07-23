---
name: uo-diff
description: >-
  相对已有 KB 给出只读变更摘要。/uo-diff 或「相对上次 KB 改了什么」。
  不写 KB、不写持久 diff/ PR 包。
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# Skill: uo-diff

## Purpose

已有 KB → **只读**变更摘要（给人看），不产生可消费的 `diff/**` PR 包。

## Trigger

- 适用：快速了解「相对上次 KB 改了什么」
- 不适用：需要 `diff/**`（`/uo-update`）；首次建库（`/uo-init`）；缺陷/需求审查（`/uo-code-review`）

人读 Step 明细：`docs/uo-diff-workflow.md`。  
本 skill **刻意不合并进** `uo-update`。

## Inputs

| 权威 | 说明 |
|---|---|
| `$UO_ROOT` | 须存在 |
| `manifest` revision | 与当前 git 对比的基线 |

辅助：`uo/scripts/detect_kb_changes.py`；可选 `prompts/common/cbm.md`。

## Outputs

**正式：** 终端/对话中的变更摘要（可引用已有 `diff/change_set.yaml` 若 update 已跑过）。  
**禁止：** 写 KB；写持久 review 包；安装 code-review-graph。

## Invariants

- 只读；不修改 `$UO_ROOT` 产物
- 不依赖 CRG；不依赖可能缺失的 CBM `detect_changes` 工具

## Tool Policy

### MUST use

- 校验 `$UO_ROOT` 存在
- `detect_kb_changes.py`（或已有 change_set 的只读展示）

### MAY use

- 需定位源码时按 `prompts/common/cbm.md`（MCP first）

### MUST NOT

- 写 KB / 写 `diff/**` 产品；本地 CBM CLI；装 CRG；与 update 合并流程

## Workflow

### Phase 1: 校验 KB

- **Entry：** 用户触发 `/uo-diff`
- **Exit：** `$UO_ROOT` 存在
- **Failure：** 缺失 → 报告路径，建议 `/uo-init`，**STOP**

### Phase 2: 变更检测

- **Actions：**

```powershell
python -X utf8 "$SCRIPT_DIR/detect_kb_changes.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

- **Artifacts：** stdout / 结构化变更列表；若已有 `diff/change_set.yaml` 可摘要之
- **Exit：** 有可报告的变更集合（可为空）

### Phase 3: 摘要输出

- **Actions：** 用人读短文总结变更；结束
- **Exit：** 摘要已给出；无持久 review 产物

## Semantic Escalation

通常不需要 LLM 语义升级。若需源码定位 → MCP（禁 Grep 当主证据）。

## Failure Taxonomy

`NO_EXISTING_KB` · `TOOL_FAILURE`

## Quality Gate

- [ ] 未写 KB / 未写持久 `diff/` 产品
- [ ] 摘要基于 detect 输出或已有 change_set

## Stop Conditions

- 无 `$UO_ROOT` → **STOP**
- 脚本失败 → 报告路径，**STOP**（不假装无变更）
