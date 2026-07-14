# Boundary Agent Compatibility Prompt

The active Phase 1 prompt is `agents/uo-boundary-agent.md`.

Use only the Phase 0 artifacts under:

```text
runs/<current_run_id>/phase0/scope_scan.yaml
runs/<current_run_id>/phase0/semantic_enrichment.yaml
runs/<current_run_id>/phase0/scope_review.yaml
runs/<current_run_id>/phase0/receipt.yaml
cbm/index_meta.json
```

Do not use legacy boundary artifacts. Write only:

```text
facts/operator/interface.yaml
facts/operator/source_files.yaml
facts/operator/entrypoints.yaml
```

Then the orchestrator runs `validate_facts.py --stage step1 --scope boundary --write-report`.

