# `/uo-init` 工作流

`/uo-init` 用于首次为尚未建库的算子构建完整 `$UO_ROOT`。

实现方式可概括为：

> 基于静态代码分析、有限 AST/语法结构抽取、代码图索引和大模型语义解析，提取算子的输入、属性、Host 变量、TilingKey、TilingData、Kernel 变量及分支关系，构建具备源码证据和变量依赖关系的算子知识图谱。

整体原则是：

* 脚本负责确定性扫描、抽取、回溯、校验和导出；
* 大模型只处理低置信候选、残留语义和 KEY / input_derivable 缺口；
* 人工负责确认源码分析范围；
* 不确定内容必须进入 unresolved、gap 或 confidence report，禁止伪造 high。

---

## 使用条件

| 使用 `/uo-init`                 | 不使用 `/uo-init`                |
| ----------------------------- | ----------------------------- |
| 空仓或尚未建立算子 KB                  | 已有 fresh KB 的问答使用 `/uo-query` |
| 需要首次生成完整 `$UO_ROOT`           | 增量刷新使用 `/uo-update`           |
| 需要系统提取 Host、Tiling、Kernel 变量图 | 代码变更审查使用 `/uo-code-review`    |

编排入口为 `skills/uo-init/SKILL.md`，可执行工作流定义在 `prompts/init/workflow.md`。

变量：`SCRIPT_DIR=$PLUGIN_ROOT/engines/uo/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.ascendc-agent/uo`。

建库期间只允许派发：

* `uo-semantic-resolve`（入口 / plan / 残留 FP）
* `uo-key-resolve`（KEY triage + 按复杂度 resolve）
* `uo-kb-review`

不得派发 `/uo-query` 做 KEY 闭合，避免建库过程反向依赖尚未完成的 KB。  
Phase0 不得派 `explore` / `generalPurpose` 预扫目录。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill 入口 | `skills/uo-init/SKILL.md` |
| 路径解析 | `skills/uo-init/PATHS.md` |
| 阶段合同 | `prompts/init/workflow.md` |
| Todo | `prompts/init/progress.md` |
| 子代理派发 | `prompts/init/dispatch.md` |
| KEY 解析 | `agents/uo-key-resolve.md` · `prompts/init/references/tpl_key_{triage,resolve}.md` |
| Phase0 / Extract / Resolve | `skills/uo-init/references/{phase0,extract,resolve}.md` |
| KEY / input_derivable | `skills/uo-init/references/uo-input-derivable-resolve.md` |
| 公共规则 | `prompts/common/{runtime,path,tools,language,cbm}.md` |
| Spec | `spec/ownership.yaml` · `spec/kb_layout.yaml` |

---

# Phase 0：确认分析范围并建立索引

Phase 0 负责创建 KB 目录、扫描源码范围、人工确认范围，并对确认后的窄目录建立代码图索引。

## Step 1：创建 KB 目录

**关键文件**

* 脚本：`uo/scripts/prepare_operator.py`
* 路径规则：`skills/uo-init/PATHS.md`
* KB 布局：`spec/kb_layout.yaml`

**执行内容**

脚本根据项目根目录和算子名称创建 `$UO_ROOT`，初始化 `manifest.yaml`、标准目录骨架和本次运行的 `current_run_id`。

**输入 / 输出**

输入为 `$PROJECT_ROOT`、`$OP_NAME`；输出为 `$UO_ROOT`、manifest 骨架及当前运行目录。

---

## Step 2：扫描分析范围提案

**关键文件**

* 脚本：`uo/scripts/macro_scope_scan.py`
* 阶段说明：`skills/uo-init/references/phase0.md`
* 展示合同：`prompts/init/macro_scope.md` · `prompts/init/scope_menu.md`
* 架构配置：由命令参数传入，例如 `--architecture arch35`

**执行内容**

