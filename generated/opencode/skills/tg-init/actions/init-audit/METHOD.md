# init_audit (migrated domain method)

> Domain content migrated from skills-src/tg-init/references/tg-init-audit.md. Do not advance Harness state from this file.

# tg-init 终审清单（tg-init-audit subagent）

在 `--merge-uo-resolve` 之后、`--confirm` 之前执行。产物根：`.ascendc-agent/tg/`。

**真值源**：本表 `id` 列 = `init/audit_report.yaml` checks[].id =（子集）`--verify-csv-closure` 的 `gates` 键。  
合法 skip：`legitimate-skips.md`。

## 检查项（全量）

| id | 层 | 读什么 | 通过条件 |
|----|----|--------|----------|
| `lexicon_resolve_sync` | audit | `uo_query_resolve/KEY_*.yaml` vs lexicon | resolved KEY 有非 null expr；与 resolve 一致 |
| `confidence_high_only` | verify+audit | resolve / lexicon | resolved → **仅** `confidence: high` |
| `chain_to_csv` | verify+audit | chain / expr | 叶子 ⊆ `VAR_CSV_*` 或 compile-time lit |
| `no_opaque_fn_leaf` | audit | shape_expr / expr | 无未展开 `Get*` / `op: call`（verify 的 `chain_to_csv` 已含部分 opaque） |
| `nonempty_keys_resolved` | verify+audit | resolve status | 非合法 skip 不得 unresolved；禁伪 `not_csv` |
| `binding_resolve_coverage` | verify+audit | `binding_inventory.needs_binding_keys` vs `uo_query_resolve/KEY_*.yaml` | 每个 needs_binding KEY **必须**有 resolve 文件（禁真空过门） |
| `unresolved_honesty` | audit | resolve skip | skip 必须 ∈ `legitimate-skips.md`（含 `not_input_derivable`） |
| `domain_symmetry` | verify+audit | lexicon vs CSV 域 | 无域外常量（脚本 `require_domain_symmetry`） |
| `domain_align` | audit | domain_review vs map | KEY 所用 CSV 域一致 |
| `tiling_domain_ok` | audit | tiling 相关域 | 非残缺（optional 哨兵除外） |
| `no_placeholders` | verify+audit | lexicon / resolve | 无 `already_bound_in_kb` / `deter_branch` / `then==else` |
| `merge_report` | verify+audit | `uo_merge_report.yaml` | `status=pass` |
| `merge_artifacts` | verify+audit | map + shape graph 文件 | 存在且 merge 产物齐全 |
| `full_csv_closure` | verify+audit | lexicon 叶子 vs shape closure | 可闭包中间量已闭合；叶子 ⊆ CSV∪closure |
| `mid_symbol_drained` | verify+audit | `mid_symbol_queue.yaml` | `symbols` 为空 |
| `shape_graph_built` | verify+audit | `bind/shape_derivation_graph.yaml` | `status=built`；有 resolved 时 closure 非空 |
| `shape_chain_consistent` | audit | lexicon vs graph | 依赖可达 |
| `unbound_reducible` | verify+audit | abstract vs closure | abstract unbound 不得仍 ∈ closure |
| `kernel_shape_progress` | audit | alignment TilingKey | 已 resolved KEY 不应大量 `KEY_DERIVATION_MISSING` |

### 层含义

- **verify**：`--verify-csv-closure` → `require_full_csv_closure().gates`（键名与上表 id **同名**）

## 写出

`init/audit_report.yaml`（全量 id 见 `$PLUGIN_ROOT/agents/references/init-audit-schema.md`）。  
`status=fail` → 禁止 `--confirm`。

## CLI

禁止直调 `tg-init … --verify-csv-closure`（Plugin 拦截）。  
verify 层由 `harness run-action integrity_gate` 完成；本 Action 只写 `init/audit_report.yaml` 审查结论，然后：

```powershell
harness run-action init_audit --finalize --project "<算子仓>"
```
