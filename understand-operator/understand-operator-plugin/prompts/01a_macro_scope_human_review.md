# Phase 0 Scope Review

Review the Phase 0 scope discovery artifacts:

```text
runs/<current_run_id>/phase0/scope_proposal.yaml
runs/<current_run_id>/phase0/scope_scan.yaml
```

The review must show the proposed candidate files by category, candidate
directories, excluded groups, and warnings. Phase0 intentionally only performs
lightweight scope discovery; deep operator understanding starts after CBM
indexing.

Before the user confirms, do not call CBM and do not read source files at scale.

Record decisions only through:

```powershell
python review_checkpoint.py <repo> --op-name <op> --gate macro_scope --decision continue
```

That command writes:

```text
runs/<current_run_id>/phase0/scope_review.yaml
runs/<current_run_id>/phase0/scope_confirmed.yaml
```

It must not write a Phase 0 receipt. The receipt is written only by
`finalize_phase0.py` after confirmed-file CBM indexing and Phase 0 checks pass.