脚本根据算子名称、目录布局、文件名、Host/Kernel/Tiling 目录特征生成源码范围候选。当前机制主要是文件系统启发式，不是完整 AST 分析。

默认：**`tests` / `examples` / `ut` / `st` 不进候选**（可用 `--seed` / `manual_supplement` 显式加回）。

脚本在 `scope_proposal.yaml` 写入 `summary.included_layers`，并在 stdout 打印 **INCLUDE / EXCLUDE** 两张表：按路径前缀聚合，每层同时报 `.cpp` 与 `.h` 数量。禁止根据 `candidate_files.host` / `headers` 桶自行合成「op_host=N」。

**输入 / 输出**

输入为项目目录、算子名和目标架构；输出为 `runs/<id>/phase0/scope_proposal.yaml`（含 `summary`）及 stdout 计数表。

---

## Step 3：人工确认分析范围

**关键文件**

* 门禁脚本：`uo/scripts/review_checkpoint.py`
* 门禁定义：`prompts/init/workflow.md`
* 交互规则：`prompts/common/runtime.md`

**执行内容**

必须先**原样转述**脚本 INCLUDE / EXCLUDE 计数表（每层 `.cpp` + `.h`），再通过 AskQuestion 让用户选择：

* `continue`
* `revise`
* `manual_supplement`
* `stop`

禁止自动选择 `continue`。禁止 Phase0 派 `explore` / `generalPurpose` 预扫。用户选择 `stop` 后立即终止；选择修改或补充时重新生成确认范围。

**输入 / 输出**

输入为 `scope_proposal.yaml`（含 `summary`）、脚本 stdout 与用户决策；输出为 `scope_confirmed.yaml` 及门禁记录。

---

## Step 4：准备窄范围索引目录

**关键文件**

* 脚本：`uo/scripts/stage_cbm_scope.py`
* CBM 规则：`prompts/common/cbm.md`
* 路径规则：`prompts/common/path.md`

**执行内容**

脚本仅将人工确认的源码文件整理到 `$UO_ROOT/cbm/index_stage/`，避免对整个父仓建立索引，并记录原文件与 staged 文件之间的映射。

**输入 / 输出**

输入为 `scope_confirmed.yaml`；输出为窄范围索引目录和文件映射信息。

---

## Step 5：通过 MCP 建立代码图

**关键文件**

* MCP 调用规则：`prompts/common/tools.md`
* CBM 使用规则：`prompts/common/cbm.md`
* 阶段说明：`skills/uo-init/references/phase0.md`

**执行内容**

调用 `index_repository`：

```text
repo_path = $UO_ROOT/cbm/index_stage
mode      = fast
name      = <op>-phase0-scope
```

代码图用于后续符号搜索、调用关系分析、入口定位和跨文件追踪，但不替代源码证据。

**输入 / 输出**

输入为 staged 窄目录；输出为 MCP 代码图项目名称和索引状态。

---

## Step 6：回写索引元数据并结束 Phase 0

**关键文件**

* 元数据脚本：`uo/scripts/prepare_operator.py`
* 收尾脚本：`uo/scripts/finalize_phase0.py`
* manifest 规范：`spec/ownership.yaml`

**执行内容**

使用 `prepare_operator.py --write-index-meta --cbm-project <name>` 回写索引信息，禁止使用 `--force-new-run`，随后执行 `finalize_phase0.py` 检查范围确认和索引状态。

**退出条件**

必须同时满足：

* `scope_confirmed.yaml` 存在；
* `index_meta.indexed_via=mcp`；
* CBM 项目名称已写入 manifest；
* Phase 0 状态已完成。

---

# Phase 1：Extract

Phase 1 负责确认算子入口、生成抽取计划，并提取 Host、TilingKey、TilingData、Kernel 及其桥接关系。

## Step 1：寻找入口候选并计算置信度

**关键文件**

