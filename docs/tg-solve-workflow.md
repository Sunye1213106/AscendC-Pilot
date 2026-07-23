# `/tg-solve` 工作流

`/tg-solve` 用于在**已批准** coverage plan 上做 Z3/SMT 求解，生成 CSV 行与 uncover 原因码。

实现方式可概括为：

> 以批准计划与 confirmed lexicon 为只读真源，先做域对称门禁，再将覆盖义务编码为 SMT 约束，求解后投影为 CSV，并由脚本核对每条义务终态。

整体原则是：

* 不得修改 approved plan 与 lexicon；
* 覆盖闭合由脚本校验，不得手算覆盖率；
* 语义缺口最多返工一次（uo-query → merge → 再批准 → 再 solve）；
* 证据不足义务记为 uncovered + 稳定 reason_code。

---

## 使用条件

| 使用 `/tg-solve` | 不使用 `/tg-solve` |
| --- | --- |
| 某 level 已 approve 且 `Allow solve:yes` | 未批准 → 回 `/tg-plan` |
| | 未 confirm / 域不对称 → 回 `/tg-init` |
| | 建库或改 KB → UO 侧 |

编排入口为 `skills/tg-solve/SKILL.md`，命令块为 `prompts/solve/workflow.md`。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill 入口 | `skills/tg-solve/SKILL.md` |
| 命令块 | `prompts/solve/workflow.md` |
| 域对称 | `skills/tg-solve/references/domain-symmetry.md` |
| uncover 原因码 | `skills/tg-solve/references/uncover-codes.md` |
| 路径 | `skills/PATHS.md` |
| 上游 | [tg-plan-workflow.md](./tg-plan-workflow.md) · [tg-init-workflow.md](./tg-init-workflow.md) |

### 输入真源（只读）

| 真源 | 说明 |
| --- | --- |
| `plan/human_supplement.yaml` + level 批准快照 | 不可修改 |
| confirmed `binding_lexicon.yaml` | SMT 真源；会话中不可手改 |
| consumer schema / `realization_map` | 投影 CSV 列（`VAR_CSV_*` → 行） |

---

# Phase 1：门禁

## Step 1：校验 approval 与域对称

**关键文件**

* 域对称：`skills/tg-solve/references/domain-symmetry.md`
* 命令块：`prompts/solve/workflow.md`

**执行命令**

```powershell
tg-solve "$PROJECT_ROOT" --op-name $OP_NAME --level L0
```

**执行内容**

启动前校验：approval + domain_review + **domain_symmetry**（字面量 ∈ CSV 域）。

| Fail | 动作 |
| --- | --- |
| `APPROVE_*` | 回 `/tg-plan` |
| `domain_asymmetry` | 回 `/tg-init` merge；会话中不得 Edit lexicon |

---

# Phase 2：编码与求解

## Step 2：编码义务为 SMT

**执行内容**

脚本把批准义务编码为 SMT 约束。Fail → `ENCODE_FAIL`。

---

## Step 3：求解

**执行内容**

Z3 / 后端求解，得到模型或 unsat。  
Fail：`UNSAT` · `SOLVER_FAIL`。

---

# Phase 3：投影与覆盖核对

## Step 4：投影 CSV

**执行内容**

将 `VAR_CSV_*` 投影为 CSV 行，写出 CSV 与 `solve_report`。  
Fail → `PROJECT_FAIL`。

---

## Step 5：核对覆盖终态

**关键文件**

* 原因码：`skills/tg-solve/references/uncover-codes.md`

**执行内容**

脚本核对每条义务：`covered` 或 `uncovered` + 稳定 `reason_code`。  
不得手算覆盖率；不得以无效 skip / 不当 not_csv 消定义务。

---

# 语义返工（MAY，至多一次）

语义失败时：

1. Task Follow `/uo-query`（cap=8）；
2. `tg-init … --merge-uo-resolve`；
3. `tg-plan` 同 level **再批准**；
4. 再 `/tg-solve`。

不得在 solve 内手改 YAML / lexicon / approved plan 以解除阻塞。

---

# 正式产物

* 求解 CSV；
* `solve_report` / uncovered（含 `reason_code`）。

---

# 禁止事项

* 修改 `plan/**` 批准快照；
* Edit lexicon 绕过域对称；
* 改 UO KB / 测试脚本；
* 父代理循环 `uo_kb_query`；
* 将已废弃的 `tg-contract` / `tg-domain-review` 作为必经步骤；
* 用无效 skip 消定义务。

---

# 质量标准

一次合格求解应能说明：

1. 门禁（approval + domain_symmetry）是否通过；
2. 是否未改 approved plan / lexicon；
3. 每条义务是否有终态；
4. CSV 是否符合 consumer schema。

失败码：`APPROVE_BLOCKED` · `DOMAIN_REVIEW_REQUIRED` · `domain_asymmetry` · `ENCODE_FAIL` · `UNSAT` · `SOLVER_FAIL` · `PROJECT_FAIL` · `UNCOVERED` · `INVALID_LEVEL`
