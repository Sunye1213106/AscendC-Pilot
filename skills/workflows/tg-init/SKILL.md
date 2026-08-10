---
name: tg-init
description: 测例契约与绑定：变量/IO/TilingKey 维信息提取。用户说 tg-init、建测例契约、tilingkey 绑定时加载。默认 tilingkey_full_coverage（无需
  CSV）。Pilot 管阶段；加载后 acp start tg-init。
---

# tg-init

编排 TG 初始化。领域认知：`skills/domain/tg-init`。

阶段：`intent → kb_ready → contract → bind → gate → confirm`。

权威 UO 是 `.ascendc-pilot/uo/<op>.<arch>.uo`（CodeMap）。`kb_check` 确认其中的 TG 视图
（`tiling/exhaustive_key_space`、`ir/tg_host_view`、`ir/operator_graph`），并写入
`tg/init/uo_ready.yaml`。视图缺失时用
`python -m uo_init.dump <op>.uo --materialize-tg --op-root <算子目录>` 物化进同一 `.uo`。

## Pilot

`acp start` → `next` → `run-action` →（语义则 finalize）→ `advance`。

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
