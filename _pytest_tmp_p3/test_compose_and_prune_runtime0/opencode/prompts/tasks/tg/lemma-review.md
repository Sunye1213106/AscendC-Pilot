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

- Follow `skills/source-proof/SKILL.md` (referee-replay section / `skills/source-proof/references/referee-replay.md` via that skill)

- Replay only; do not open new hypotheses

# Return

`accept` | `reject` | `defer` per candidate.
