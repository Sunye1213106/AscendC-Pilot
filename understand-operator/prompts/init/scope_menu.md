# 范围确认菜单（`macro_scope` 硬门禁）

## Task

取得用户对 Phase0 `scope_proposal` 的明确决策；未确认禁止索引与 Extract。

## 唯一选项

AskQuestion **恰好**这些：`continue` | `revise` | `stop` | `manual_supplement`

**MUST NOT：** 自动选择 `continue`；把「看起来合理」当成已确认。

## Procedure

1. 展示提案摘要（分类/警告；详见 `macro_scope.md`）
2. AskQuestion 等待用户
3. 写入 checkpoint：

```powershell
python -X utf8 "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --gate macro_scope --decision <continue|revise|stop|manual_supplement>
```

## 决策后果

| 决策 | 后果 |
|---|---|
| `continue` | 写出 `scope_confirmed.yaml` 后方可 `stage_cbm_scope` / MCP index |
| `revise` | 调 scope 后 **再次**本菜单确认 |
| `manual_supplement` | 人工补文件列表后再次确认 |
| `stop` | 结束 init；保留已写目录，不索引 |

## Acceptance

- checkpoint 反映真实用户选择
- 无确认却进入索引 → 流程违规，必须停

## Failure

用户拒绝 → 按 `stop` 或保持等待；禁止默默 continue。
