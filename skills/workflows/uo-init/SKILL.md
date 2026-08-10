---
name: uo-init
description: '首次构建 AscendC `.uo` CodeMap：确定范围与 BuildVariant、抽取 CompilerFacts、 运行确定性
  CodeMap Pass、只消解显式语义缺口、写入并审查单一 `.uo`。 用户要求建 UO/CodeMap、首次分析算子或指定 architecture 建图时使用。

  '
---

# uo-init

首次构建 AscendC CodeMap。领域规则按需读取 `skills/domain/uo-codemap-build/SKILL.md`。

```text
prepare → extract → analyze → resolve → commit → review
```

正式产物：`.ascendc-pilot/uo/<op_name>.<arch>.uo`。

## 执行边界

- `prepare`：确定性扫描优先；只有真实 scope / architecture 歧义才由 primary 判断。
- `extract`、`analyze`、`apply_gap_patch`、`commit`、`review`：engine 直接执行，无 Agent、无 task prompt。
- `resolve`：唯一 UO 构建语义 Agent，只处理当前 bundle 的 unresolved gaps。
- `apply_gap_patch` 是 `resolve` 阶段内部确定性 merge Action，不是额外公开阶段。

Pilot 只按 `acp start` / `next` / `run-action` / `advance` 返回的当前 Action 执行；语义 producer 完成后由 primary finalize。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `prepare` | `primary_interactive` | `ascendc-pilot` | `controller` | `uo-init/prepare` | `uo/scope-confirmation` | `uo-prepare-v1` |
| `extract` | `deterministic` | `human` | `deterministic_engine` | `uo-init/extract` | `-` | `uo-extract-v1` |
| `analyze` | `deterministic` | `human` | `deterministic_engine` | `uo-init/analyze` | `-` | `uo-analyze-v1` |
| `resolve` | `subagent` | `uo-semantic-resolver` | `producer` | `uo-init/resolve` | `uo/resolve-gaps` | `resolve-gaps-v1` |
| `apply_gap_patch` | `deterministic` | `human` | `deterministic_engine` | `uo-init/apply-gap-patch` | `-` | `gap-patch-v1` |
| `commit` | `deterministic` | `human` | `deterministic_engine` | `uo-init/commit` | `-` | `uo-commit-v1` |
| `review` | `deterministic` | `human` | `deterministic_engine` | `uo-init/review` | `-` | `uo-review-v1` |

<!-- END GENERATED ACTIONS -->
