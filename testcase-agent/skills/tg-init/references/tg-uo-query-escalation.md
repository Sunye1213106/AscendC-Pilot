# TG 算子语义 → Task Follow `/uo-query` → `--merge-uo-resolve`

## Lexicon 问题（必读）

`binding_lexicon.key_derivations` = SMT 真值。仅有 `uo_query_resolve` 却不 merge → plan/solve 仍用错误/启发式 expr。

## HARD

- 每个 needs_binding KEY：**父代理** Task Follow `uo-query/SKILL.md`（相近可打包，cap 8）— **不问用户**
- **`confidence: high` only**；禁止 `medium`/`low` 标 resolved
- 交付须含可执行 `key_derivation.expr`（禁止 `already_bound_in_kb`、`deter_branch`、`then==else`、`op: call`、未展开 `Get*`）
- 交付须含 `shape_determined` + **`derivation_chain` 叶子 ⊆ `VAR_CSV_*`**
- 中间量（`bnSparseLimit`/`deterSparseType`…）：**父代理自动套娃**（`tg-mid-symbol-nesting.md`）；禁止把追符号作业甩给用户
- empty 族可暂缓；非 empty unresolved → merge/confirm 失败
- Parent **只** CLI merge/list-open-mids/verify；禁止手改 lexicon
- Parent **禁止**循环 `uo_kb_query`；禁止向用户说「请你对 xxx 开 Task」

## 流程（父代理全自动 · 用户零操作）

```text
needs_binding_keys
  → 并行 Task Follow uo-query → KEY_*.yaml
  → --merge-uo-resolve
  → WHILE mid_symbol_queue 非空: 并行 mid Task → merge   # 自动，不问用户
  → WHILE kernel unbound 可追: 并行 Task → merge
  → --verify-csv-closure   # 必须 pass
  → tg-init-audit → --confirm → tg-plan
```

## Kernel 条件闭合（第二段）

读 `realization/realization_map.yaml` 的 `abstract_branches` / `alignment_report`：

1. 保留 `determinant_source` ∈ {TilingKey, KernelVariable, TilingDataField, UnboundTemplateSymbol}
2. reason ∈ {UNBOUND_ATOM, UNBOUND_CMP, UNBOUND_KVAR, UNBOUND_CALL, KEY_DERIVATION_MISSING}
3. **忽略** LOOP_LOCAL / PLATFORM_MACRO / empty
4. 按符号聚合（cap ~8 Task），Follow uo-query：`neighbors_of` + CBM → 写 `derivation_chain` 直到 `VAR_CSV_*`
5. 再 merge + `--verify-csv-closure`；不可 CSV 实现的非 empty 仍拦 confirm（须继续追或标清 compile-time）

## 值域不对称

merge/solve 会拒：`eq(VAR_CSV_*, 0)` 而 `0∉domain`；`keep_prob=[NONE]` 与浮点语义冲突等。