* 脚本：`uo/scripts/resolve_entrypoints.py`
* 提示词模板：`prompts/init/tpl_entrypoint.md`
* 抽取规则：`skills/uo-init/references/extract.md`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/resolve_entrypoints.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --write
```

**执行内容**

脚本优先通过 CBM 按角色名模式搜索：

* `DoOpTiling`
* `GetTilingKey`
* `{Op}Kernel`
* 算子注册入口
* `__global__` Kernel

搜索失败时，回退到 confirmed 文件中的整词正则和目录启发式。

候选置信度综合考虑：

* 精确符号名；
* 文件路径；
* 函数签名；
* 注册引用；
* 候选是否唯一。

高置信且唯一的候选自动 selected；低于阈值或无法唯一确认的角色进入 `llm_required_roles`。

**输入 / 输出**

输入为 confirmed 文件范围和 CBM 索引；输出为 `ir/entrypoint_candidates.yaml`。

---

## Step 2：大模型确认低置信入口

**关键文件**

* 提示词：`prompts/init/tpl_entrypoint.md`
* 子代理：`uo-semantic-resolve`
* 应用脚本：`uo/scripts/resolve_entrypoints.py`

**执行条件**

仅当 `llm_required_roles` 非空时派发任务 A。

**执行内容**

大模型只能从现有候选中选择一个，或将角色标记为 missing，禁止发明符号、扩大范围或修改高置信结果。

生成 `ir/entrypoint_confirm.yaml` 后，必须执行：

```powershell
python -X utf8 "$SCRIPT_DIR/resolve_entrypoints.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" `
  --confirm-patch "$UO_ROOT/ir/entrypoint_confirm.yaml"
```

**输入 / 输出**

输入为候选及其 evidence、score；输出为正式 `ir/entrypoints.yaml`。只生成 confirm 文件但不执行 `--confirm-patch`，确认结果不会生效。

---

## Step 3：生成抽取范围候选

**关键文件**

* 脚本：`uo/scripts/propose_extract_plan.py`
* 提示词模板：`prompts/init/tpl_extract_plan.md`
* 抽取说明：`skills/uo-init/references/extract.md`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/propose_extract_plan.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --write
```

**执行内容**

脚本以已确认的 `host_tiling_entry` 为起点：

1. 定位函数体；
2. 提取直接 callee；
3. 通过 CBM trace 扩展调用关系；
4. 搜索 `set_*`、TilingData、TilingKey 和 Workspace 写入；
5. 扩展一跳调用和关键 sink 闭包。

当前主要机制是正则、花括号定界和 CBM 辅助，不是完整 clang AST。

**输入 / 输出**

输入为 `entrypoints.yaml` 和 confirmed 源码；输出为 `ir/extract_plan_candidates.yaml`。

---

## Step 4：大模型确认抽取计划

**关键文件**

* 提示词：`prompts/init/tpl_extract_plan.md`
* 子代理：`uo-semantic-resolve`
* 校验脚本：`uo/scripts/apply_extract_plan.py`

**执行内容**

大模型根据候选 evidence 和 score，将函数分类为：

* `tiling_writer`
* `key_writer`
* `workspace_writer`
* `provenance_helper`
* `ignore`

禁止添加候选中不存在的函数、扩大源码范围或修改入口。

完成后执行：

```powershell
python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --check

