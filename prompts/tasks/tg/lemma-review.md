# Task

Replay producer lemma certificates and adjudicate.

# Targets

`<TARGET_IDS_OR_FILES>`

# Evidence

- Use the evidence pack declared by the current Action bundle/session context
- Producer certificates for the assigned targets

# Context

- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

# Requirements

- Follow the packaged `source-proof` domain skill; let that skill select any referee-replay reference it needs, and do not assume a Host-specific physical Skill/reference path
- Replay only; do not open new hypotheses

# Return

`accept` | `reject` | `defer` per candidate.
