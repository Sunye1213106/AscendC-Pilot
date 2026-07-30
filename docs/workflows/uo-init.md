# /uo-init

首次建立分层 UO KB。权威结构以 `pilot/ascendc_pilot/workflows/specs.py` 的 `WORKFLOWS["uo-init"]` 为准；本文是人读摘要。

## 阶段（不可跳步）

```text
prepare → scope → extract → normalize → export → review
```

```text
prepare_layout
  → scope_scan（范围检索）
  → scope_confirm（人工确认；无歧义且探针干净可自动）
  → extract_host / extract_tiling_key / extract_registry / extract_kernel
  → normalize_variables（占位）
  → derive_key_fields
  → normalize_predicates（写出 unresolved blockers）
  → resolve_gaps（LLM 分片补全，≤30 blocker/shard）
  → apply_gap_patch（确定性合入 + 派生回环）
  → export_kb / build_index / export_integrity
  → kb_review
```

## 引擎

Pilot `ENGINE_REGISTRY[("uo-init", *)]` → `uo_init.pilot_engines`。

## 启动

```powershell
acp start uo-init --project <算子目录> --architecture arch35
acp next
acp run-action <action_id>
```

范围步骤也可：`acp uo-scope prepare|scan|confirm`（包装同一 `pilot_engines`）。

禁止用 Glob/Read 自编文件表代替 `acp uo-scope scan`；**未 `scope_confirm` 不得 extract**。

## prepare_layout ↔ KB 目录

prepare 种同名骨架（`manifest`/`operator`/`tiling`/`kernel`/`flow`/`summary`/`runs`），OPTIONAL 层写 `status: not_extracted` stub。  
`ir/` `checks/` `indexes/` `cross_layer/` `review/` 故意延后到 extract/export/review 再建。与 `kb_export` 分层同名对应。

## extract 四步（确定性）

| Action | 做什么 |
|--------|--------|
| `extract_host` | libclang 抽 Host IR、可控性、变量域、TPL 绑定、初版 gap；重活 |
| `extract_tiling_key` | 把上一步 binding 写成 `tiling/key_bind_receipt.yaml`（不重算） |
| `extract_registry` | Registry 竞价序 → `tiling/families.yaml` |
| `extract_kernel` | Kernel 按 key 折叠分支（可 skip）→ `kernel/fold_receipt.yaml` |

## normalize 与 LLM 分片

1. `derive_key_fields` → `uo/ir/host_derivation.yaml` + `tiling/key_derivations.yaml`
2. `normalize_predicates` → `uo/ir/unresolved.yaml`（谓词 gap + 派生 undecided，单位是 **blocker**）
3. `resolve_gaps`（subagent `uo-gap-resolve`）
   - 触发：`derivation_blocker_count > 0` **或** `blocker_count ≥ 20`
   - 分片：Host prepare 调 `uo_init.blocker_shards.plan_blocker_shards`，**每 shard ≤ 30**
   - worker 只读本 `inputs/batches/batch_XXX.yaml`，只写 `parts/part_XXX.yaml`
   - 封闭词汇表：`scheduling` / `input_derived` / `validation_assumption` / `genuinely_unknown`
4. `apply_gap_patch` 合并校验 → `gap_bindings.yaml` → 重跑派生（derived 不降、escalating 下降）

## 现状缺口（诚实）

- **K6**：`materialize_tiling` 仍未把 19 维 `value_expr` 联立进 Z3；Pilot `export_kb` 常未传 `tpl_schema`
- `export_kb` 可能覆写 `unresolved.yaml`，丢掉 normalize 写入的派生 blocker 元数据
- `docs/fag/*`、`docs/debug/handoff.md` 是调试快照，**不是**工作流契约

## 不在本链

旧 `extract_plan` / `detect_score_*` / `adjudicate_llm_tasks` / `uo.scripts.*` 已删除。分片调度在 `uo_init.blocker_shards`，不恢复旧脚本包。
