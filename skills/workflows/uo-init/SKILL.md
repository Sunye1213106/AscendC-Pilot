---
name: uo-init
description: 首次建立 / 创建本地知识库（UO KB）。用户提到建库、只分析某架构分支（如 arch35）时加载。Pilot 管阶段；加载后执行 acp
  start uo-init。
---

# uo-init

首次建立 UO KB。引擎：`engines/understand-operator`（包 `uo_init`）。

## 硬规则

0. **必须先 Tab 切到 `ascendc-pilot`（primary）再跑本 Skill**。
0.5. **关键启动参数不明确 → 立刻 AskQuestion**（算子目录 `--project`、architecture）。
1. **`acp` 是真实 CLI**，禁止按 METHOD 手工模拟工作流。
2. **禁止跳步**：`acp start` → `acp next` → 当前 `action_id`。
3. **确定性 Action**：只跑 `acp run-action <id>`（自动 finalize）。
4. **语义 Action**（如 `resolve_gaps` / `kb_review`）：`run-action` 准备 → 派发 Bundle 声明的 actor → `--finalize`。
   - Primary **禁止**自己 Write `uo/ir/**`。
   - Task 正文只能用 prepare 返回的 `task_prompt_stub` 原样粘贴。
5. **禁止**用 Glob/Read 自编文件表代替 `acp uo-scope scan`。
6. **进度**：遵循公共策略 `pilot-control`。

## 启动

```text
acp start uo-init --project <算子目录> --architecture arch35
acp next
acp run-action <action_id>
```

已有活动 run：按 `needs_human_decision` / AskQuestion 选项处理，禁止静默复用或自动删除。

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
| `normalize_predicates` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/normalize-predicates` | `-` | `normalize-predicates-v1` |
| `resolve_gaps` | `subagent` | `uo-gap-resolve` | `producer` | `uo-init/resolve-gaps` | `uo/resolve-gaps` | `resolve-gaps-v1` |
| `apply_gap_patch` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/apply-gap-patch` | `-` | `gap-patch-v1` |
| `export_kb` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-kb` | `-` | `export-kb-v1` |
| `build_index` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/build-index` | `-` | `build-index-v1` |
| `export_integrity` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-integrity` | `-` | `integrity-v1` |
| `kb_review` | `subagent` | `uo-kb-review` | `referee` | `uo-init/kb-review` | `uo/kb-review` | `kb-review-v1` |

<!-- END GENERATED ACTIONS -->

## 阶段（规格真值）

prepare → scope → extract → normalize → export → review

全部确定性抽取挂 `uo_init.pilot_engines`；无旧 `extract_plan` / `uo.scripts` 路径。
