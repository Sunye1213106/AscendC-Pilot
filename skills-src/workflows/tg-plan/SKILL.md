                ---
                name: tg-plan
                description: >-
                  生成覆盖义务并人工批准。 Harness 管阶段；本 Skill 只索引 Action。
                disable-model-invocation: true
                ---

                # tg-plan

                生成覆盖义务并人工批准。

                本 Skill 不定义工作流阶段。执行时：

                1. 调用 `harness start/resume`；
                2. 调用 `harness next`；
                3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
                4. 执行一个 Action；
                5. 将结果交回 Harness。

                ## Actions

                | action_id | 名称 | method | agent |
                |---|---|---|---|
                | `plan_scope` | 确定规划范围 | `tg-plan/plan-scope` | `deterministic-tg-engine` |
| `plan_precheck` | 规划前置门禁 | `tg-plan/plan-precheck` | `deterministic-tg-engine` |
| `plan_build` | 生成覆盖义务 | `tg-plan/plan-build` | `deterministic-tg-engine` |
| `plan_approve` | 批准规划 | `tg-plan/plan-approve` | `human` |
