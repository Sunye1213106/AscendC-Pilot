---
name: tg-solve
description: >-
  TG stage-3: SMT+CSV for approved level with Allow solve:yes.
  MUST NOT modify approved plan or lexicon; domain-symmetry gate at start.
argument-hint: "<project_root> --op-name <op> --level L0|L1|L2"
---

# Skill: tg-solve

## Purpose

**已批准** coverage plan → realizable CSV rows + uncover 原因码报告。

## Trigger

- 用户 `/tg-solve`；某 level 已 approve 且 `Allow solve:yes`
- **不适用**：未批准 plan（回 `/tg-plan`）；未 confirm init / 域不对称（回 `/tg-init`）；
  建库或改 KB（UO 侧）

## Inputs

| 权威 | 说明 |
|---|---|
| `plan/human_supplement.yaml` + 对应 level 批准快照 | **只读**；本 Skill 禁改 |
| confirmed `binding_lexicon.yaml` | SMT 真值；禁会话手改 |
| `contracts` / consumer schema / realization_map | 投影 CSV 列 |

冲突优先：approved plan 义务集 > solve 内部候选；lexicon merge 真值 > 未 merge resolve。  
**禁止生成**：改写 approved plan、临时 lexicon 补丁当主路径。

## Outputs

正式：求解 CSV、`solve_report` / uncovered obligations（含稳定 reason_code）。

中间：Z3 模型、投影调试产物（若脚本写出）。

**禁止产物**：修改 `plan/**` 批准快照；Edit lexicon 绕过域对称；伪 `resolved` 无高置信证据。

## Invariants

- **MUST NOT** 修改 approved plan（含 obligations / review 已批准内容）
- 启动前：approval + domain_review + **domain_symmetry**（字面量 ∈ CSV 域）
- 语义失败 → Task Follow uo-query → 只写 `$OUT_ROOT` → `tg-init --merge-uo-resolve` → **replan 一次**；禁手改 YAML / 禁改 `$UO_ROOT`
- 覆盖闭合由脚本校验；禁止手算覆盖率
- 语言：简体中文（`prompts/common/language.md`）

## Tool Policy

### MUST

```powershell
tg-solve "<算子仓>" --op-name <op> --level L0
```

- 域对称失败 → `ask=domain_asymmetry` → 回 init merge；禁止会话 Edit
- 命令块：`prompts/solve/workflow.md`；原因码：`references/uncover-codes.md`

### MAY

- 一次语义返工：uo-query Tasks（cap=8）→ merge → `tg-plan` 同 level 再批准 → 再 solve

### MUST NOT

- 改 approved plan / lexicon / `$UO_ROOT/**` / 测试脚本
- 父循环 `uo_kb_query` 当主路径
- 用伪 skip / 假 not_csv 消定义务
- 把 `tg-contract` / `tg-domain-review` 当用户必经命令

## Workflow

| Phase | Entry | Actions | Exit | Fail |
|---|---|---|---|---|
| 1 Gate | 用户触发 | 校验 approval + domain_symmetry | 门禁 pass | `APPROVE_*` / `domain_asymmetry` |
| 2 Encode | gate pass | 脚本编码义务→SMT | 约束集 | `ENCODE_FAIL` |
| 3 Solve | encode ok | Z3 / 后端求解 | 模型或 unsat | `UNSAT` / `SOLVER_FAIL` |
| 4 Project | 有模型 | 投影 `VAR_CSV_*`→CSV 行 | CSV + report | `PROJECT_FAIL` |
| 5 Cover | CSV 齐 | 脚本核对义务终态 | cover/uncover 报告 | 未举证 → uncover+code |

细节：`references/domain-symmetry.md`。

## Semantic Escalation

| 适合脚本 | 适合 LLM / uo-query |
|---|---|
| Z3、投影、覆盖核对、域对称 | 求解前语义缺口（须回 init merge，不在 solve 内猜） |

证据不足义务 → uncover + 稳定 reason_code，禁止伪 high 闭合。

## Failure Taxonomy

`APPROVE_BLOCKED` · `DOMAIN_REVIEW_REQUIRED` · `domain_asymmetry` · `ENCODE_FAIL` ·
`UNSAT` · `SOLVER_FAIL` · `PROJECT_FAIL` · `UNCOVERED` · `INVALID_LEVEL`

## Quality Gate

- [ ] 未修改 approved plan / lexicon
- [ ] 每条义务有终态：covered | uncovered+reason_code
- [ ] CSV 符合 consumer schema；无空 binding 行冒充成功
- [ ] 域对称门禁曾 pass

## Stop Conditions

- 无批准 / Allow solve:no → 停并回 `/tg-plan`
- `domain_asymmetry` → 停并回 `/tg-init --merge-uo-resolve`
- 语义返工超过一次仍失败 → 停并报告，禁止无限手改
