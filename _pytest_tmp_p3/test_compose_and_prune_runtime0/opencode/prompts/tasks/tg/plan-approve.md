<task>
Approve or reject the exact TG target set produced by plan_build.
</task>

<instructions>
1. Review `target_set.yaml` and `coverage_obligations.yaml` for the current level.
2. Verify the target mode matches the user's intent. No explicit target means `all_declared`.
3. Require non-empty T, T ⊆ D, and present `target_hash`, `snapshot_hash`, and `plan_hash`.
4. Approval freezes that exact target set. `tg-solve` must not widen it; any target change requires a new plan.
5. Do not approve reachability/unreachability conclusions here; Plan only approves what Solve must attempt to close.
6. Follow `skills/testcase-generation/SKILL.md`.
</instructions>

<output>
`APPROVE` | `REVISE` | `BLOCKED`, with a concise reason. On APPROVE the deterministic primary action records the approved plan hash.
</output>
