# uo-init timing baseline

Harness: `engines/understand-operator/tools/timing_baseline.py`.

## How to measure

Cold and warm in one pass, against a throwaway cache root so the first
run really is a first-ever parse:

```powershell
python engines/understand-operator/tools/timing_baseline.py --measure --write-doc
```

Or from two captured stderr logs of `acp run-action`:

```powershell
$env:UO_TIMING = "1"
acp run-action extract_host 2> cold.err   # empty UO_CACHE_ROOT
acp run-action extract_host 2> warm.err   # same root, second time
python engines/understand-operator/tools/timing_baseline.py `
    --from-stderr cold.err --warm-stderr warm.err --write-doc
```

Warm re-run goal (sources unchanged): full uo-init pipeline **≤ 2 minutes**
(`UO_WARM_REPLAY_BUDGET_S`, gated in CI).

Cold start goal: uo-init pipeline **≤ 3 minutes** (`UO_COLD_BUDGET_S=180`) under
the default profile `UO_INIT_PROFILE=fast` (`closure_mode=keypath`,
one dtype `kernel_ir` walk overlapped with host IR via **ProcessPool** TU walks,
merged frame/index AST pass, optional native `uo_walk`, tilingdata extract,
`fold_kernel=false`, API clang skipped).  Opt into the previous complete path
with `UO_INIT_PROFILE=full` (may exceed the cold budget).

## Actions

Wall clock for the whole action. `extract_host` is the one this harness
drives directly; the others are separate `acp run-action` steps and are
measured by capturing their own stderr.

| Action | Cold (s) | Warm (s) | Notes |
|--------|---------:|---------:|-------|
| `prepare_layout` | not yet measured | not yet measured | separate action; capture its stderr |
| `scope_validate` | not yet measured | not yet measured | internal prepare gate; capture its stderr |
| `extract_host` | ~max(host,1×kernel) (`fast`) / ~180 (`full`) | 1.388 | `fast`: 1 dtype kernel \|\| host; skips API clang |
| `extract_tiling_key` | not yet measured | not yet measured | separate action; capture its stderr |
| `extract_kernel` | not yet measured | not yet measured | pairwise fold expensive; fold_kernel=false skips harness |
| `normalize_variables` | not yet measured | not yet measured | separate action; capture its stderr |
| `derive_key_fields` | not yet measured | not yet measured | fields wall can sum to minutes; isolate workers add more (host_derivation) |
| `normalize_predicates` | not yet measured | not yet measured | separate action; capture its stderr |
| `export_kb` | not yet measured | not yet measured | separate action; capture its stderr |
| `export_tg_host_view` | not yet measured | not yet measured | FAG cached export 31.7s → 2.0s (fingerprint reuse) |
| `quality_gate` | not yet measured | not yet measured | separate action; capture its stderr |

## Inside `extract_host`

Σ over every occurrence of the phase. Phases that fan out across
translation units sum above the wall clock of the call — that is the
parallelism, not an inconsistency.

| Phase | Σ cold (s) | Σ warm (s) |
|-------|-----------:|-----------:|
| `BuildContext.load` | 0.011 | 0.011 |
| `api_contract.done` | 62.842 | 0.207 |
| `api||kernel||bind` | 130.677 | 0.467 |
| `bind.done` | 0.033 | 0.035 |
| `build_host_ir` | 49.049 | 0.178 |
| `discover` | 0.111 | 0.114 |
| `host_ir.walk_tu` | 284.918 | 0.597 |
| `kernel_ir.done` | 130.676 | 0.466 |
| `kernel_ir.walk` | 389.629 | 1.077 |
| `var_model+platform` | 0.537 | 0.605 |
| `walk_file` | 674.316 | 1.674 |

## FAG cold-fast hotspot baseline (2026-08)

Operator: FAG arch35, `UO_INIT_PROFILE=fast`, cold cache.
Source: full-pipeline `UO_TIMING=1` action walls (not yet driven by
`timing_baseline.py` harness for every action).

| Action | Cold wall (s) | Notes | First target |
|--------|--------------:|-------|-------------:|
| `scope_scan` | 10.9 | inventory; P2 cache later | — |
| `extract_host` | **49.5** | parse 2–3s/TU; `ast_walk` 37–38s/TU | 25–35 |
| `extract_tiling_key` | 1.5 | leave alone | — |
| `extract_kernel` | 0.6 | fast path | — |
| `normalize_variables` | 0.4 | leave alone | — |
| `derive_key_fields` | **33.8** | HostIR cache hit ~0.9s; rest is field derive + spawn | ≤20 |
| `normalize_predicates` | 0.5 | leave alone | — |
| `export_kb` | **29.1** | HostIR cache hit ~0.8s; YAML-hash + JSON dump dominate | ≤12 |
| `build_index` | 0.5 | already fast | — |
| **pipeline** | **~130–140** | three hotspots ≈ 112s | **&lt;100** (stretch 70–90) |

Optimization order: AST walk pruning → persistent derive workers →
serialize-once export (see Codemap / uo-init acceleration plan).

## Still anecdotal

Numbers from code comments / execution notes:

- Kernel pairwise fold: expensive; disable with `fold_kernel=false`.
- `export_tg_host_view`: FAG cached export **31.7s → 2.0s** after fingerprint reuse ([`../fag_test/fag-arch35-static-blocker-execution-20260806.md`](../fag_test/fag-arch35-static-blocker-execution-20260806.md)；历史材料，不当权威).

## Cache knobs (warm path)

| Env | Default | Effect |
|-----|---------|--------|
| `UO_TIMING` | `1` | Emit `[uo-timing]` stderr lines |
| `UO_TU_CACHE` | `1` | Durable libclang walk IR under `uo/cache/tu/` |
| `UO_HOST_IR_POOL` | `process` | Multi-TU host walks: `process` (default) or `thread` |
| `UO_NATIVE_WALK` | `1` | Use optional native `uo_walk` when built |
| `UO_WALK_BIN` | — | Override path to native walker |
| `UO_DERIVE_CACHE` | `1` | Per-field derive rows under `uo/cache/derive/` |
| `UO_FOLD_CACHE` | `1` | clang `-ast-dump` fold under `uo/cache/fold/` |
| `UO_CTRL_WORKERS` | `1` | Controllability pool size (keep 1; >1 often regresses) |
| `UO_WARM_REPLAY_BUDGET_S` | `120` | CI warm replay budget |
| `closure_mode` | product `full`; `_ensure_bundle` → `off` when meta exists | Skip deep controllability on downstream actions |

_Status: cold target **≤180s** (`UO_COLD_BUDGET_S`); ProcessPool TU walks + merged frame/index pass + optional native `uo_walk`. Prior FAG fast cold was ~185s (≤240s budget). Warm re-run still targets ≤120s._
