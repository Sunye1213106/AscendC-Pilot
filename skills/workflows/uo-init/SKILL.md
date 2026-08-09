---
name: uo-init
description: 首次建立 UO KB：范围确认 → 静态扫描 → 导出 tg_host_view。用户提到建库、只分析某架构 （如 arch35）、host
  投影时加载。Pilot 管阶段；加载后执行 acp start uo-init。
---

# uo-init

编排首次 UO KB 建立与 Host 投影导出。

领域认知（勿在此复述）：`skills/domain/uo-kb-build`。  
引擎：`engines/understand-operator`。

阶段关系：

```text
prepare → scope → extract → normalize → export → review
```

语义 Action（如 resolve_gaps / kb_review）走 Bundle 声明 actor。

## Pilot

`acp start` → `next` → `run-action` →（语义则 finalize）→ `advance`。  
关键参数不清时 AskQuestion。禁止用手工文件表代替 `acp uo-scope scan`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `prepare_layout` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/prepare-layout` | `-` | `kb-layout-v1` |
| `scope_scan` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/scope-scan` | `-` | `scope-candidates-v1` |
| `scope_confirm` | `primary_interactive` | `ascendc-pilot` | `controller` | `uo-init/scope-confirm` | `uo/scope-confirmation` | `scope-confirmed-v1` |
| `extract_host` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/extract-host` | `-` | `extract-host-v1` |
| `extract_tiling_key` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/extract-tiling-key` | `-` | `extract-tiling-key-v1` |
| `extract_registry` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/extract-registry` | `-` | `extract-registry-v1` |
| `extract_kernel` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/extract-kernel` | `-` | `extract-kernel-v1` |
| `normalize_variables` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/normalize-variables` | `-` | `normalize-variables-v1` |
| `derive_key_fields` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/derive-key-fields` | `-` | `derive-key-fields-v1` |
| `normalize_predicates` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/normalize-predicates` | `-` | `normalize-predicates-v1` |
| `resolve_gaps` | `subagent` | `uo-gap-resolve` | `producer` | `uo-init/resolve-gaps` | `uo/resolve-gaps` | `resolve-gaps-v1` |
| `apply_gap_patch` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/apply-gap-patch` | `-` | `gap-patch-v1` |
| `export_kb` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-kb` | `-` | `export-kb-v1` |
| `build_index` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/build-index` | `-` | `build-index-v1` |
| `export_tg_host_view` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-tg-host-view` | `-` | `export-tg-host-view-v1` |
| `export_adapter_pack` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-adapter-pack` | `-` | `export-adapter-pack-v1` |
| `export_integrity` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-integrity` | `-` | `integrity-v1` |
| `kb_review` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/kb-review` | `uo/kb-review` | `kb-review-v1` |

<!-- END GENERATED ACTIONS -->
