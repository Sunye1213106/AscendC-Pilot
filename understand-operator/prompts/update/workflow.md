# `/uo-update` 编排

## Purpose

同构刷新 KB + 写 `diff/`（供 PR 测）。不做 testcase-agent / Z3 / 真跑测。

## Required reads

`common/language.md` · `common/path.md` · `common/cbm.md` · `init/dispatch.md` ·
`skills/uo-update/SKILL.md` · `docs/uo-update-workflow.md` · `spec/ownership.yaml`

## Todo（中文 7 条 · 唯一）

1. 校验已有 KB 与 revision  
2. 计算 git diff → `diff/change_set.yaml`  
3. 生成 update_plan 并展示影响面  
4. 必要时 Phase0 复审 / CBM 重索引  
5. 按层重抽并写出新 KB  
6. 有界语义补全  
7. 写出专用 diff 产物并校验 KB  

## Procedure（与 docs Step 对齐）

### Step 1 — 校验 KB

无 manifest / revision unknown → 停并提示 `/uo-init`。

### Step 2 — 脚本 detect

```powershell
python -X utf8 "$SCRIPT_DIR/detect_kb_changes.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

### Step 3 — 脚本 plan 并展示

```powershell
python -X utf8 "$SCRIPT_DIR/plan_kb_update.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

展示 `summary/update_plan.yaml`。

### Step 4 — 条件 Phase0

若 `needs_phase0_review`：AskQuestion `continue|revise|stop`（禁自动 continue）→  
可接受后带 `--confirm-phase0`；扩范围则同 init Phase0 Step 3–6。

### Step 5 — 脚本重建

```powershell
python -X utf8 "$SCRIPT_DIR/update_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
# PR: --base $BASE --head $HEAD
# Phase0 确认后: --confirm-phase0
```

机制同 init Extract Step 5；入口/plan 变更复用 init Extract Step 1–4。

### Step 6 — 有界 LLM（按需）

- 新 entrypoint → 任务 A · `tpl_entrypoint.md`
- 新 unresolved → 任务 B · `tpl_residual.md`（≤12）
- extract_plan → 任务 C · `tpl_extract_plan.md`
- 新 gaps → 任务 E · `tpl_input_derivable.md`（禁未定稿改派 uo-query）

### Step 7 — 门禁 + diff/

classify → confidence → integrity → `export_diff_product` → receipt。

## Downstream

优先读：`diff/index.yaml` · `diff/impact.yaml` · `diff/unresolved.yaml`。  
`confidence=low` / `layer_only` → 按 `kb_refs` 回查 KB。

## Stop

无 manifest / revision unknown → 停并提示 `/uo-init`。
