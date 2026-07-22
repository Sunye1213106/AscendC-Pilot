# `/tg-plan` 工作流

`/tg-plan` 用于在 `init.status=confirmed` 之后，生成并审批覆盖计划（`Allow solve:yes`）。

实现方式可概括为：

> 由人工说明或默认「全部输入可达」确定范围，LLM 落到稳定 KEY/VAR/branch id，脚本生成 L0/L1（可选 L2）义务集，经 reachability 过滤后由人工批准。

整体原则是：

* 无输入 = 全部输入可达；有输入 = 只覆盖 focus / topic 命中实体；
* 始终剔除核内不可控 id 与 `not_input_derivable`；
* 批准后 plan 为 solve 只读真源；
* 缺口较大应回 `/tg-init`，不得手改 lexicon。

---

## 使用条件

| 使用 `/tg-plan` | 不使用 `/tg-plan` |
| --- | --- |
| init 已 confirm 后生成 / 审批覆盖义务 | 未 confirm → 回 `/tg-init` |
| | 已批准后求 CSV → `/tg-solve` |

编排入口为 `skills/tg-plan/SKILL.md`，命令块为 `prompts/plan/workflow.md`。

### 核心约定：人输入 → LLM 定范围 → 再出计划

| 输入 | 行为 |
| --- | --- |
| **有人工说明**（变量 / KEY / 功能点 / 自然语言） | LLM 解析为要覆盖的变量 / KEY / branch，再调用 `tg-plan --focus …`（必要时加 `--topic`） |
| **无输入 /「全部」** | 默认覆盖全部输入可达义务（L0+L1；可选 L2） |

「输入可达」= 能从算子接口面经 KB `input_derivable` 派生到的 KEY / 变量 / 分支。

### 级别

| Level | 含义 | 默认 |
| --- | --- | --- |
| L0 | 功能冒烟（在选定范围内） | 是 |
| L1 | 受影响 / 范围内的 kernel branch | 是 |
| L2 | 全部可达 TilingKey | 可选 |

`--level` 默认 `L0,L1`；`all` = `L0,L1,L2`；无 L3。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill | `skills/tg-plan/SKILL.md` |
| 命令块 | `prompts/plan/workflow.md` |
| Level | `skills/tg-plan/references/levels.md` |
| 审批门禁 | `skills/tg-plan/references/approval-gate.md` |
| 上游 init | [tg-init-workflow.md](./tg-init-workflow.md) |

### 输入真源

| 真源 | 路径 |
| --- | --- |
| TG 测项合同 | `$OUT_ROOT/contract/testcase.yaml` |
| confirmed realization | `$OUT_ROOT/realization/**` |
| 覆盖语义 + `input_derivable` | `$UO_ROOT` 定稿 KB |

---

# Phase 0：范围

## Step 1：解析人工范围

**关键文件**

* Skill：`skills/tg-plan/SKILL.md`
* 级别：`skills/tg-plan/references/levels.md`

**执行内容**

1. 读取用户本轮说明；空 = 全部输入可达；
2. LLM 对照 KB / lexicon，落到稳定 id（`KEY_*` / `VAR_*` / `KBR_*` 等）；
3. 有范围时写入 `--focus`；主题类再用 `--topic`；
4. 不得将 `loopId` / `blockId` 等核内局部写入 focus 强行覆盖。

**输入 / 输出**

输入为人工说明或空；输出为 focus / topic 参数。

---

# Phase 1：Gate 与 Build

## Step 2：确认 init 已通过

**执行内容**

`require_init_confirmed`。Fail → `init_required`。

---

## Step 3：生成覆盖计划

**关键文件**

* 命令块：`prompts/plan/workflow.md`
* 级别：`skills/tg-plan/references/levels.md`

**执行命令**

```powershell
# 默认：全部输入可达，L0+L1
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME

# 指定变量与 KEY
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME --focus "KEY_IsRope KEY_MaskType"

# 可选 L2 / topic
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME --level L0,L1,L2
tg-plan "$PROJECT_ROOT" --op-name $OP_NAME --topic <scope>
```

**执行内容**

生成 `plan/levels/<level>/` 与 `plan/review.md`。  
Build 后自动执行 `input_reachable_filter`，过滤 `not_input_derivable` KEY 与 LOOP_LOCAL 分支。

**输入 / 输出**

输入为 confirmed realization + 范围参数；输出为 plan levels 与 review。

---

# Phase 2：过滤与审批

## Step 4：过滤可达义务

**执行内容**

按 CSV reachability / topic / focus 过滤。空关键套件 → `Allow solve: no`。

---

## Step 5：人工 Review / Approve

**关键文件**

* 审批门禁：`skills/tg-plan/references/approval-gate.md`

**执行内容**

人读 review；仅 `Allow solve:yes` 可通过 AskQuestion approve，写入 `plan/human_supplement.yaml`。  
缺口较大 → 回 `/tg-init`，不得手改 lexicon。

---

# 正式产物

* `plan/levels/<L0|L1|L2>/`
* `plan/review.md`
* `plan/human_supplement.yaml`（批准后）

---

# 禁止事项

* 改 `binding_lexicon` 或写入 `$UO_ROOT/**`；
* 写 CSV；
* 伪造 `Allow solve:yes`；
* 将 UO `contracts/` 作为测项真源；
* 将核内不可控 id 当作必须覆盖的测点；
* 使用已移除的 L3。

---

# 质量标准

一次合格 plan 应能说明：

1. 覆盖范围来自人工 focus 还是全部输入可达；
2. 各 level 产物是否齐全；
3. approve 时是否 `Allow solve:yes`；
4. 覆盖面是否不含核内不可控 / `not_input_derivable`。

失败码：`init_required` · `PLAN_BUILD_FAIL` · `APPROVE_BLOCKED` · `DOMAIN_REVIEW_REQUIRED` · `BINDING_REVIEW_REQUIRED` · `KEY_DERIVATION_MISSING` · `INVALID_LEVEL`
