# evals

Dry-first evaluation layer for AscendC-Pilot.

| Path | Role |
|------|------|
| `harness/runner.py` | Shared metrics: pass@1, pass^k, context_tokens, tool_calls, context_efficiency |
| `routing/` | Skill description trigger precision / recall (no LLM) |
| `skills/<id>/` | with_skill vs without_skill dry cases |
| `smoke.py` | CI entry (`evals-smoke` job) |

Agent / LLM modes stay opt-in (see `scripts/closure_acceptance_harness.py --mode agent`).
