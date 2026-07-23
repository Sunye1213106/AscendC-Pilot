# extract_plan — 结构抽取（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `extract_plan`。

## Purpose

把「从哪抽、抽哪些函数」钉死，再由脚本确定性产出 layered IR。  
LLM 只在脚本算不准时做有界消歧 / 角色裁剪，不全仓扫代码。

**入口事实源唯一**：`ir/entrypoint_graph.yaml`（类型化节点/边/extraction_units/closure）。  
已删除 `roles.*.selected` 单入口契约；禁止再写或读取 `selected`。

## Actions

### 1. 脚本构建入口图并评估闭包

- 脚本：`resolve_entrypoints.py --write`
- 逻辑：CBM + confirmed 源码扫描；架构中立路径保留；注册宏 `REG_OP` / `IMPL_OP_OPTILING` / `REGISTER_TILING_TEMPLATE*` 生成边
- 状态机：`located → verified → linked → closed | unresolved`
- Host 主链：`registration → public host → registry/dispatch → concrete impl(s)`
- Kernel 主链：`public kernel → dispatch → arch family/impl`
- 缺主链 → **blocking** unresolved（不是 warning）
- 产物：`ir/entrypoint_graph.yaml`（+ `entrypoint_candidates.yaml` 仅作中间列表）

### 2. 低置信 / 主链未闭合时 LLM 补边（任务 A）

- 条件：`closure.host_main_chain` 或 `kernel_main_chain` ≠ `closed`
- Prompt：`prompts/init/references/tpl_entrypoint.md`
- 补丁写入节点/边（`apply_entrypoint_confirmation`）；禁发明无证据符号
- 回流：`resolve_entrypoints.py --confirm-patch …` → 更新 `ir/entrypoint_graph.yaml`

### 3. 脚本扩抽取面候选

- 脚本：`propose_extract_plan.py --write`
- 依据：`entrypoint_graph.extraction_units`（非单 selected）
- Writer 身份：`file_path|qualified_name|class`（禁止 `name.casefold()` 合并）
- 产物：`ir/extract_plan_candidates.yaml`

### 4. LLM 打角色确认 plan（任务 C）

- Prompt：`prompts/init/references/tpl_extract_plan.md`
- 依据候选 evidence 标 `tiling_writer | key_writer | workspace_writer | provenance_helper | ignore`
- MUST NOT：扩面、发明名、跨 extraction unit 合并同名方法
- 回流：`apply_extract_plan.py --check` → `--write` → `ir/extract_plan.yaml`

### 5. 确定性 layered 抽取

- `build_layered_kb.py`：host/kernel/tilingkey/boundary/build/doc/bridge
- Operator boundary、def-use、typed TilingData / 位置级 TilingKey 由脚本闭合
- 官方文档：`cann_doc_evidence.py`（离线缓存优先）只证接口契约

## Hard Constraints

- MUST NOT：恢复 `selected`；短名 `SYM::DoOpTiling` 作为唯一身份；按局部变量名猜输入名
- MUST NOT：把 BuildConfig/CompileMacro/PlatformInfo 投影为 CSV 输入
- MUST：证据不足保留分级 unresolved（blocking/degraded/informational）

## Stop Conditions

- extract_plan 已写入；或 blocking 缺口已入账待人工/下一轮
