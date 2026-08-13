<task>
批准或驳回 `plan_build` 产出的精确 TG 目标集合。
</task>

<context>
批准会冻结该目标集；`tg-solve` 不得擅自扩大。改目标必须重新 plan。
本步只批准“Solve 必须尝试闭合什么”，不断言可达/不可达。
方法细节见打包 Skill `testcase-generation`。
</context>

<instructions>
1. 审阅当前 level 的 `target_set.yaml` 与 `coverage_obligations.yaml`。
2. 核对 target mode 是否匹配用户意图；未显式指定则为 `all_declared`。
3. 要求：T 非空、T ⊆ D，且存在 `target_hash` / `snapshot_hash` / `plan_hash`。
4. 不要在此批准 reachability / unreachability 结论。
</instructions>

<output>
返回 `APPROVE` | `REVISE` | `BLOCKED`，并附简短理由。
`APPROVE` 后由确定性 primary action 把已批准的 plan hash 写入 `tg/plan/levels/*/human_supplement.yaml`。
</output>
