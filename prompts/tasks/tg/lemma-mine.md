# Task

Prove or refute the assigned source lemma leads.

# Targets

`<TARGET_IDS_OR_FILES>`

# Evidence

Closed lead pack only (do not invent leads). Use the companion evidence pack when present.

# Context

- Project: `<PROJECT_ROOT>`
- UO: `<UO_ROOT>`
- TG: `<TG_ROOT>`

# Requirements

- Follow `skills/domain/source-lemma-proof/SKILL.md`
- Close required proof obligations; actively seek counterexamples
- Do not convert missing/search failure into exclusion
- Each candidate must include structured fields:
  - `proposition`: P ⇒ Q
  - `codemap_anchors`: list of `{entity_id or relation_id, query}`
  - `obligations`: list of `{id, status, evidence}` (OPEN/CLOSED/BLOCKED)
  - `source_citations`: list of `{file, line, quote}`
  - `verdict`: PROVED | REFUTED | INSUFFICIENT
- PROVED requires all obligations CLOSED; empty candidates block `lemma_apply`

# Return

`PROVED` | `REFUTED` | `INSUFFICIENT` with evidence.
