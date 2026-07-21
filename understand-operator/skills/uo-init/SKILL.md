---
name: uo-init
description: >-
  End-to-end AscendC operator layered KB build for a target repo.
  Use when the user runs /uo-init, uo_init, or asks to build
  an operator KB. Pipeline: Phase0 (human scope review) -> entrypoint confirm ->
  directed trace -> bounded LLM resolve -> contract export.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--full]"
---

# uo-init - Layered Operator KB Build

Build an evidence-backed operator KB under:

```text
.understand-operator/<op_name>/
```

## 进度 Todo（必须用中文，且只用下面这 7 条）

开跑时立刻创建 Todo，**标题只用中文业务语**，不要反复写 `Phase 0`，不要堆脚本名当标题。
脚本名可写在补充说明里，但 Todo 正文保持简短：

```text
1. 创建知识库目录
2. 扫描并提案分析范围（含向上发现 common）
3. 等待确认分析范围（硬门禁）
4. 窄索引代码图并完成范围收尾
5. 抽取 Host/Kernel/桥接（含入口确认 + extract_plan）
6. 有界语义补全（残留 unresolved）+ 入账 + 导出 + integrity
7. KB 产物审查（uo-kb-review）
```

含义对照（给执行者，不要写进 Todo 标题）：

| Todo | 主要动作 |
|---|---|
| 1 创建知识库目录 | `prepare_operator.py` |
| 2 扫描并提案分析范围 | `macro_scope_scan.py` |
| 3 等待确认分析范围 | AskQuestion + `review_checkpoint.py`（收窄用 `--replace-initial`） |
| 4 窄索引代码图并完成范围收尾 | `stage_cbm_scope.py` → MCP 索引 `index_stage` → `--write-index-meta` → `finalize_phase0.py` |
| 5 抽取 Host/Kernel/桥接（含入口确认） | `resolve_entrypoints` → `propose_extract_plan` → LLM extract_plan → `build_layered_kb` |
| 6 残留补全 + 入账 + 导出 | `uo-semantic-resolve` → `apply_resolution.py`（默认传播）→ ledger → `kb_query_export` + `export_kb_graph` + `check_kb_integrity`（脚本内刷新 overview） |
| 7 KB 产物审查 | 派发 `uo-kb-review`；`verdict=pass` 后**再** `export_human_views.py` 写入 kb_review；fail 按 `rework_stage` 回环（最多 2 次） |

Do **not** run Phase1 global BFS/sink pruning, Phase2/3 fact agents, or old
fact-review / graph-review receipt gates (`uo-boundary-agent`,
`uo-host-extraction`, `evaluate_review_trigger`, etc.).

**硬门禁：第 3 步「等待确认分析范围」不可跳过、不可自动 continue。**

若 scan 发现 sibling/parent `common/`：**确认范围必须保留 include 裁剪后的非空 `common/` 子集**。
`review_checkpoint continue` 与 `stage_cbm_scope` 在 confirmed 无 `common/` 路径时失败（`COMMON_SCOPE_REQUIRED`）。
include 裁剪只用完整/后缀路径匹配，**不用唯一 basename**（避免同名头文件串库）。

LLM 取源码：优先 CBM `search_graph` / `get_code_snippet`；禁止整读 `operator_graph` / `testcase` 全文 / `exhaustive`。

## Variables

