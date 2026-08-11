# Live skill eval (opt-in, nightly)

Requires a model host. Default CI must **not** run this directory.

```bash
# Example (host-specific):
# ASCENDC_PILOT_LIVE_EVAL=1 python -m evals.skills.run_skill_eval --skill source-proof --live
```

Until `--live` is implemented for a given host, keep dry cases under
`evals/skills/<id>/cases.yaml` and worked examples under `skills/<id>/examples/`.
