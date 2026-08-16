# Infer scenarios from code or a diff

**When to load**：freshness 确认后，审核 engine 写出的 `ce-scenario-set/v1`。

合法 id 与何时挂上：`references/scenario-catalog.md`。Agent **不得发明 id**。

## Two entries

| Entry | Source | What to scan |
| --- | --- | --- |
| `static` | 无 diff | `kernel_api`（Cast/DataCopy/EnQue）、`buffer`、切分字段写点 |
| `diff` | change capture | 切片里的锚点（OPERATION / BUFFER / BRANCH / KERNEL） |

截断切片或 stale UO 是披露边界，不是「没有精度/性能影响」。

Engine 写骨架。Agent 只填 knobs staging；Host `scenario_apply` 合并后再确认。不得用审查叙述把精度/性能放进 `V`。

## Engine steps

**Static (no diff)**：`kernel_api` 扫 Cast / DataCopy / DataCopyPad / EnQue / DeQue；再扫 `buffer` 与切分字段写点（`field` / `tiling_data`）；按目录映射，不得发明 id；`origin: inferred` + 目录默认预算。

**Diff**：确认 change capture SHA 与 UO `source_revision` / fingerprint；锚点覆盖 OPERATION / BUFFER / BRANCH / KERNEL（不只 Host writers）；切片保留 `truncated`；截断进 `blind_spots`，不是空影响；每场景一项义务；精度/性能保持 `external` 直到 `ce-external-evidence/v1` 收据。

Forbidden：用审查叙述关闭精度/性能；把 Host-only impact 当成 kernel-only diff 的完整影响；从 scenario overlay 扩成 `tilingkey_full_coverage`。

## Output shape

每项：`id`、`risk_class`、`anchors[]`、`knobs`、`budget`、`oracle`、`origin`（`inferred` | `user`）。语料检索是 engine 的事。
