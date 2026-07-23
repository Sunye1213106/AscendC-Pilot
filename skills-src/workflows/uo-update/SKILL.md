                ---
                name: uo-update
                description: >-
                  增量更新 UO KB；含 diff_only。 Harness 管阶段；本 Skill 只索引 Action。
                disable-model-invocation: true
                ---

                # uo-update

                增量更新 UO KB；含 diff_only。

                本 Skill 不定义工作流阶段。执行时：

                1. 调用 `harness start/resume`；
                2. 调用 `harness next`；
                3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
                4. 执行一个 Action；
                5. 将结果交回 Harness。

                ## Actions

                | action_id | 名称 | method | agent |
                |---|---|---|---|
                | `detect_changes` | 检测源码变更 | `uo-update/detect-changes` | `deterministic-uo-engine` |
| `plan_update` | 制定更新计划 | `uo-update/plan-update` | `uo-semantic-resolve` |
| `apply_update` | 应用变更 | `uo-update/apply-update` | `uo-semantic-resolve` |
| `key_resolution` | KEY 语义闭合 | `uo-update/key-resolution` | `uo-key-resolve` |
| `confidence_report` | 生成置信度报告 | `uo-update/confidence-report` | `deterministic-uo-engine` |
| `confidence_review` | 置信度原因审查 | `uo-update/confidence-review` | `uo-confidence-review` |
| `export_integrity` | 导出与完整性校验 | `uo-update/export-integrity` | `deterministic-uo-engine` |
| `diff_summary` | 只读差异摘要 | `uo-update/diff-summary` | `deterministic-uo-engine` |
| `diff_only` | 仅差异摘要（跳过完整更新） | `uo-update/diff-only` | `deterministic-uo-engine` |
