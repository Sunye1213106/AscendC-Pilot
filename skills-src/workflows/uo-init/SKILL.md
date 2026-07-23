                ---
                name: uo-init
                description: >-
                  首次建立 UO KB。 Harness 管阶段；本 Skill 只索引 Action。
                disable-model-invocation: true
                ---

                # uo-init

                首次建立 UO KB。

                本 Skill 不定义工作流阶段。执行时：

                1. 调用 `harness start/resume`；
                2. 调用 `harness next`；
                3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
                4. 执行一个 Action；
                5. 将结果交回 Harness。

                ## Actions

                | action_id | 名称 | method | agent |
                |---|---|---|---|
                | `prepare_layout` | 创建知识库目录 | `uo-init/prepare-layout` | `deterministic-uo-engine` |
| `scope_confirmation` | 确认分析范围 | `uo-init/scope-confirmation` | `ascendc-agent` |
| `extract_plan` | 抽取计划与分层 IR | `uo-init/extract-plan` | `uo-semantic-resolve` |
| `key_triage` | KEY 粗分 | `uo-init/key-triage` | `uo-key-resolve` |
| `key_resolution` | KEY 语义闭合 | `uo-init/key-resolution` | `uo-key-resolve` |
| `confidence_report` | 生成置信度报告 | `uo-init/confidence-report` | `deterministic-uo-engine` |
| `confidence_review` | 置信度原因审查 | `uo-init/confidence-review` | `uo-confidence-review` |
| `export_integrity` | 导出与完整性校验 | `uo-init/export-integrity` | `deterministic-uo-engine` |
| `kb_review` | KB 产物审查 | `uo-init/kb-review` | `uo-kb-review` |