python -X utf8 "$SCRIPT_DIR/apply_extract_plan.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --write
```

**输入 / 输出**

输入为 `extract_plan_candidates.yaml`；输出为正式 `ir/extract_plan.yaml`。

---

## Step 5：执行分层知识抽取

**关键文件**

* 主脚本：`uo/scripts/build_layered_kb.py`
* 抽取说明：`skills/uo-init/references/extract.md`
* KB 结构：`spec/kb_layout.yaml`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/build_layered_kb.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**内部模块**

* `extract_host_subgraph`
* `extract_kernel_subgraph`
* `extract_tilingkey_space`
* `extract_key_predicates`
* `extract_golden`
* `macro_regions`
* `reconcile_bridge`

**执行内容**

脚本按正式 extract plan 提取：

* 算子输入、属性、Shape 和 dtype；
* Host 中间变量及条件；
* TilingData、TilingKey、Workspace 写入；
* Kernel 模板参数、读取字段和分支；
* 编译宏和架构宏；
* Host 写入与 Kernel 读取之间的 bridge；
* 输入、属性到内部变量的初始推导链。

不能确定的内容必须进入 unresolved 或 gap。

**输入 / 输出**

输入为 `entrypoints.yaml`、`extract_plan.yaml` 和源码；输出为 layered IR、`ir/input_derivable*.yaml`、bridge、宏区域和 `ir/unresolved.yaml`。

**硬规则**

入口候选和抽取候选必须真实写入文件。缺少 `--write` 时，大模型任务没有候选可读，工作流必须停止。

---

# Phase 2：Resolve、门禁与导出

Phase 2 负责解析 unresolved、补全 KEY / input_derivable 语义、检查置信度，并导出正式知识图谱。

## Step 1：解析残留 unresolved

**关键文件**

* 提示词：`prompts/init/references/tpl_residual.md`
* 子代理：`uo-semantic-resolve`
* 应用脚本：`uo/scripts/apply_resolution.py`
* 阶段说明：`skills/uo-init/references/resolve.md`

**执行内容**

大模型处理简单变量别名、短赋值链、局部布尔表达式和明确字段来源。每次只处理有限数量的简单 false positive；复杂 TilingKey 或多层条件写入 `escalate_keys`，交后续 KEY triage。

禁止无证据闭合、建库期派 `/uo-query` 做 KEY 闭合，或将猜测标为 high。

补丁生成后必须先执行 `--check`，再正式 apply。

**输入 / 输出**

输入为 `ir/unresolved.yaml` 和关联源码证据；输出为 `ir/resolution_patch.yaml`、已解决项和 `escalate_keys`。

---

## Step 2：KEY triage 与按复杂度 resolve

**关键文件**

* 提示词：`prompts/init/references/tpl_key_triage.md` · `prompts/init/references/tpl_key_resolve.md`
* 子代理：`uo-key-resolve`
* 细则：`skills/uo-init/references/uo-input-derivable-resolve.md` · `skills/uo-init/references/resolve.md`

**触发条件**

满足任一条件时执行：

* 存在 open gap；
* 边置信度不是 high；
* 存在 `escalate_keys`。

**执行内容**

1. 派发 **一次** triage，写出 `ir/key_triage.yaml`（每 KEY：`complex|simple` + 中文理由；只分类不闭合）。
2. 按复杂度分流并行 resolve（Tasks cap≈8）：
   * **complex**（如 IsNzOut、分轴、sparse/NZ、强 shape）→ **一 KEY 一 Task**；
   * **simple**（如 empty_tensor、纯 regbase 开关）→ **多 KEY 打包**（每批 ≤6）。
3. 主路径：Host `file_path` 定向阅读；CBM 仅 MAY。写出 `ir/input_derivable_patch.yaml`，可选 `ir/key_shape_resolve/<KEY>.yaml`。

只有充分证据支持的关系才能标记为 high。不得将 Kernel 循环状态、运行时索引或编译宏标为外部输入可推导。禁止默认「每个 KEY 一个 subagent」。

**输入 / 输出**

输入为 layered IR、gaps、`escalate_keys` 和源码证据；输出为 `key_triage.yaml`、patch、闭合项、开放项及置信度。

---

## Step 3：重新计算 input derivable

**关键文件**

* 分类脚本：`uo/scripts/classify_input_derivable.py`
* 规则说明：`skills/uo-init/references/resolve.md`
* 数据定义：`ir/input_derivable.yaml`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/classify_input_derivable.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**执行内容**

脚本从分支条件或目标变量向上回溯，判断其是否最终来源于：

* 算子输入；
* 算子属性；
* Shape；
* dtype；
* TilingData；
* TilingKey；
* Kernel 运行状态；
* CompileMacro。

**输入 / 输出**

输入为更新后的 Host、Kernel 和 bridge 图；输出为更新后的 `ir/input_derivable.yaml`、推导路径、开放 gap 和不可推导原因。

---

## Step 4：检查最终置信度

**关键文件**

* 检查脚本：`uo/scripts/check_final_confidence.py`
* 输出：`checks/confidence_gate.yaml`
* 报告：`summary/confidence_report.md`
* 规则：`skills/uo-init/references/resolve.md`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/check_final_confidence.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**检查内容**

重点检查：

* 入口；
* 抽取角色；
* TilingData 字段来源；
* TilingKey 条件；
* Kernel 模板参数；
* Host-Kernel bridge；
* input derivable 结论；
* 开放 gap。

状态只能为：

* `pass`
* `reported`
* `fail`

`fail` 时返回 Step 2 继续补全；确实无法闭合时，必须完整写入 `confidence_report.md`，不得伪造 high 置信度。

---

## Step 5：导出正式知识图谱

**关键文件**

* 查询视图脚本：`uo/scripts/kb_query_export.py`
* 图导出脚本：`uo/scripts/export_kb_graph.py`
* 图数据库：`indexes/kb_graph.sqlite`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/kb_query_export.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --view testcase-contract
python -X utf8 "$SCRIPT_DIR/export_kb_graph.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**执行内容**

先导出 `testcase-contract` 查询视图，再生成正式图数据库。

图中至少包含：

* 输入和属性；
* Host 变量；
* TilingData 字段；
* TilingKey；
* `KTPL_*` 模板参数；
* Kernel 变量；
* 分支和条件表达式；
* 数据依赖边；
* 控制依赖边；
* Host-Kernel bridge；
* 证据、置信度和 `fixes_flag`。

不得只生成无语义关系的符号列表或通用 `operator_graph` dump。

**输入 / 输出**

输入为正式 IR 和 confidence gate；输出为查询视图及 `indexes/kb_graph.sqlite`。

---

## Step 6：执行 KB 完整性检查

**关键文件**

* 检查脚本：`uo/scripts/check_kb_integrity.py`
* 输出：`checks/integrity.yaml`
* 最终检查：`checks/final.yaml`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/check_kb_integrity.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME"
```

