# 范围人工审查（Phase0）

## Task

审查宏范围提案，硬停止等待确认，确认后再做窄索引。

## Authoritative Inputs

- `runs/<run_id>/phase0/scope_proposal.yaml`（含 `summary.counts` / `summary.included_layers`）
- 脚本 stdout 的 **INCLUDE / EXCLUDE 计数表**（权威展示源）
- 算子树与 sibling `common/` 发现结果（脚本产出）
- 确认菜单：`init/scope_menu.md`

## Procedure

1. 读 proposal / 脚本 stdout：**原样转述** INCLUDE 与 EXCLUDE 两张表（每层同时报 `.cpp` 与 `.h` 数）
2. **禁止**根据 `candidate_files.host` / `headers` 桶自行合成「op_host=N」；host 计数必须以路径前缀层行为准（`op_host/ (top-level)` + `op_host/<arch>/`）
3. **硬停止** → Follow `scope_menu.md`（AskQuestion 四选项；禁自动 continue）
4. 有 sibling `common/` 时：confirmed **必须**含裁剪后非空 `common/`；禁把 `PROJECT_ROOT` 抬到多算子父仓
5. **MUST NOT**：Phase0 派 `explore` / `generalPurpose` 预扫目录；范围只信 `macro_scope_scan` 产物
6. 仅 `continue` 后：

```powershell
python -X utf8 "$SCRIPT_DIR/stage_cbm_scope.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
# MCP index_repository:
#   repo_path = $UO_ROOT/cbm/index_stage
#   mode = fast
#   name = <op>-phase0-scope
python -X utf8 "$SCRIPT_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME" `
  --write-index-meta --cbm-project <mcp_project_name>
# 禁止 --force-new-run
python -X utf8 "$SCRIPT_DIR/finalize_phase0.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

## 展示合同（AskQuestion 前必贴）

```text
=== INCLUDE (candidates) ===
layer                              cpp     h other total
op_host/ (top-level)                 …     …     …     …
op_host/<arch>/                      …     …     …     …
op_kernel/ (top-level)               …     …     …     …
op_kernel/<arch>/                    …     …     …     …
common/.../<arch>/                   …     …     …     …
SUBTOTAL operator / common / TOTAL …

=== EXCLUDE (default / filter) ===
tests/examples/ut/st          — 默认不进候选
other arch* under host/kernel — architecture 过滤
sibling operators …           — 出包范围
```

默认：**tests / examples / ut / st 不进候选**（`--seed` / `manual_supplement` 可显式加回）。

## Hard Constraints

- MUST：只索引 `$UO_ROOT/cbm/index_stage`（禁父工作区）
- MUST：`index_meta.indexed_via=mcp` 且 `cbm_project` 非空
- MUST：AskQuestion 前展示脚本计数表（cpp + h）
- MUST NOT：未确认就 extract；用本地 CBM CLI 顶替 MCP；Phase0 explore 预扫

## Exit

`finalize_phase0` 通过 → 进入 Extract（`workflow.md` Phase 1）。

## Failure

`finalize` 报错（缺 project / indexed_via）→ 停并修复 meta，禁止跳过。
