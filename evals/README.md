# evals

Dry-first evaluation layer for AscendC-Pilot.

| Layer | Path | When |
|-------|------|------|
| L0 Static | `smoke.py` | PR / CI |
| L1 Skill dry | `skills/<id>/` | via smoke |
| L1 Skill live | `skills/<id>/live/` | nightly opt-in only |
| L2 Harness E2E | `harness_e2e/` | via smoke (no LLM) |
| Examples | `python -m evals.run_example --all` | via smoke |

| Path | Role |
|------|------|
| `harness/runner.py` | Shared metrics: pass@1, pass^k, context_tokens, tool_calls |
| `routing/` | Skill / slash-entry description trigger precision / recall (no LLM) |
| `skills/<id>/` | with_skill vs without_skill dry cases |
| `harness_e2e/` | authorize fail-closed scenarios |
| `run_example.py` | Worked-example layout regression |
| `smoke.py` | CI L0 entry |

Cognitive skills under eval: `operator-analysis`, `testcase-generation`, `source-proof`, `code-review`.

Agent / LLM modes stay opt-in (see `scripts/closure_acceptance_harness.py --mode agent`).