**检查内容**

至少检查：

* manifest、entrypoints、extract plan 和 layered IR 是否存在；
* unresolved 是否清空；
* 全部 `KTPL_*` 和 Key 是否已导出；
* Host-Kernel bridge 是否一致；
* 图数据库是否可读取；
* high 置信事实是否有证据；
* confidence gate 是否为 `pass` 或 `reported`；
* 所有开放 gap 是否已报告。

**Phase 2 退出条件**

* unresolved 清空；
* confidence gate 为 `pass` 或 `reported`；
* integrity 为 `pass`；
* `kb_graph.sqlite` 已生成。

---

# Phase 3：KB 产物审查

Phase 3 只审查已经生成的正式 KB，不再进行无限制源码探索。

## Step 1：执行 KB 审查

**关键文件**

* 子代理：`uo-kb-review`
* 提示词：`prompts/init/tpl_kb_review.md`
* 输出：`review/kb_product_review.yaml`

**执行内容**

审查以下内容：

* Host、TilingKey、TilingData、Kernel 是否正确对齐；
* 关键路径是否覆盖；
* 入口和函数角色是否合理；
* Key 和模板参数是否完整；
* input derivable 结论是否可信；
* 是否存在伪造的 high 置信度；
* 图数据库是否能被 `/uo-query` 和测试生成流程消费。

审查结论只能为：

* `pass`
* `fail`

---

## Step 2：审查失败时返工

**关键文件**

