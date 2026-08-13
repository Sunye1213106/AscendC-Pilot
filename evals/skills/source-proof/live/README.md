# Live skill eval (opt-in)

Requires an explicit model host. Default CI must **not** score live cases as
pass@k. Without a product or model the harness **skips** and labels `skip`.

```bash
# Dry (CI):
python evals/smoke.py
python evals/skills/run_skill_eval.py --skill source-proof

# Live skip (no model — expected in CI):
python evals/live/run.py
python evals/skills/run_skill_eval.py --skill source-proof --live

# Live run (opt-in):
ASCENDC_PILOT_LIVE_EVAL=1 \
ASCENDC_LIVE_EVAL_CMD='your-runner --flag' \
ASCENDC_LIVE_PRODUCT=/path/to/operator \
python evals/live/run.py
```

Fixed cases: `evals/live/cases.yaml` (~20, from operator-analysis / uo-query
examples plus the other cognitive skills).
