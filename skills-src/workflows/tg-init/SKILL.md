                ---
                name: tg-init
                description: >-
                  构建测项合同与绑定。 Harness 管阶段；本 Skill 只索引 Action。
                disable-model-invocation: true
                ---

                # tg-init

                构建测项合同与绑定。

                本 Skill 不定义工作流阶段。执行时：

                1. 调用 `harness start/resume`；
                2. 调用 `harness next`；
                3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
                4. 执行一个 Action；
                5. 将结果交回 Harness。

                ## Actions

                | action_id | 名称 | method | agent |
                |---|---|---|---|
                | `kb_check` | 校验定稿 KB | `tg-init/kb-check` | `deterministic-tg-engine` |
| `contract_build` | 构建合同骨架 | `tg-init/contract-build` | `tg-csv-contract` |
| `semantic_bind` | 语义绑定 | `tg-init/semantic-bind` | `deterministic-tg-engine` |
| `bind_merge` | 绑定合并 | `tg-init/bind-merge` | `deterministic-tg-engine` |
| `mid_nest` | 中间量闭合 | `tg-init/mid-nest` | `deterministic-tg-engine` |
| `integrity_gate` | 完整性校验 | `tg-init/integrity-gate` | `deterministic-tg-engine` |
| `init_audit` | Init 审计 | `tg-init/init-audit` | `tg-init-audit` |
| `human_confirm` | 人工确认 | `tg-init/human-confirm` | `human` |
