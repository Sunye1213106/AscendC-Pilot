# Phase 0 Scope Review

Review the deterministic Phase 0 scope artifacts:

```text
runs/<current_run_id>/phase0/scope_scan.yaml
runs/<current_run_id>/phase0/semantic_enrichment.yaml
cbm/index_meta.json
```

The review must show initial operator files, dependency-discovered files outside
the operator directory, public headers, public implementation files, registration
files, Proto/API files, architecture variants, excluded files, system and
third-party dependencies, and unresolved dependencies.

Record decisions only through:

```powershell
python review_checkpoint.py <repo> --op-name <op> --gate macro_scope --decision continue
```

That command writes:

```text
runs/<current_run_id>/phase0/scope_review.yaml
```

It must not write a Phase 0 receipt. The receipt is written only by
`finalize_phase0.py` after all Phase 0 checks pass.

