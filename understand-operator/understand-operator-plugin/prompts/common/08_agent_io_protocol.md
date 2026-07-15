# Agent IO Protocol

Read the relevant Phase receipt and write only candidate JSON. Agents never
write formal Facts YAML, document headers, stable IDs, relation IDs, SRC IDs,
source text, or hashes. Python is the only formal-Facts writer; validators are
the only writers of `checks/*validation.yaml`.

For Phase 1, read `11_phase1_candidate_authoring.md` as the authoring contract.

For each 5-10 candidate batch: create JSON conforming to
`spec/schemas/candidate/candidate_batch.schema.json`, run
`validate_candidate_batch.py`, then run `compile_candidate_facts.py`. The
compiler atomically replaces same-canonical-identity entries in the catalog
target.

Candidate items use only `local_id`, `kind`, display `name`, structured
`identity`, semantic `fields`, and `source_locations`. Candidate relations use
`type`, structured `source`/`target` reference objects, semantic `fields`, and
`source_locations`.

`local_id` is batch-local only. It may reference only `items[]` in the current
Candidate JSON batch and expires immediately after compilation. Later batches
must reference compiled facts with `ref_type: entity` or `ref_type: symbol`, not
with an older `local_id`.

Do not generate `fact_key`, `relation_key`, `source_fact_key`,
`target_fact_key`, formal stable IDs, relation IDs, source IDs, `source_text`,
or hashes. Do not put guessed IDs in `*_ref` fields. Use local/entity/symbol
reference objects instead.

Names are display labels only. Identity is derived by Python from structured
identity fields. Never use a display name as a cross-fact reference.

Include unresolved information rather than inventing facts. Parallel agents
must not modify another owner's target.

Run `validate_fact_stage.py` only after an agent/stage completes. If local
validation or compilation fails, repair the same candidate JSON batch; do not
edit the formal YAML or relax schemas/ownership rules.
