<task>
批准或驳回 `plan_build` 产出的精确 TG 目标集合。
</task>

<context>
批准会冻结该目标集；`tg-solve` 不得擅自扩大。改目标必须重新 plan。
本步只批准“Solve 必须尝试闭合什么”，不断言可达/不可达。
方法细节见打包 Skill `testcase-generation`。
AskQuestion 文案由控制面生成。
</context>

<instructions>
1. 审阅当前 level 的 `target_set.yaml` 与 `coverage_obligations.yaml`。
2. 核对 target mode 是否匹配用户意图；未显式指定则为 `all_declared`。
3. 要求：T 非空、T ⊆ D，且存在 `target_hash` / `snapshot_hash` / `plan_hash`。
4. 不要在此批准 reachability / unreachability 结论。
5. Host 弹出 AskQuestion；选项必须原样使用控制面返回的 `ask_question.options`。
6. Primary 禁止 Write `human_supplement.yaml`。选「批准并开始求解」后由 Host `--finalize` 写入。
</instructions>

<output>
不写文件。批准后由 Host finalize 把已批准的 plan hash 写入 `tg/plan/levels/*/human_supplement.yaml`。
</output>