* 工作流定义：`prompts/init/workflow.md`
* 返工控制：`skills/uo-init/SKILL.md`
* 审查结果：`review/kb_product_review.yaml`

**可选返工阶段**

* `phase0_scope`
* `entrypoints`
* `extract_plan`
* `residual_resolve`
* `input_derivable`
* `confidence_gate`
* `export_graph`
* `none`

返工最多两轮，禁止在多个阶段之间无限循环。超过上限后必须停止，并输出剩余问题和风险。

---

## Step 3：导出人读视图

**关键文件**

* 脚本：`uo/scripts/export_human_views.py`
* 输出：`summary/human_overview.md`
* 可选报告：`summary/confidence_report.md`

**执行内容**

审查通过后，生成便于开发者阅读的：

* 算子输入、属性和输出概览；
* Host Tiling 主流程；
* TilingKey 生成逻辑；
* TilingData 字段说明；
* Kernel 模板和分支结构；
* Host-Kernel 对齐关系；
* input derivable 结果；
* 已知限制和开放问题。

**Phase 3 退出条件**

* `kb_product_review.yaml` verdict 为 `pass`；
* 人读视图生成成功；
* `checks/final.yaml` 完整；
* 不存在未记录的关键开放问题。

---

# 正式产物

`/uo-init` 的正式产物包括：

```text
manifest.yaml

ir/**
tiling/**
kernel/**

indexes/kb_graph.sqlite

checks/integrity.yaml
checks/confidence_gate.yaml
checks/final.yaml

review/kb_product_review.yaml

summary/human_overview.md
summary/confidence_report.md   # 可选
```

中间产物至少应覆盖：

* 入口候选与正式入口；
* 抽取计划候选与正式计划；
* Host 和 Kernel layered IR；
* TilingKey 与 Key 条件；
* Host-Kernel bridge；
* input derivable；
* unresolved、gaps 和 resolution patch；
* 代码证据及置信度信息。

---

# 禁止事项

建库过程中禁止：

* 未经人工确认范围自动继续；
* 对父仓建立全量 CBM 索引；
* 派发 `/uo-query`；
* 让大模型发明入口或函数；
* 让大模型扩大脚本候选范围；
* 无证据补全变量关系；
* 将低置信结论标为 high；
* 将 Kernel 运行状态映射为 CSV 输入；
* 将 CompileMacro 错误映射为测试字段；
* unresolved 未清空便导出正式 KB；
* 写入 `contracts/**`；
* dump 通用 `operator_graph`；
* 绕过 confidence 或 integrity 门禁；
* 审查失败后无限返工。

---

# 质量标准

最终 KB 不以文件数量为标准，而应能够回答：

1. 算子的 Host 和 Kernel 入口在哪里；
2. 输入、属性、Shape 和 dtype 如何生成 Host 中间变量；
3. Host 如何生成 TilingData 和 TilingKey；
4. TilingKey 如何选择 Kernel 模板或分支；
5. Kernel 条件依赖哪些字段和变量；
6. 哪些条件可由外部输入推导；
7. 哪些条件属于 Kernel 运行状态或编译宏；
8. 每个 high 置信结论的源码证据在哪里；
9. 哪些 gap 尚未闭合，以及为什么；
10. 图数据库能否被查询、测试生成和覆盖分析稳定消费。

---

# 执行前预检

**关键文件**

* 预检脚本：`uo/scripts/verify_required_subagents.py`
* Skill 入口：`skills/uo-init/SKILL.md`
* 工作流定义：`prompts/init/workflow.md`
* Todo：`prompts/init/progress.md`
* 子代理派发：`prompts/init/dispatch.md`

预检至少确认：

* 必需子代理存在；
* 脚本环境和 Python UTF-8 模式可用；
* 项目根目录和算子名称有效；
* MCP 索引能力可用；
* 没有误调用 `/uo-query`；
* 旧运行目录不会与当前运行冲突。

预检失败时，不得开始 Phase 0。
