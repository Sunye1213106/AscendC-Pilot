# `/tg-init` 工作流

`/tg-init` 用于在**定稿 KB** 与测试工具之上，生成 `.testcase-generator/<op>/` 的 **confirmed** realization：thin contract、KEY 语义绑定、域确认与 audit。

实现方式可概括为：

> 以测试工具 AST 抽取测项合同骨架，再通过并行 `/uo-query` 将 KEY 绑定到可映射接口叶子，经 merge、中间符号递归解析、csv-closure 与 audit 后确认 lexicon，形成 SMT 可执行真源。

整体原则是：

* UO KB 只读；TG 绑定与合同只写 `$OUT_ROOT`；
* 脚本负责 AST contract、merge、闭包校验与 confirm；
* 大模型 / uo-query 只处理 KEY 与中间符号语义缺口；
* 父代理自动 WHILE，中途不得询问用户是否继续下一轮。

---

## 使用条件

| 使用 `/tg-init` | 不使用 `/tg-init` |
| --- | --- |
| 合同摄入、KEY 绑定、域确认 | 已 confirmed 后只规划 → `/tg-plan` |
| | 已批准 plan 后求 CSV → `/tg-solve` |
| | 建库 / 修复 `input_derivable` → `/uo-init` |

编排入口为 `skills/tg-init/SKILL.md`，命令块为 `prompts/init/workflow.md`。

变量：`UO_ROOT=$PROJECT_ROOT/.understand-operator/$OP_NAME`；`OUT_ROOT=$PROJECT_ROOT/.testcase-generator/$OP_NAME`。

### UO ↔ TG 边界

| 侧 | 推导叶子 | 说明 |
| --- | --- | --- |
| UO | `HOST_ATTR_*` / `HOST_START_*` 等接口面 | 不写 CSV 列名 |
| TG | `VAR_CSV_*` | merge 后写入 `binding_lexicon.yaml`（SMT 真源） |

UO staging：`$UO_ROOT/ir/key_shape_resolve/<KEY>.yaml`  
TG 交付：`$OUT_ROOT/realization/uo_query_resolve/<KEY>.yaml`（再映射 CSV，**不写回** UO KB）

测项合同真源：`$OUT_ROOT/contract/testcase.yaml`。UO `contracts/**` 已废弃，不得作为真源。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill 入口 | `skills/tg-init/SKILL.md` |
| 路径 / 状态机 | `skills/PATHS.md` |
| 命令块 | `prompts/init/workflow.md` |
| 派发合同 | `prompts/init/dispatch.md` |
| uo-query 升级 | `skills/tg-init/references/tg-uo-query-escalation.md` |
| 中间符号递归解析 | `skills/tg-init/references/tg-mid-symbol-nesting.md` |
| 合法 skip | `skills/tg-init/references/legitimate-skips.md` |
| Contract 阶段 | `skills/tg-init/references/tg-contract-phase.md` |
| 终审 | `skills/tg-init/references/tg-init-audit.md` · `agents/tg-init-audit.md` |
| 可选补 bind | `agents/tg-csv-contract.md` |
| Schema | `agents/references/{csv-contract-schema,init-audit-schema}.md` |
| UO 查询 | `../understand-operator/skills/uo-query/SKILL.md` |

---

# Phase 0：校验定稿 KB

## Step 1：校验 KB 就绪

**关键文件**

* Skill：`skills/tg-init/SKILL.md`
* 路径：`skills/PATHS.md`

**执行内容**

`require_kb`：确认 `$UO_ROOT` 存在且 fresh。

**失败**

`uo_init_required` → 停止，提示 `/uo-init` 或 `/uo-update`。

---

# Phase 1：thin contract

## Step 2：扫描测试工具并生成合同骨架

**关键文件**

* 命令块：`prompts/init/workflow.md`
* 细节：`skills/tg-init/references/tg-contract-phase.md`
* 可选补 bind：`agents/tg-csv-contract.md`

