# TG 算子语义 → Task Follow `/uo-query` → `--merge-uo-resolve`

## Lexicon 问题（必读）

`binding_lexicon.key_derivations` = SMT 真值。仅有 `uo_query_resolve` 却不 merge → plan/solve 仍用错误/启发式 expr。

## HARD

- 每个 needs_binding KEY：**父代理** Task Follow `uo-query/SKILL.md`（cap 8）— **不问用户**
- 查库：**在 uo-query Task 内**先 sqlite 图 `uo_kb_query --pattern …`；父代理禁循环刷图 CLI；禁止整读 `operator_graph.yaml`
- **`confidence: high` only**；叶子 ⊆ `VAR_CSV_*`（TG 侧 CSV↔HOST 映射）；禁止占位 expr
- **只写 `$OUT_ROOT`**：`realization/uo_query_resolve/<KEY>.yaml`；**禁止** Edit / 写入 `$UO_ROOT/**`
- **禁伪 not_csv**（ses_07b1）：下列借口 → merge `ask=fake_not_csv_excuse`，必须改写 LogicExpr + 套娃：
  - `cross_variable_comparison_not_csv_realizable`（`eq`/`ne` 即可）
  - `runtime_derived_*` / `runtime_shape_*` / `template_selection_*`
  - `depends_on_*_chain` / 伪造 `empty_allowlisted: true`
- 合法 skip 仅：见 `legitimate-skips.md`（含 **`not_input_derivable`** / 核内局部）
- Host 上下文只读 **一跳** `host_parent_hints` + KB 图 `determined_by`/`reaches_input`；**禁止**期望完整 `host_derivation_chain` 倾倒
- `not_input_derivable_keys` 不进 Task
- `unsolved_input_derivable_keys`：**可读** UO `ir/input_derivable_gaps.yaml` 作证据，仍派 uo-query 闭合到 `VAR_CSV_*`（写 OUT_ROOT）；**不**回写 UO `input_derivable*`，也**不**因此强制回 `/uo-init`
- 中间量自动套娃（`tg-mid-symbol-nesting.md`）；算术/LOOP_LOCAL 碎片不进 queue
- Parent **禁止**向用户说「是否继续第二轮」— audit fail → 自动再 WHILE
- Merge 输入 **仅** `realization/uo_query_resolve/*.yaml`；**永不**读 `$UO_ROOT/ir/key_shape_resolve`

## 流程（父代理全自动 · 可多轮）

```text
needs_binding_keys（已排除 not_input_derivable）
  → 并行 Task（图查询优先；prompt 附 host_parent + roots）→ OUT_ROOT/.../KEY_*.yaml
  → --merge-uo-resolve
  → WHILE mid_symbol_queue 非空 OR verify fail OR audit fail:
        并行 mid/KEY Tasks → merge → --verify-csv-closure
        （禁止问用户；达轮次上限才向用户报 ask=…）
  → tg-init-audit pass → --confirm → tg-plan
```

## Kernel 第二段

只追 **chaseable** 标识符（`IS_ATTEN_MASK`、`IS_BN2_MULTIBLK`…）。  
**忽略**：`((x-p)+1) le y`、`HEAD_DIM_ALIGN gt 512`、`ENABLE_*`、LOOP_LOCAL / PLATFORM_MACRO。

## 值域不对称

merge/solve 会拒域外常量；optional 列不得偷写成常量 0 糊弄（须真实 presence 语义或修 domain_review）。
