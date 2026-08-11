# Task

Replay producer lemma certificates and adjudicate.

# Targets

`<TARGET_IDS_OR_FILES>`

# Evidence

- Evidence pack: `<LEMMA_EVIDENCE_PATH>`
- Producer certificates for the assigned targets

# Context

- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`

# Requirements

- Follow the packaged `source-proof` domain skill and its `references/referee-replay.md`; do not assume a Host-specific physical Skill path
- Replay only; do not open new hypotheses

# Return

`accept` | `reject` | `defer` per candidate.
