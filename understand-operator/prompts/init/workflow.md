# `/uo-init` 编排（有限状态机）

Skill 管流程：`skills/uo-init/SKILL.md`。本文件给父代理**可执行阶段合同**。

必读：`common/runtime.md` · `common/cbm.md` · `init/progress.md` ·
`init/scope_menu.md` · `init/macro_scope.md` · `init/dispatch.md` ·
`spec/ownership.yaml`

变量：`SCRIPT_DIR=$PLUGIN_ROOT/uo/scripts`；
`UO_ROOT=$PROJECT_ROOT/.understand-operator/$OP_NAME`。禁全盘搜脚本。

## Phase 0 — 范围（硬门禁）

**Entry：** 用户触发 init。  
**机制：** 文件系统扫描提案（非 AST）→ 人确认 → 窄目录 MCP 索引。  
**Actions：**

```powershell
python -X utf8 "$SCRIPT_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/macro_scope_scan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35
# 展示 scope_proposal → AskQuestion（scope_menu）→ 禁自动 continue
python -X utf8 "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision continue
python -X utf8 "$SCRIPT_DIR/stage_cbm_scope.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
# MCP index_repository(repo_path=$UO_ROOT/cbm/index_stage, mode=fast, name=<op>-phase0-scope)
python -X utf8 "$SCRIPT_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write-index-meta --cbm-project <name>
python -X utf8 "$SCRIPT_DIR/finalize_phase0.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

收窄初次提案可用 scan 的 `--replace-initial`。  
**Exit：** `scope_confirmed` + `index_meta.indexed_via=mcp`。  
**Fail：** 用户 stop / 未确认 → STOP。细节：`macro_scope.md` · `skills/uo-init/references/phase0.md`。

## Phase 1 — Extract（脚本为主，LLM 有界）

**Entry：** Phase0 完成。  
**权威细则：** `skills/uo-init/references/extract.md`（置信度阈值、扩面启发式、非 AST 说明）。

### ① 脚本找入口 + 置信度

```powershell
python -X utf8 "$SCRIPT_DIR/resolve_entrypoints.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write
# → ir/entrypoint_candidates.yaml
```

- **逻辑：** CBM 按角色名模式搜符号；回退在 confirmed 文件上整词正则；kernel 另扫 `__global__`
- **置信度：** 路径/精确名/Host·Kernel 目录启发式打分；`confidence < 0.85` → 候选标 `needs_llm`
- **高置信：** 脚本可自动 `selected`（该角色**不派** LLM）
- **低置信 / 歧义：** 角色进 `llm_required_roles`

### ② LLM 介入（仅 llm_required_roles）

派发 `tpl_entrypoint`（任务 A）→ 只从候选选一个或标 missing → `ir/entrypoint_confirm.yaml`。  
**禁止**发明候选外符号。

```powershell
python -X utf8 "$SCRIPT_DIR/resolve_entrypoints.py" "$PROJECT_ROOT" --op-name "$OP_NAME" `
  --confirm-patch "$UO_ROOT/ir/entrypoint_confirm.yaml"
# → ir/entrypoints.yaml（后续唯一入口锚点）
# 若跳过本步，build 必须带同一 --confirm-patch
```

### ③ 脚本按入口扩 plan 候选

```powershell
python -X utf8 "$SCRIPT_DIR/propose_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write
# → ir/extract_plan_candidates.yaml
```

- **依据：** 已确认 `host_tiling_entry`
- **怎么扩：** 花括号定界函数体 → callee → CBM trace → 扫 `set_*`/`tilingData=` → 一跳 + sink 闭包
- **机制：** 正则 + 花括号匹配（**非** clang AST）

### ④ LLM 确认 plan（打角色，不扩面）

派发 `tpl_extract_plan`（任务 C）→ 按候选 `evidence` 标
`tiling_writer|key_writer|workspace_writer|provenance_helper|ignore` → `ir/extract_plan.yaml`。

```powershell
python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --check
python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write
```

### ⑤ 分层抽取

```powershell
python -X utf8 "$SCRIPT_DIR/build_layered_kb.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

- **依赖：** `entrypoints.yaml` + `extract_plan.yaml`
- **内部：** `extract_host_subgraph` / `extract_kernel_subgraph` / `extract_tilingkey_space` / …
- **机制：** 按 plan 过滤后，对函数体做正则抽写入/分支；CBM 辅助定位

**Exit：** layered IR + `input_derivable*.yaml`。  
**硬规则：** 无 `--write` 则任务 A/C **无候选可读**；无 `--confirm-patch` 则任务 A 的 confirm **不会进入** `entrypoints.yaml`。

## Phase 2 — Resolve + 置信度门禁

**Entry：** extract 完成。  
**Actions：**
1. 派发 `tpl_residual`（任务 B）→ `apply_resolution --check` → apply
2. `escalate_keys` / gaps `open` / confidence≠high → `tpl_input_derivable`（任务 E，**禁 uo-query**，cap 8）
3. 跑门禁与导出：

```powershell
python -X utf8 "$SCRIPT_DIR/classify_input_derivable.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_final_confidence.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/kb_query_export.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --view testcase-contract
python -X utf8 "$SCRIPT_DIR/export_kb_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_kb_integrity.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

仍非 high → 写满 `summary/confidence_report.md`（禁伪 high）。  
**Exit：** unresolved 清空；`confidence_gate` ∈ {pass,reported}；integrity pass。  
`reported` 时 open input_derivable gaps 在 integrity 中为 **warning**（非 error）；须展示 `confidence_report.md`，不得伪标 high。  
细节：`skills/uo-init/references/resolve.md` · `skills/uo-init/references/confidence-gate.md` ·
`skills/uo-init/references/uo-input-derivable-resolve.md`。

## Phase 3 — Review

**Entry：** integrity pass。  
派发 `tpl_kb_review`（`uo-kb-review`）。  
**Exit：** verdict=pass → `export_human_views.py`。  
**Fail：** 按 `rework_stage` 返工 ≤2。

```powershell
python -X utf8 "$SCRIPT_DIR/export_human_views.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## 全局硬规则

- 写入遵循 `ownership.yaml`；思考/话术中文（`runtime.md`）
- 禁 dump `operator_graph` / 完整 `testcase`；源码走 `cbm.md`
- 子代理仅 semantic-resolve + kb-review（`dispatch.md`）
- Phase 编号以本文件为准（0–3）；Todo 七条见 `progress.md`（不另编号 Phase）
- 增量：`update/workflow.md`；审查：`review/workflow.md`
