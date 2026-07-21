# tg-init 终审清单（tg-init-audit subagent）

在 `--merge-uo-resolve`（含 kernel 第二段）之后、`--confirm` 之前执行。产物根：`.testcase-generator/<op>/`。

## 检查项

| id | 读什么 | 通过条件 |
|----|--------|----------|
| `lexicon_resolve_sync` | `uo_query_resolve/KEY_*.yaml` vs `binding_lexicon.key_derivations` | resolved KEY 有非 null expr；与 resolve 一致 |
| `confidence_high_only` | resolve / lexicon | **任一 resolved 必须 `confidence: high`**；禁 medium/low |
| `chain_to_csv` | `derivation_chain` / expr | 叶子 ⊆ `VAR_CSV_*` 或 compile-time lit |
| `no_opaque_fn_leaf` | shape_expr / expr | 无未展开 `Get*` / `op: call` |
| `nonempty_keys_resolved` | resolve status | 非 empty 白名单不得 unresolved |
| `domain_symmetry` | lexicon vs csv domains | 无域外常量；`require_domain_symmetry` |
| `no_placeholders` | lexicon / resolve | 无 `already_bound_in_kb`、`deter_branch`、`then==else`、假 resolved |
| `domain_align` / `tiling_domain_ok` | domain_review vs map | KEY 所用 CSV 域一致且非残缺（optional 哨兵除外） |
| `merge_report` | `uo_merge_report.yaml` | `status=pass`（禁手写 lexicon 跳过 merge） |
| `merge_artifacts` | map + shape graph | `realization_map` + `shape_derivation_graph` 存在 |
| `full_csv_closure` | `--verify-csv-closure` | **可闭包中间量队列必须为空**；lexicon 叶子 ⊆ CSV∪closure |
| `shape_graph_built` | `bind/shape_derivation_graph.yaml` | `status=built`；有 resolved KEY 时 closure 非空 |
| `shape_chain_consistent` | lexicon vs graph | 依赖可达 |
| `unbound_reducible` | abstract vs closure | abstract unbound 不得仍 ∈ closure |
| `kernel_shape_progress` | alignment TilingKey | 已 resolved KEY 不应仍大量 `KEY_DERIVATION_MISSING` |
| `unresolved_honesty` | empty only | 仅 empty 白名单可 unresolved；须写原因 |
| `mid_symbol_drained` | `mid_symbol_queue.yaml` | `symbols` 为空，否则 fail 并要求套娃 Task |

## 写出

`init/audit_report.yaml`。`status=fail` → 禁止 `--confirm`。

## CLI 辅助

```powershell
tg-init "<算子仓>" --op-name <op> --verify-csv-closure
python -X utf8 -c "from testcase_agent.resolve_policy import require_full_csv_closure, require_high_only, require_chains_terminate_at_csv, require_no_nonempty_unresolved, require_no_placeholders, collect_open_mid_symbols; from testcase_agent.shape_derivation import check_shape_graph_built, check_unbound_reducible; from pathlib import Path; r=Path(r'<OUT_ROOT>'); print(require_full_csv_closure(r)); print(collect_open_mid_symbols(r)); print(check_shape_graph_built(r)); print(check_unbound_reducible(r))"
```
