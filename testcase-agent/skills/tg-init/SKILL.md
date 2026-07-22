---
name: tg-init
description: >-
  TG stage-1: thin contract + semantic binding + domain confirm.
  Parent auto-loops uo-query Tasks until csv-closure + audit pass + --confirm.
  User only runs /tg-init (embeds former tg-contract / tg-domain-review).
argument-hint: "<算子仓> --op-name <op> --test-script-root <测试工具> | --merge-uo-resolve | --verify-csv-closure | --confirm"
---

# Skill: tg-init

## Purpose

测试工具 + **定稿 KB** → `.testcase-generator/<op>/` **confirmed** realization
（lexicon merge 完成、csv-closure pass、audit pass）。

## Trigger

- 用户 `/tg-init`，或需要合同摄入 / KEY 绑定 / 域确认
- **不适用**：已 confirmed 后只做覆盖规划（`/tg-plan`）；已批准 plan 后求解 CSV（`/tg-solve`）；
  KB 缺失 / integrity fail / 需重建图 → `/uo-init` 或 `/uo-update`（建库断边用 UO sen，**不是**本 Skill）

## Inputs

| 权威 | 说明 |
|---|---|
| `PROJECT_ROOT` + 定稿 `$UO_ROOT` | **只读**语义事实源；缺库 → `uo_init_required` |
| `--test-script-root` | CSV consumer / 测试工具根（CSV↔HOST 映射来自本侧） |
| `realization/uo_query_resolve/*.yaml` | 待 merge 证据（非 SMT 真值，直至 merge） |

冲突优先：merge 后的 `binding_lexicon.yaml` > 未 merge 的 resolve 文件 > 启发式脚手架。  
**禁止生成**：改写 `$UO_ROOT/**`、伪造 `init.status=confirmed`、完整 `operator_graph` dump。

## Outputs

正式（**仅** `$OUT_ROOT`）：`realization/{consumer_*,realization_map,binding_lexicon,domain_*,unresolved}.yaml`、
`contract/testcase.yaml`（TG 拥有的测项合同：CSV 域 × KB refs）、
`realization/uo_merge_report.yaml`、`init/audit_report.yaml`、`init/kb_fingerprint.yaml`、`init.status=confirmed`。

中间：`uo_query_resolve/`、`mid_symbol_queue.yaml`、`bind/*`。

**禁止产物**：任何 `$UO_ROOT/**` 写入（含 `ir/input_derivable*`、`key_shape_resolve`、`contracts/**`）；
手改 lexicon「修过」；伪 `confidence: high`；CSV 行 / Z3 模型（属 solve）。

## Invariants

- **隔离**：UO 图只读；TG 绑定断边 / CSV↔`HOST_ATTR_*` 映射只写 `$OUT_ROOT`
- Lexicon = SMT 可执行真值；resolved → **仅** `confidence: high`；叶子 ⊆ `VAR_CSV_*`
- 允许 uo-query 修 **TG 绑定断边**（含 `unsolved` KEY→CSV）；**禁止**回写 UO 分类文件或代替建库 sen
- 合法 skip 仅：见 `references/legitimate-skips.md`（含 `not_input_derivable`）
- 禁伪 unresolved：`cross_variable_*`、`runtime_derived_*`、`depends_on_*_chain` 等
- 幂等：可重跑 thin contract / merge；禁静默改用户已 confirm 的锁
- 用户只发 `/tg-init`；父代理全自动 WHILE，禁止追问「是否继续第二轮」
- 语言/思考：简体中文（`prompts/common/language.md`）

## Tool Policy

### MUST

```powershell
tg-init "<算子仓>" --op-name <op> --test-script-root "<测试工具>"
# 绑定环（父代理）：
tg-init "<算子仓>" --op-name <op> --merge-uo-resolve
tg-init "<算子仓>" --op-name <op> --verify-csv-closure
tg-init "<算子仓>" --op-name <op> --confirm
```

- 语义绑定：Task Follow `understand-operator/skills/uo-query/SKILL.md`（并行 cap=8）
- 派发合同：`prompts/init/dispatch.md`；命令块：`prompts/init/workflow.md`
- 终审：Task `tg-init-audit` → `init/audit_report.yaml` pass 后才 `--confirm`

### MAY

- thin 缺口：Task `tg-csv-contract`（仅 inventory 证据内补 bind）
- 兼容 CLI `tg-contract`（内部；用户勿当主入口）

### MUST NOT

- 父代理循环 `uo_kb_query` 当主路径；整读 `operator_graph.yaml`
- 写入 / Edit `$UO_ROOT/**`（含 `input_derivable*`、`key_shape_resolve`）；改算子源码 / 测试脚本糊弄过门
- 会话 Edit lexicon / domains 绕过 merge；伪造 audit pass
- 向用户暴露 `/tg-contract`、`/tg-domain-review` 为必经步骤

## Workflow

| Phase | Entry | Actions | Exit | Fail |
|---|---|---|---|---|
| 0 KB | 用户触发 | `require_kb` | fresh KB | `uo_init_required` |
| 1 Contract | KB ok | thin AST contract（脚本） | inventory + gaps | `CONTRACT_*` |
| 2 Bind | gaps 非空 | 并行 uo-query Tasks → resolve YAML | KEY 文件齐 | `UNRESOLVED_SEMANTICS` |
| 3 Merge | resolve 齐 | `--merge-uo-resolve` | merge pass + 域对称 | `fake_not_csv_excuse` / `domain_asymmetry` |
| 4 Nest | mid 非空或 verify fail | mid/KEY 套娃（见 references） | queue 空 | 轮次用尽 → `ask=` |
| 5 Gate | merge ok | `--verify-csv-closure` + audit | 双 pass | audit fail → 自动回 Phase 2 |
| 6 Confirm | audit pass | `--confirm` | `init.status=confirmed` | `audit_required` |

细节：`references/tg-uo-query-escalation.md`、`tg-mid-symbol-nesting.md`、`tg-init-audit.md`、
`tg-contract-phase.md`。

## Semantic Escalation

| 适合脚本 | 适合 LLM / uo-query |
|---|---|
| AST contract、merge、verify-csv-closure、域对称校验 | KEY/中间量语义、无法静态别名的 binding gap |
| mid queue 过滤算术垃圾 | 跨函数 dtype / tiling / host 约束 |

每批 gap cap=8。证据不足 → `unresolved` + 稳定 reason_code，禁止猜满。

## Failure Taxonomy

`uo_init_required` · `CONTRACT_FAIL` · `UNRESOLVED_SEMANTICS` · `fake_not_csv_excuse` ·
`domain_asymmetry` · `CSV_CLOSURE_FAIL` · `audit_required` · `INVALID_PATH` · `TOOL_FAILURE`

## Quality Gate

- [ ] `uo_merge_report.status=pass`；`--verify-csv-closure` pass
- [ ] `init/audit_report.yaml` status=pass；无伪 high / 伪 not_csv
- [ ] `mid_symbol_queue` 空；`init.status=confirmed`
- [ ] 未改 UO KB / approved plan（尚无 plan）

## Stop Conditions

- KB 缺失 / stale → 停并提示 `/uo-init` 或 `/uo-update`
- 轮次用尽仍有 open mid → 停并向用户报告 `ask=`（中间不得提问）
- PLUGIN_ROOT / prompts 缺失 → 停并提示 `install.ps1`
