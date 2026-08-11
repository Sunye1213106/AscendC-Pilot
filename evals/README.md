# evals

Dry-first evaluation layer for AscendC-Pilot.

| Path | Role |
|------|------|
| `harness/runner.py` | Shared metrics: pass@1, pass^k, context_tokens, tool_calls, context_efficiency |
| `routing/` | Skill / slash-entry description trigger precision / recall (no LLM) |
| `skills/<id>/` | with_skill vs without_skill dry cases for the four cognitive skills |
| `smoke.py` | CI entry (`evals-smoke` job) |

Cognitive skills under eval: `operator-analysis`, `testcase-generation`, `source-proof`, `code-review`.

Agent / LLM modes stay opt-in (see `scripts/closure_acceptance_harness.py --mode agent`).
