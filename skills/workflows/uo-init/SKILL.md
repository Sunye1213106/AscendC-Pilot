---
name: uo-init
description: 首次编译 AscendC CodeMap（operator.uo）：准备范围 → Clang 抽取 → 确定性 Pass → 缺口消解 →
  写入 .uo → 审查。用户提到建库、CodeMap、只分析某架构时加载。 Pilot 管阶段；加载后执行 acp start uo-init。
---

# uo-init

编排 AscendC CodeMap Compiler（UO）首次构建。

领域认知（勿在此复述）：`skills/domain/uo-codemap-build`。  
引擎：`engines/understand-operator`。

正式产物：

```text
.ascendc-pilot/uo/<op_name>.<arch>.uo
```

阶段关系：

```text
prepare → extract → analyze → resolve → commit → review
```

细粒度 extract_*/normalize_*/export_* 是 engine 内部步骤，不是 Pilot Action。

## Pilot

`acp start` → `next` → `run-action` →（语义则 finalize）→ `advance`。  
关键参数不清时 AskQuestion。禁止用手工文件表代替 `acp uo-scope scan`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `prepare` | `primary_interactive` | `ascendc-pilot` | `controller` | `uo-init/prepare` | `uo/scope-confirmation` | `uo-prepare-v1` |
| `extract` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/extract` | `-` | `uo-extract-v1` |
| `analyze` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/analyze` | `-` | `uo-analyze-v1` |
| `resolve` | `subagent` | `uo-semantic-resolver` | `producer` | `uo-init/resolve` | `uo/resolve-gaps` | `resolve-gaps-v1` |
| `apply_gap_patch` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/apply-gap-patch` | `-` | `gap-patch-v1` |
| `commit` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/commit` | `-` | `uo-commit-v1` |
| `review` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/review` | `uo/kb-review` | `uo-review-v1` |

<!-- END GENERATED ACTIONS -->
