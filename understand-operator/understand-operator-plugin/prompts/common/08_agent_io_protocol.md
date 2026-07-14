# Agent IO Protocol

Read the relevant Phase receipt before writing facts. Write only paths allowed by `spec/ownership.yaml`.

Business agents do not write validator reports. Python validators are the only writers of `checks/*validation.yaml`.

Parallel agents must not modify shared files. Agents must not relax schemas or ownership rules.

Do not overwrite a large fact YAML by hand. Use the deterministic fact writer:

1. Create or refresh the target skeleton with `prepare_fact_file.py`.
2. Merge at most 5-10 new `items`, `relations`, or `unresolved` entries per
   batch with `merge_fact_entries.py`.
3. Read the file back after each merge.
4. Run the scoped file/stage validator.
5. Repair in the same owning agent context before starting the next batch.

If writing or validation fails, the orchestrator resumes the same owning
subagent. It must not create a new general agent to rewrite the file.

Model-authored YAML is allowed only as a small temporary merge batch. A batch
contains `items`, `relations`, and/or `unresolved`; it contains no artifact or
snapshot header. The prepared final fact file remains owned by the deterministic
writer. Phase 1 boundary batches must also follow
`prompts/common/11_phase1_boundary_yaml_authoring.md`.

