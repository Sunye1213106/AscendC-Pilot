---
name: tg-init
description: 测例契约与绑定：变量/IO/TilingKey 维信息提取。用户说 tg-init、建测例契约、tilingkey 绑定时加载。默认 tilingkey_full_coverage（无需
  CSV）。Pilot 管阶段；加载后 acp start tg-init。
---

# tg-init

从定稿 UO KB + `tg_host_view` 构建测项合同与绑定。

语义方法：`skills/domain/tg-init/SKILL.md`。

链路：`uo-init → tg-init → tg-plan → tg-solve`。

## Pilot

1. `acp start` → `acp next` → `acp run-action <action_id>`
2. 语义 Action：派发 Bundle 声明 actor → `--finalize`
3. `acp advance`（仅消费可信收据）
4. 前置：`uo_ready` + 新鲜 `uo/ir/tg_host_view.yaml`；csv_consumer 才需要 test_script_root

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `init_intent` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/init-intent` | `-` | `tg-init-intent-v1` |
| `kb_check` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/kb-check` | `-` | `uo-ready-v1` |
| `contract_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/contract-build` | `-` | `tilingkey-contract-v1` |
| `semantic_bind` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/semantic-bind` | `-` | `tilingkey-binding-v1` |
| `bind_merge` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/bind-merge` | `-` | `bind-merge-v1` |
| `mid_nest` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/mid-nest` | `-` | `mid-nest-v1` |
| `integrity_gate` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/integrity-gate` | `-` | `tilingkey-integrity-v1` |
| `init_audit` | `subagent` | `tg-init-audit` | `referee` | `tg-init/init-audit` | `tg/init-audit` | `init-audit-v1` |
| `human_confirm` | `primary_interactive` | `ascendc-pilot` | `controller` | `tg-init/human-confirm` | `tg/human-confirm` | `init-confirmed-v1` |

<!-- END GENERATED ACTIONS -->
