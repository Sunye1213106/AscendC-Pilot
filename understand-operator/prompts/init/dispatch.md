# 子代理派发合同（`/uo-init`）

## Task

父代理按阶段派发**唯一**允许的子代理，完成有界语义/审查任务。

## Allowed Agents

| Agent | 何时 |
|---|---|
| `uo-semantic-resolve` | 入口 / extract_plan / residual / input_derivable 断边 |
| `uo-kb-review` | integrity 通过后的最终抽查 |

**MUST NOT：** 建库期派 `uo-query` / `uo-code-reviewer`。

预检：`python -X utf8 "$SCRIPT_DIR/verify_required_subagents.py" --platform cursor`

## Identity / Resume

```text
<run_id>:<phase-or-step>:<owner>:<target-path-or-slice-id>
```

同身份已 open 或已返回 → **续跑同一上下文**，勿新开窗口。  
无法续跑 → 失败码 `SUBAGENT_RESUME_UNAVAILABLE`，向用户说明后停或重建身份。

显式传入：`PLUGIN_ROOT` · `PROMPT_DIR` · `SCRIPT_DIR` · `PROJECT_ROOT` · `OP_NAME` · `UO_ROOT`。

## Authoritative Prompt Bodies

模板正文 **verbatim**（只替换路径与 KEY 列表）：

| 任务 | Agent 任务字母 | 模板 |
|---|---|---|
| 入口确认 | A | `init/references/tpl_entrypoint.md` |
| Extract plan | C | `init/references/tpl_extract_plan.md` |
| 残留 resolve | B（+D） | `init/references/tpl_residual.md` |
| input_derivable 断边 | E | `init/references/tpl_input_derivable.md` |
| KB 产物审查 | — | `init/references/tpl_kb_review.md` |

Agent 细则：`agents/uo-semantic-resolve.md` + `agents/references/semantic-resolve-tasks.md`；
审查：`agents/uo-kb-review.md`。

## Writable Surfaces（semantic-resolve）

`ir/entrypoint_confirm.yaml` · `ir/extract_plan.yaml` · `ir/resolution_patch.yaml` ·
`ir/input_derivable_patch.yaml`

**MUST NOT** 改：`contracts/` · `tiling/` · `kernel/` · 源码树 · `diff/`。

kb-review **ONLY**：`review/kb_product_review.yaml`。

## Parent Procedure After Return

| 返回自 | 回流命令（MUST） |
|---|---|
| 任务 A（`tpl_entrypoint`） | `resolve_entrypoints.py ... --confirm-patch "$UO_ROOT/ir/entrypoint_confirm.yaml"`（或随后 `build_layered_kb ... --confirm-patch` 同路径） |
| 任务 C（`tpl_extract_plan`） | `apply_extract_plan.py --check` → 通过后再 `--write` |
| 任务 B（`tpl_residual`） | `apply_resolution.py --check` → apply |
| 任务 E（`tpl_input_derivable`） | `classify_input_derivable` → `check_final_confidence` → export → integrity |
| kb-review | fail → 按 `rework_stage` ≤2；pass → `export_human_views` |

通用顺序：

1. 对应上表跑 **check / confirm-patch**（禁止跳过）
2. rejected → **同身份**续跑修正 → 再 check → apply/confirm
3. gaps `open` / confidence≠high → 批跑任务 E（并行 cap **8**）
4. integrity pass → kb-review

## Hard Constraints

- MUST：一次 Task 一个模板；上下文闭包（路径 + 子集 id）
- MUST：任务 A/C 派发前候选已 `--write` 落盘（见 `workflow.md` Phase 1）
- MUST NOT：把整份 `operator_graph` 塞进子代理；要求子代理手点覆盖 unresolved
- MUST NOT：子代理失败后改派 uo-query「补救」建库
- MUST NOT：有 `entrypoint_confirm.yaml` 却不跑 `--confirm-patch` 就 build

## Acceptance

- 每个派发有身份字符串与返回产物路径
- check / confirm-patch 通过才进入下一步
- 无建库期 uo-query 调用

## Example identities

```text
run_042:extract:entrypoint:ir/entrypoint_confirm.yaml
run_042:extract:plan:ir/extract_plan.yaml
run_042:resolve:residual:batch0
run_042:resolve:input_derivable:KEY_ISNZOUT,KEY_ISPSE
run_042:review:kb:review/kb_product_review.yaml
```

## Parallelism

- 任务 E：按 KEY 批并行，**cap 8**
- 任务 A/C：与 E 串行（先入口/plan，再断边）
- 任务 B：单身份抽样，勿与 E 抢写同一 `resolution_patch` 而无合并约定
- kb-review：仅 integrity 后串行一次

## Stop / escalate

| 情况 | 动作 |
|---|---|
| `SUBAGENT_RESUME_UNAVAILABLE` | 告知用户；重建身份或人工接管 |
| apply/confirm 连续 2 次 rejected | 停该步，展示原因，勿改派 uo-query |
| 缺 candidates 文件 | 补 `--write` 后重派，勿空跑 LLM |
| confidence_gate=fail 且报告未写满 | 继续 E 或补 `confidence_report.md`，禁止进 review |
