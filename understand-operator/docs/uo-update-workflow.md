# `/uo-update` 工作流

`/uo-update` 用于在已有 KB 上，相对上次 `manifest.source.revision` 做增量刷新：写出**同构新 KB**，并生成可供 PR 测试消费的 `diff/**`。

实现方式可概括为：

> 以 git 变更检测确定受影响层，按层复用 init 的抽取与有界语义补全，再通过置信度与完整性门禁，导出同构 KB 与专用 diff 包。

整体原则是：

* 新 KB 与 `/uo-init` 同构，下游优先读 `diff/`，不确定再回查 KB；
* 脚本负责检测、计划、重建、门禁与 diff 导出；
* 大模型只处理新增不确定项（任务 A/B/C/E）；
* `needs_phase0_review` 时必须人工确认，不得自动 continue。

---

## 使用条件

| 使用 `/uo-update` | 不使用 `/uo-update` |
| --- | --- |
| 代码变更后刷新 KB | 首次建库 → `/uo-init` |
| 需要可消费的 `diff/**` | 只要口头摘要 → `/uo-diff` |
| | 缺陷 / 需求审查 → `/uo-code-review` |

编排入口为 `skills/uo-update/SKILL.md`，阶段合同为 `prompts/update/workflow.md`。

变量：`SCRIPT_DIR=$PLUGIN_ROOT/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.understand-operator/$OP_NAME`。

前置：`$UO_ROOT/manifest.yaml` 存在且 `source.revision` ≠ `unknown`。缺失则 **STOP**，提示 `/uo-init`。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill | `skills/uo-update/SKILL.md` |
| 阶段合同 | `prompts/update/workflow.md` |
| 复用细则 | `skills/uo-init/references/{phase0,extract,resolve}.md` |
| 派发 / 模板 | `prompts/init/dispatch.md` · `prompts/init/references/tpl_*.md` |
| 变更检测 | `uo/scripts/detect_kb_changes.py` |
| 更新计划 | `uo/scripts/plan_kb_update.py` |
| 重建编排 | `uo/scripts/update_operator.py` |
| diff 导出 | `uo/scripts/export_diff_product.py` |

---

# Phase 1：校验与变更规划

## Step 1：校验已有 KB

**关键文件**

* Skill：`skills/uo-update/SKILL.md`
* Manifest：`$UO_ROOT/manifest.yaml`

**执行内容**

确认 manifest、revision 合法，且曾完成分层抽取。

**失败**

`NO_EXISTING_KB` / `UNKNOWN_REVISION` → 停止并提示 `/uo-init`。

---

## Step 2：检测变更

**关键文件**

* 脚本：`uo/scripts/detect_kb_changes.py`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/detect_kb_changes.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
# 可选：--base <rev> --head <rev>
```

**执行内容**

以 git base/head（可选）与 Phase0 confirmed 文件求交，生成变更集合。机制是 git diff，不是 AST。

**输入 / 输出**

输入为 revision 与 confirmed 文件；输出为 `diff/change_set.yaml`。

---

## Step 3：生成并展示 update_plan

**关键文件**

* 脚本：`uo/scripts/plan_kb_update.py`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/plan_kb_update.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**执行内容**

标注受影响层、是否 `needs_phase0_review`，并向用户展示 `mode` / `affected_layers`。不得静默吞入 scope 外文件。

**输入 / 输出**

输入为 change_set；输出为 `summary/update_plan.yaml`。

---

# Phase 2：条件复审与按层重建

## Step 4：必要时确认 Phase0

**关键文件**

* 门禁：`uo/scripts/review_checkpoint.py`
* Phase0 细则：`skills/uo-init/references/phase0.md`
* 重建入口：`uo/scripts/update_operator.py`

**执行条件**

`needs_phase0_review=true`。

**执行内容**

AskQuestion：`continue | revise | stop`。不得自动 continue。  
扩 scope 流程同 init Phase0（confirm → stage → MCP → meta）。  
重建时使用 `update_operator.py ... --confirm-phase0`。用户 `stop` → **STOP**。

**输入 / 输出**

输入为 update_plan 与用户决策；输出为确认后的 scope / 索引状态，或本步跳过。

---

## Step 5：按层重建 KB

**关键文件**

* 主脚本：`uo/scripts/update_operator.py`
* 可选分步：`uo/scripts/build_layered_kb.py --layers …`
* Extract 细则：`skills/uo-init/references/extract.md`

**执行内容**

重抽受影响层，写出同构新 KB。抽取机制与 init Extract 相同（正则 + 花括号函数体；依赖 entrypoints + extract_plan）。  
若入口 / plan 变更，复用 init Extract Step 1–4（脚本候选 → 低置信 LLM 任务 A/C）。

**输入 / 输出**

输入为 update_plan 与源码；输出为同构新 KB。

---

## Step 6：有界语义补全（按需）

**关键文件**

* 子代理：`uo-semantic-resolve`
* 模板：`prompts/init/references/tpl_*.md`
* Resolve 细则：`skills/uo-init/references/resolve.md`

**执行内容**

仅对**新增**不确定项派发：

| 场景 | 任务 | Prompt | 回流 |
| --- | --- | --- | --- |
| 新 entrypoint | A | `tpl_entrypoint.md` | `resolve_entrypoints --confirm-patch` |
| 新 unresolved | B（≤12） | `tpl_residual.md` | `apply_resolution` |
| extract_plan 变更 | C | `tpl_extract_plan.md` | `apply_extract_plan` |
| 新 gaps | E | `tpl_input_derivable.md` | classify / confidence |

未定稿边不得改派 `/uo-query`（除非 integrity 已通过）。

---

# Phase 3：门禁与 diff 产物

## Step 7：门禁检查并写出 diff/

**关键文件**

* `uo/scripts/classify_input_derivable.py`
* `uo/scripts/check_final_confidence.py`
* `uo/scripts/check_kb_integrity.py`
* `uo/scripts/export_diff_product.py`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/classify_input_derivable.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_final_confidence.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/check_kb_integrity.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/export_diff_product.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

**执行内容**

完成置信度与完整性门禁后，导出 `diff/{index,change_set,impact,unresolved}.yaml`，并写入 `runs/<id>/update/receipt.yaml`。

下游优先阅读顺序：`diff/index.yaml` → `impact.yaml` → `unresolved.yaml`；不确定再回查 KB。

**退出条件**

* integrity pass；
* `diff/index.yaml` 可读；
* sqlite / overview 已刷新。

---

# 正式产物

* 与 init 同构的新 KB；
* `diff/{index,change_set,impact,unresolved}.yaml`；
* 中间：`summary/update_plan.yaml`、`runs/<id>/update/receipt.yaml`。

---

# 禁止事项

* 无合法 manifest / revision 时继续；
* 跳过 Phase0 门禁或自动 continue；
* 静默吞入 scope 外文件；
* 改写已批准 TG plan；
* 写测试 CSV；
* 未定稿时用 `/uo-query` 代替任务 E；
* 用本流程做代码审查。

---

# 质量标准

一次合格更新应能说明：

1. 变更范围与受影响层；
2. 是否触发并完成 Phase0 确认；
3. 新 KB 是否同构且 integrity pass；
4. `diff/` 是否可供下游稳定消费；
5. 开放 gap 是否已报告。

失败码见 `skills/uo-update/SKILL.md`。
