# Task

Replay producer lemma certificates from this round's Round Analysis and adjudicate.
These are in-round claims (expected-growth rejects), not end-of-search cleanup.

# Targets

`<TARGET_IDS_OR_FILES>`

# Evidence

- Use the evidence pack declared by the current Action bundle/session context
- Producer certificates for the assigned targets
- Cross-check against current R and latest `round_analysis.yaml` / reject observations

# Context

- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

# Requirements

- Follow the packaged `source-proof` domain skill; let that skill select any referee-replay reference it needs, and do not assume a Host-specific physical Skill/reference path
- Replay only; do not open new hypotheses
- Reject certificates that treat search miss or bare Host reject as unreachability

# Return

`accept` | `reject` | `defer` per candidate.
