# Agent IO Protocol

Read the relevant Phase receipt and write only candidate JSON. Agents never
write formal Facts YAML, document headers, stable IDs, relation IDs, SRC IDs,
source text, or hashes. Python is the only formal-Facts writer; validators are
the only writers of `checks/*validation.yaml`.
For Phase 1 this supersedes `11_phase1_boundary_yaml_authoring.md`'s legacy
YAML examples.

For each 5–10 candidate batch: create JSON conforming to
`spec/schemas/candidate/candidate_batch.schema.json`, run
`validate_candidate_batch.py`, then run `compile_candidate_facts.py`. The
compiler atomically replaces same-`fact_key` entries in the catalog target.
Candidate items use `fact_key`, `kind`, `fields`, and `source_locations` only;
relations use semantic endpoint keys. Include unresolved information rather
than inventing facts. Parallel agents must not modify another owner's target.

Run `validate_fact_stage.py` only after an agent/stage completes. If local
validation or compilation fails, repair the same candidate JSON batch; do not
edit the formal YAML or relax schemas/ownership rules.

