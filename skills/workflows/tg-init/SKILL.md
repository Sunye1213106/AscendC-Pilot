---
name: tg-init
description: >-
  构建测例契约 / 测项合同与绑定、测试工具初始化。用户说 tg-init、建测例契约时加载。
  Pilot 管阶段；加载后执行 acp start tg-init。
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

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `kb_check` | 校验定稿 KB | `tg-init/kb-check` | `deterministic-tg-engine` | `deterministic_engine` |
| `contract_build` | 构建合同骨架 | `tg-init/contract-build` | `deterministic-tg-engine` | `deterministic_engine` |
| `semantic_bind` | 语义绑定 | `tg-init/semantic-bind` | `tg-semantic-bind` | `producer` |
| `bind_merge` | 绑定合并 | `tg-init/bind-merge` | `deterministic-tg-engine` | `deterministic_engine` |
| `mid_nest` | 中间量闭合 | `tg-init/mid-nest` | `deterministic-tg-engine` | `deterministic_engine` |
| `integrity_gate` | 完整性校验 | `tg-init/integrity-gate` | `deterministic-tg-engine` | `deterministic_engine` |
| `init_audit` | Init 审计 | `tg-init/init-audit` | `tg-init-audit` | `referee` |
| `human_confirm` | 人工确认 | `tg-init/human-confirm` | `human` | `-` |
