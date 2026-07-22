# 范围人工审查（Phase0）

## Task

审查宏范围提案，硬停止等待确认，确认后再做窄索引。

## Authoritative Inputs

- `runs/<run_id>/phase0/scope_proposal.yaml`
- 算子树与 sibling `common/` 发现结果（脚本产出）
- 确认菜单：`init/scope_menu.md`

## Procedure

1. 读 proposal：展示分类（算子包 / common / 排除项）与警告
2. **硬停止** → Follow `scope_menu.md`（AskQuestion 四选项；禁自动 continue）
3. 有 sibling `common/` 时：confirmed **必须**含裁剪后非空 `common/`；禁把 `PROJECT_ROOT` 抬到多算子父仓
4. 仅 `continue` 后：

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

## Hard Constraints

- MUST：只索引 `$UO_ROOT/cbm/index_stage`（禁父工作区）
- MUST：`index_meta.indexed_via=mcp` 且 `cbm_project` 非空
- MUST NOT：未确认就 extract；用本地 CBM CLI 顶替 MCP

## Exit

`finalize_phase0` 通过 → 进入 Extract（`workflow.md` Phase 1）。

## Failure

`finalize` 报错（缺 project / indexed_via）→ 停并修复 meta，禁止跳过。
