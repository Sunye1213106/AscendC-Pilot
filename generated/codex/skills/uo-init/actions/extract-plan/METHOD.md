# extract_plan — 结构抽取（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `extract_plan`。

## Purpose

把「从哪抽、抽哪些函数」钉死，再由脚本确定性产出 layered IR。  
LLM 只在脚本算不准时做有界消歧 / 角色裁剪，不全仓扫代码。

## Actions

### 1. 脚本找入口候选并算置信度

- 脚本：`resolve_entrypoints.py --write`
- 逻辑：按角色名模式（`DoOpTiling` / `GetTilingKey` / `{Op}Kernel`…）CBM 搜符号；回退 confirmed 文件整词正则；kernel 扫 `__global__`
- 置信度：路径/精确名/目录启发式；`<0.85` → `needs_llm`；无法唯一确认 → `llm_required_roles`
- 高置信：脚本自动 `selected`
- 产物：`ir/entrypoint_candidates.yaml`

### 2. 低置信时 LLM 选入口（任务 A）

- 条件：`llm_required_roles` 非空
- Prompt：`prompts/init/references/tpl_entrypoint.md`
- 只从候选选一个或标 missing；禁发明符号
- 回流：`resolve_entrypoints.py --confirm-patch …/entrypoint_confirm.yaml` → `ir/entrypoints.yaml`

### 3. 脚本扩抽取面候选

- 脚本：`propose_extract_plan.py --write`
- 依据：已确认 `host_tiling_entry`
- 扩面：花括号函数体 → callee → CBM trace → 扫 `set_*`/`tilingData=` → 一跳 + sink 闭包
- 产物：`ir/extract_plan_candidates.yaml`

### 4. LLM 打角色确认 plan（任务 C）

- Prompt：`prompts/init/references/tpl_extract_plan.md`
- 依据候选 evidence 标 `tiling_writer | key_writer | workspace_writer | provenance_helper | ignore`
- MUST NOT：扩面、发明名
- 回流：`apply_extract_plan.py --check` → `--write` → `ir/extract_plan.yaml`

### 5. 脚本分层抽取

- 脚本：`build_layered_kb.py`
- 依赖：`entrypoints.yaml` + `extract_plan.yaml`
- 机制：按 plan 过滤后，对函数体正则抽写入/分支；CBM 辅助定位
- 产物：layered IR + gaps / unresolved

## Hard Constraints

- MUST：先 `--write` 再派任务 A/C；有 confirm 必须 `--confirm-patch`
- MUST NOT：让 LLM 全仓搜入口；跳过 plan 直接 `build_layered_kb`

## Failure Handling

- 入口缺失 / plan 无法 apply → `UNRESOLVED_SEMANTICS`
- 脚本失败 → `TOOL_FAILURE`
