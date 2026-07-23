                ---
                name: tg-solve
                description: >-
                  Z3 求解与 CSV 投影。 Harness 管阶段；本 Skill 只索引 Action。
                disable-model-invocation: true
                ---

                # tg-solve

                Z3 求解与 CSV 投影。

                本 Skill 不定义工作流阶段。执行时：

                1. 调用 `harness start/resume`；
                2. 调用 `harness next`；
                3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
                4. 执行一个 Action；
                5. 将结果交回 Harness。

                ## Actions

                | action_id | 名称 | method | agent |
                |---|---|---|---|
                | `solve_precheck` | 求解前置校验 | `tg-solve/solve-precheck` | `deterministic-tg-engine` |
| `z3_solve` | 求解并投影 | `tg-solve/z3-solve` | `deterministic-tg-engine` |
| `cover_confirm` | 覆盖确认 | `tg-solve/cover-confirm` | `deterministic-tg-engine` |
