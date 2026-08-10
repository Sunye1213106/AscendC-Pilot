<task>
Determine the exact TilingKey target selector for this TG run. Do not construct cases, run replay, or decide reachability.
</task>

<context>
- Project: `<PROJECT_ROOT>`
- TG: `<TG_ROOT>`
- Current operator/architecture come from Pilot context and `.uo`.
</context>

<instructions>
1. Preserve any explicit packed TilingKey list the user supplied as `target_mode: explicit_keys`.
2. Preserve any requested TilingKey dimension/value filter as `target_mode: dimension_filter`.
3. If the user did not specify a target, choose `target_mode: all_declared`; this means T equals the complete current Kernel-declared domain D.
4. Do not infer unreachable keys, derive 19-dimensional formulas, or call SAT/SMT in planning.
5. Surface contradictory or ambiguous target requests instead of silently broadening them.
6. Follow `skills/domain/tg-plan/SKILL.md`.
</instructions>

<output>
Return only the planning intent needed to build `target_set.yaml`: target mode, explicit keys or dimension filter, and any blocking ambiguity. The later deterministic `plan_build` validates T ⊆ D and freezes its hash.
</output>
