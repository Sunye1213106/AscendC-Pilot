---
name: tg-init
description: 测例契约与绑定：变量/IO/TilingKey 维信息提取。用户说 tg-init、建测例契约、tilingkey 绑定时加载。默认 tilingkey_full_coverage（无需
  CSV）。Pilot 管阶段；加载后 acp start tg-init。
---

# tg-init

从定稿 UO KB + `tg_host_view` 构建测项合同与绑定。

## 链路位置

```text
uo-init → tg-init → tg-plan → tg-solve
```

## 硬规则

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后 `--finalize`；
5. 调用 `acp advance`（仅消费可信收据）。

## 前置

- `uo_ready` + `uo/ir/tg_host_view.yaml` 存在且 fingerprint 新鲜
- **full 模式**（默认）：无需 `test_script_root`
- **csv_consumer**：才需要 `--test-script-root` / 环境变量；缺则立刻 AskQuestion

## 角色

- **运动员**（csv 模式）`tg-semantic-bind`：写 binding patch，不写正式 lexicon
- **裁判** `tg-init-audit`：审查 init 产物，不改被审正文

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

`bind_merge` / `mid_nest` 仅在 `csv_consumer` overlay 中进入流水线。
