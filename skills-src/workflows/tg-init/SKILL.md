---
name: tg-init
description: >-
  构建测项合同与绑定。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# tg-init

构建测项合同与绑定。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

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
