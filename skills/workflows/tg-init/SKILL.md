---
name: tg-init
description: 构建测例契约 / 测项合同与绑定、测试工具初始化。用户说 tg-init、建测例契约时加载。 Pilot 管阶段；加载后执行 acp start
  tg-init。
---

# tg-init

构建测项合同与绑定。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

前置条件：

- 定稿 UO KB（`uo_ready`）
- 测试脚本 / CSV 消费端目录：`--test-script-root` / `csv_consumer_root` / `ASCENDC_TEST_SCRIPT_ROOT`

**测试脚本路径不明确 → 立刻 AskQuestion**：未给出 `--test-script-root` 且环境变量也未设时，**同一轮** `question` 请用户粘贴测试脚本根目录；禁止 Glob 全盘猜路径、长篇纠结。已明确则直接 `acp start tg-init --test-script-root <路径>`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `kb_check` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/kb-check` | `-` | `uo-ready-v1` |
| `contract_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/contract-build` | `-` | `csv-contract-v1` |
| `semantic_bind` | `subagent` | `tg-semantic-bind` | `producer` | `tg-init/semantic-bind` | `tg/semantic-bind` | `semantic-bind-v1` |
| `bind_merge` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/bind-merge` | `-` | `bind-merge-v1` |
| `mid_nest` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/mid-nest` | `-` | `mid-nest-v1` |
| `integrity_gate` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/integrity-gate` | `-` | `tg-integrity-v1` |
| `init_audit` | `subagent` | `tg-init-audit` | `referee` | `tg-init/init-audit` | `tg/init-audit` | `init-audit-v1` |
| `human_confirm` | `primary_interactive` | `human` | `-` | `tg-init/human-confirm` | `tg/human-confirm` | `init-confirmed-v1` |

<!-- END GENERATED ACTIONS -->