**执行命令**

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --test-script-root "$TEST_ROOT"
```

**执行内容**

扫描测试工具 AST，生成 inventory / gaps / scaffold 与 `contract/testcase.yaml` 骨架。  
MAY：Task `tg-csv-contract`（仅在 inventory 证据内补 bind）。

**输入 / 输出**

输入为测试工具根与定稿 KB；输出为 `realization/consumer_*`、`realization_map`、gaps 与合同骨架。

---

# Phase 2：语义绑定（uo-query）

## Step 3：并行绑定 needs_binding_keys

**关键文件**

* 升级细则：`skills/tg-init/references/tg-uo-query-escalation.md`
* 合法 skip：`skills/tg-init/references/legitimate-skips.md`
* UO skill：`../understand-operator/skills/uo-query/SKILL.md`

**执行内容**

对 `needs_binding_keys` 并行 Task Follow `/uo-query`（cap=8）。  
**默认排除** `not_input_derivable` 与核内局部（`loopId` / `blockId` / `taskId` 等）。

依据定稿 KB 的 `ir/input_derivable.yaml`：

| 保留 | 剔除（默认） |
| --- | --- |
| 能从接口面派生到的 KEY / 变量 | `not_input_derivable: true` / `input_derivable: false` |
| 可由 CSV 控制的运行时分支 | 由核内不可控 id 控制的分支 |

resolved 仅 `confidence: high`；叶子落到可映射接口根后再写成 `VAR_CSV_*`。

**约束**

* 父代理不得以循环 `uo_kb_query` 作为主路径；
* 不得完整读取 `operator_graph.yaml`；
* 不得用 uo-query 修复核内局部不可达边。

**输入 / 输出**

输入为 gaps / needs_binding_keys；输出为 `$OUT_ROOT/realization/uo_query_resolve/<KEY>.yaml`。

---

# Phase 3：merge

## Step 4：合并 resolve 并检查域对称

**关键文件**

* 命令块：`prompts/init/workflow.md`
* 升级细则：`skills/tg-init/references/tg-uo-query-escalation.md`

**执行命令**

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --merge-uo-resolve
```

**执行内容**

合并 resolve 证据，写入 `binding_lexicon.yaml`，并做域对称检查。  
冲突优先：merge 后 lexicon > 未 merge 的 resolve 文件 > 启发式脚手架。

**失败**

`fake_not_csv_excuse` · `domain_asymmetry`。

**输入 / 输出**

输入为 `uo_query_resolve/**`；输出为 `binding_lexicon.yaml`、`uo_merge_report.yaml`。

---

# Phase 4：中间符号递归解析

## Step 5：消化 mid_symbol_queue

**关键文件**

* 细则：`skills/tg-init/references/tg-mid-symbol-nesting.md`

**执行条件**

`mid_symbol_queue` 非空，或 verify 失败。

**执行内容**

按中间符号递归解析继续 Task；可用 `--list-open-mids` 查看队列。Exit：queue 空。  
轮次用尽 → 向用户报告 `ask=`；过程中不得向用户提问。

---

# Phase 5：csv-closure + audit

## Step 6：闭包校验与终审

**关键文件**

* 终审：`skills/tg-init/references/tg-init-audit.md`
* 子代理：`agents/tg-init-audit.md`

**执行命令**

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --verify-csv-closure
# Task tg-init-audit → init/audit_report.yaml
```

**执行内容**

双 pass：`--verify-csv-closure` 与 `init/audit_report.yaml` status=pass。  
audit fail → **自动**回 Phase 2，不得伪造 pass。

---

# Phase 6：confirm

## Step 7：确认 init 完成

**执行命令**

```powershell
tg-init "$PROJECT_ROOT" --op-name $OP_NAME --confirm
```

**退出条件**

`init.status=confirmed`。

**失败**

`audit_required`（未过 Phase 5）。

---

# 正式产物

**正式：**

* `realization/{consumer_*,realization_map,binding_lexicon,domain_*,unresolved,uo_merge_report}.yaml`
* `contract/testcase.yaml`
* `init/audit_report.yaml`
* `init.status=confirmed`

**中间：**

* `uo_query_resolve/`
* `mid_symbol_queue.yaml`
* `bind/*`

---

# 禁止事项

* 回写 `$UO_ROOT/**`（含 `contracts/**`、`input_derivable*`、`key_shape_resolve`）；
* 手改 lexicon 以规避校验；
* 伪造 `confidence: high` 或 audit pass；
* 本阶段写 CSV / 跑 Z3；
* 将 `/tg-contract`、`/tg-domain-review` 作为必经步骤向用户暴露。

---

# 质量标准

一次合格 init 应能说明：

1. KB 已 fresh 且只读使用；
2. 绑定叶子均为可映射 `VAR_CSV_*`；
3. merge / csv-closure / audit 均 pass；
4. mid queue 为空；
5. `init.status=confirmed`。

失败码：`uo_init_required` · `CONTRACT_FAIL` · `UNRESOLVED_SEMANTICS` · `fake_not_csv_excuse` · `domain_asymmetry` · `CSV_CLOSURE_FAIL` · `audit_required` · `INVALID_PATH` · `TOOL_FAILURE`