- `SCRIPT_DIR`: `$PLUGIN_ROOT/uo/scripts` (only canonical location).
- `PLUGIN_ROOT`: plugin repository root (also linked as
  `~/.config/opencode/understand-operator-plugin` after install).
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`.
- `PROJECT_ROOT`: **operator package directory** (e.g. `.../flash_attention_score_grad`).
  KB always lives at `$PROJECT_ROOT/.understand-operator/$OP_NAME`.
  **Never** move `$PROJECT_ROOT` to the parent workspace even when `common/` is found
  (parent often contains many other operators).
- `OP_NAME`: `--op-name`, otherwise repository-derived name.
- `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`.
- Architecture default: `arch35` (v1 scope).

Never search the whole disk for scripts.

## Phase 0 (scope discovery + human review hard gate)

Read before acting:

- `$PROMPT_DIR/01a_macro_scope_human_review.md`
- `$PROMPT_DIR/00_review_menu.md`

### Steps

1. Resolve `PROJECT_ROOT`, `OP_NAME`, `SCRIPT_DIR`.
2. `prepare_operator.py` create KB layout (creates `current_run_id`).
3. Run scope proposal:

```powershell
python -X utf8 "$SCRIPT_DIR/macro_scope_scan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35
```

   AscendC note: the scanner may **walk upward** for a sibling/parent `common/`
   library and record `workspace_root` plus include-pruned `common/...` paths.
   **`$PROJECT_ROOT` and the KB stay on the operator subdirectory.** Do **not**
   re-point `$PROJECT_ROOT` to the parent workspace. Stage + MCP index only
   `$UO_ROOT/cbm/index_stage` (operator files + common subset in one tree).

4. Read `runs/<current_run_id>/phase0/scope_proposal.yaml` (and `scope_scan.yaml`).
5. **HARD STOP — human review.** Present the proposal to the user (candidate
   files by category, directories, excludes, warnings). Use the runtime
   AskQuestion / question UI with these exact choices:

   - `continue`
   - `revise`
   - `stop`
   - `manual_supplement`

   Do **not** call CBM `index_repository`, do **not** read source at scale, and
   do **not** start Extract until the user decides.

6. After the user chooses, record the decision:

```powershell
python -X utf8 "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision <continue|revise|stop|manual_supplement>
```

   - `continue` → writes `scope_review.yaml` + `scope_confirmed.yaml`; proceed.
   - `revise` / `manual_supplement` → adjust includes/excludes (via
     `review_checkpoint` flags or a new scan), then **review again**.
   - `stop` → end `/uo-init`.

7. Only after `scope_confirmed.yaml` exists: stage confirmed files, then MCP index.
   Current `codebase-memory-mcp.index_repository` **only** accepts `repo_path`
   (no file-list argument). **Never** pass the whole parent workspace
   (e.g. `FAG_test`) as `repo_path` — that indexes thousands of nodes and can
   pin CPU for minutes.

```powershell
python -X utf8 "$SCRIPT_DIR/stage_cbm_scope.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
# then MCP index_repository:
#   repo_path = <UO_ROOT>/cbm/index_stage
#   mode = fast
#   name = <op>-phase0-scope
```

   If staging fails, stop and ask the user; do **not** fall back to whole-repo
   indexing and do **not** skip writing accurate index meta.

8. `prepare_operator.py --write-index-meta --cbm-project <project>`.
   - **Must reuse the incomplete current run** (plugin default). Do **not** pass
     `--force-new-run` here; that forks a second run and breaks `finalize_phase0`
     (`scope_scan` / `scope_review` / `scope_confirmed` look missing).
9. `finalize_phase0.py` write receipt + shallow entry hints.

No `facts/**` / old `graphs/**` Phase1-3 artifacts are required after this.

## Extract (deterministic directed trace)

```powershell
python -X utf8 "$SCRIPT_DIR/resolve_entrypoints.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35 --write
```

Read `ir/entrypoint_candidates.yaml`.

- High-confidence unique roles may already be selected.
- For roles in `llm_required_roles` (low confidence / multi-candidate / missing),
  dispatch `uo-semantic-resolve` **entrypoint confirmation** only.
  Feed **only** `ir/entrypoint_candidates.yaml` role slices + signature snippets.
  Do **not** ask the subagent to read plugin Python sources.
  Prefer MCP codebase-memory for one ambiguous symbol.
  Expected confirm patch shape:

```yaml
version: 1
roles:
  kernel_entry:
    name: <best candidate name>
    file_path: op_kernel/arch35/...
    confirmed_by: llm
    rationale: ...
```

  Then:

```powershell
python -X utf8 "$SCRIPT_DIR/resolve_entrypoints.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35 --write --confirm-patch "$UO_ROOT/ir/entrypoint_confirm.yaml"
```

### Extract plan (LLM confirm → plan-driven host/kernel)

After entrypoints are confirmed:

```powershell
python -X utf8 "$SCRIPT_DIR/propose_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35 --write
```

Dispatch `uo-semantic-resolve` **extract plan confirmation** using the mandatory
template in `prompts/00_subagent_dispatch.md` (task C). Subagent writes only
`ir/extract_plan.yaml` from `ir/extract_plan_candidates.yaml` (no invented names).

```powershell
python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --check
python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write
```

Build the layered IR (requires `ir/extract_plan.yaml` for host/kernel):

```powershell
python -X utf8 "$SCRIPT_DIR/build_layered_kb.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35
```

This writes:

```text
ir/entrypoint_candidates.yaml
ir/entrypoints.yaml
ir/extract_plan_candidates.yaml
ir/extract_plan.yaml
ir/tilingkey_space.yaml
ir/host_subgraph.yaml
ir/kernel_subgraph.yaml
ir/golden.yaml
ir/bridge.yaml
ir/operator_graph.yaml
ir/unresolved.yaml
contracts/testcase.yaml
tiling/exhaustive_key_space.yaml
tiling/coverage_model.yaml
tiling/key_predicates.yaml
tiling/key_cards/KEY_*.yaml
kernel/branches.yaml
kernel/runtime_conditions.yaml
query/routes.yaml
query/terminology.yaml
cross_layer/impact_graph.yaml
```

`build_layered_kb` also runs code-only `extract_key_predicates` (non-fatal) to materialize
`tiling/key_cards` skeletons (`set_by.expr_raw` + file:line; `host_reachable`/`hit_recipe` stay unknown).

Host graph spans Input/Attr/Platform -> Predicate/HostBranch -> TilingKey/TilingData/BlockDim/Workspace/Dispatch
using **confirmed extract_plan writers/receivers** (no closed helper-name whitelist).
Kernel graph classifies branches as `compile_time` vs `runtime`, merging plan aliases
into TDF determinant normalization.
Bridge reconcile emits `unused_tiling_field` / `missing_tiling_field_producer`.

Optional rebuild of key cards only:

```powershell
python -X utf8 "$SCRIPT_DIR/extract_key_predicates.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --architecture arch35 --write
```

## Resolve (bounded LLM)

Dispatch **one** `uo-semantic-resolve` agent using the **mandatory residual
dispatch template** in `prompts/00_subagent_dispatch.md` (do not invent
`residuals:` / `resolution: warning` / exhaustive “resolve all N items”).

1. Residual resolve: sample by pattern from `ir/unresolved.yaml` (≤12 ids) for
   **simple** false_positive / host-only patterns.
2. Collect `escalate_keys` (and any remaining KEY/shape-complex open items).
3. Optional batch consistency review: branch rows only
   (`binding_time`, `condition`, `file:line`) — skip if already consistent.

Agent writes only `ir/resolution_patch.yaml` with schema
`unresolved_resolutions[].status ∈ {resolved,accepted,false_positive,alias}`
plus optional `escalate_keys`.
Parent **propagates** same-pattern siblings and writes `ir/resolution_ledger.yaml`.

### Complex KEY → parallel uo-query (required)

If `escalate_keys` is non-empty **or** open unresolved still look KEY/shape-complex
after propagate: follow `skills/uo-query/references/complex-unresolved-escalation.md`
and the per-KEY template in `prompts/00_subagent_dispatch.md`.

- Launch **one subagent per KEY in parallel** (cap 8).
- Each writes `ir/key_shape_resolve/<KEY_ID>.yaml` with a real `shape_expr`.
- Parent merges → resolution_patch → apply. **Do not** finish with bare unsolved
  KEY gaps.

Open unresolved must become empty (or only `needs_human` with AskQuestion) —
do not treat “left untouched” as success.

Validate then apply (parent gate — never ask the subagent to hand-count ids):

```powershell
python -X utf8 "$SCRIPT_DIR/apply_resolution.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --patch "$UO_ROOT/ir/resolution_patch.yaml" --check
# if rejected_count>0: resume same dispatch identity with rejected list only
python -X utf8 "$SCRIPT_DIR/apply_resolution.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --patch "$UO_ROOT/ir/resolution_patch.yaml"
# if escalate_keys / complex KEY remain: parallel per-KEY uo-query, merge, apply again
# if open unresolved remain: second residual round on remaining *simple* ids only, then apply again
python -X utf8 "$SCRIPT_DIR/kb_query_export.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --view testcase-contract --profile lean
python -X utf8 "$SCRIPT_DIR/export_kb_graph.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_kb_integrity.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
# check_kb_integrity 会刷新 summary/human_overview.md（写入 integrity 状态）
```

If integrity fails, stop and show `checks/integrity.yaml` / `checks/final.yaml`.
Do not invent facts; second residual round only for still-open **simple** ids;
complex KEY gaps go through per-KEY uo-query, not another thin sample.

## KB product review (required before finish)

After integrity pass, dispatch **one** `uo-kb-review` using the mandatory
template in `prompts/00_subagent_dispatch.md`.

- `verdict=pass` → **must** re-export overview so `kb_review` is not stuck at `pending`:

```powershell
python -X utf8 "$SCRIPT_DIR/export_human_views.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

  then mark Todo7 complete and end `/uo-init`
- `verdict=fail` → rework by `rework_stage` (max **2** loops), re-run affected
  steps + integrity, then review again
- Third fail → stop and present `review/kb_product_review.yaml`

## Hard Rules

- Phase 0 `macro_scope` human review is mandatory; never auto-`continue`.
- Narrowing scope: use `review_checkpoint.py --replace-initial` (not hand-edit YAML).
- Do not invent legacy scripts outside `uo/scripts` (see `skills/understand-operator/PATHS.md`).
- Do not dispatch host/flow/kernel-slice/review/abstraction/graph-review agents.
- Allowed subagents: `uo-semantic-resolve`, `uo-kb-review`, and **per-KEY
  `uo-query` escalate** tasks (one KEY per subagent, parallel).
  Entrypoint/extract-plan tasks of semantic-resolve remain allowed.
- Query and TestAgent are read-only consumers of `.understand-operator/`.
- User-facing language is Chinese unless the user asks otherwise.
