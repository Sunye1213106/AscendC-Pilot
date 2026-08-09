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

Cold start goal: uo-init pipeline **≤ 4 minutes** (`UO_COLD_BUDGET_S=240`) under
the default profile `UO_INIT_PROFILE=fast` (`closure_mode=keypath`,
one dtype `kernel_ir` walk overlapped with host IR, tilingdata extract,
`fold_kernel=false`, API clang skipped).  Opt into the previous complete path
with `UO_INIT_PROFILE=full` (may exceed the cold budget).

## Actions

Wall clock for the whole action. `extract_host` is the one this harness
drives directly; the others are separate `acp run-action` steps and are
measured by capturing their own stderr.

| Action | Cold (s) | Warm (s) | Notes |
|--------|---------:|---------:|-------|
| `prepare_layout` | not yet measured | not yet measured | separate action; capture its stderr |
| `scope_confirm` | not yet measured | not yet measured | separate action; capture its stderr |
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

## Still anecdotal

Numbers from code comments / execution notes, for the actions this
harness has not driven yet:

- `derive_key_fields`: per-field seconds can sum to minutes; isolate workers hide more wall time (`host_derivation.HostDerivation.phase_seconds`).
- Kernel pairwise fold: expensive; disable with `fold_kernel=false`.
- `export_tg_host_view`: FAG cached export **31.7s → 2.0s** after fingerprint reuse (`docs/fag/fag-arch35-static-blocker-execution-20260806.md`).

## Cache knobs (warm path)

| Env | Default | Effect |
|-----|---------|--------|
| `UO_TIMING` | `1` | Emit `[uo-timing]` stderr lines |
| `UO_TU_CACHE` | `1` | Durable libclang walk IR under `uo/cache/tu/` |
| `UO_DERIVE_CACHE` | `1` | Per-field derive rows under `uo/cache/derive/` |
| `UO_FOLD_CACHE` | `1` | clang `-ast-dump` fold under `uo/cache/fold/` |
| `UO_CTRL_WORKERS` | `1` | Controllability pool size (keep 1; >1 often regresses) |
| `UO_WARM_REPLAY_BUDGET_S` | `120` | CI warm replay budget |
| `closure_mode` | product `full`; `_ensure_bundle` → `off` when meta exists | Skip deep controllability on downstream actions |

_Status: measured cold full-pipeline under `UO_INIT_PROFILE=fast` (1 dtype kernel ‖ host + tilingdata): **185s** on FAG arch35 (≤240s budget). Warm re-run still targets ≤120s._
