# 子代理派发合同（`/uo-init`）

## Task

父代理按阶段派发**唯一**允许的子代理，完成有界语义/审查/KEY 任务。

## Allowed Agents

| Agent | 何时 |
|---|---|
| `uo-semantic-resolve` | 入口 / extract_plan / residual 简单 FP（任务 A/B/C） |
| `uo-key-resolve` | KEY triage + 按复杂度 resolve（运动员：写原因） |
| `uo-confidence-review` | 非 high KEY 原因独立审查（裁判） |
| `uo-kb-review` | integrity 通过后的最终抽查 |

**MUST NOT：** 建库期派 `uo-query` 做 KEY 闭合；Phase0 派 `explore` / `generalPurpose` 预扫；父代理手写 `confidence_reason_review.yaml` 顶替裁判。

预检：`python -X utf8 "$SCRIPT_DIR/verify_required_subagents.py" --platform cursor`

## Identity / Resume

```text
<run_id>:<phase-or-step>:<owner>:<target-path-or-slice-id>
```

同身份已 open 或已返回 → **续跑同一上下文**，勿新开窗口。  
无法续跑 → 失败码 `SUBAGENT_RESUME_UNAVAILABLE`，向用户说明后停或重建身份。

显式传入：`PLUGIN_ROOT` · `PROMPT_DIR` · `SCRIPT_DIR` · `PROJECT_ROOT` · `OP_NAME` · `UO_ROOT`。

## Authoritative Prompt Bodies

模板正文 **verbatim**（只替换路径与 KEY 列表；**禁止英文自由发挥**）：

| 任务 | Agent | 模板 |
|---|---|---|
| 入口确认 | A · semantic-resolve | `init/references/tpl_entrypoint.md` |
| Extract plan | C · semantic-resolve | `init/references/tpl_extract_plan.md` |
| 残留 resolve | B · semantic-resolve | `init/references/tpl_residual.md` |
| KEY 粗分 | triage · key-resolve | `init/references/tpl_key_triage.md` |
| KEY 闭合 | single/batch · key-resolve | `init/references/tpl_key_resolve.md` |
| 置信度原因审查 | — · confidence-review | `init/references/tpl_confidence_reason_review.md` |
| KB 产物审查 | — · kb-review | `init/references/tpl_kb_review.md` |

Agent 细则：`agents/uo-semantic-resolve.md` · `agents/uo-key-resolve.md` · `agents/uo-confidence-review.md` · `agents/uo-kb-review.md`。

## Writable Surfaces

### semantic-resolve

`ir/entrypoint_confirm.yaml` · `ir/extract_plan.yaml` · `ir/resolution_patch.yaml`

### key-resolve

`ir/key_triage.yaml` · `ir/input_derivable_patch.yaml` · `ir/key_shape_resolve/**`

**MUST NOT** 改：`contracts/` · `tiling/` · `kernel/` · 源码树 · `diff/`。

kb-review **ONLY**：`review/kb_product_review.yaml`。  
confidence-review **ONLY**：`review/confidence_reason_review.yaml`。

## Parent Procedure After Return

| 返回自 | 回流命令（MUST） |
|---|---|
| 任务 A（`tpl_entrypoint`） | `resolve_entrypoints.py ... --confirm-patch` |
| 任务 C（`tpl_extract_plan`） | `apply_extract_plan.py --check` → `--write` |
| 任务 B（`tpl_residual`） | `apply_resolution.py --check` → apply；若有 `escalate_keys` → **先 triage** |
| KEY triage | 读 `ir/key_triage.yaml` → 分流派发 resolve（见下） |
| KEY resolve | `classify_input_derivable` → `check_final_confidence` →（need_llm）**`uo-confidence-review`** → `harness validate-key-gates` → `harness advance export` → integrity |
| confidence-review | fail → 补原因 / 再 key-resolve；pass → 继续 export |
| kb-review | fail → 按 `rework_stage` ≤2；pass → `export_human_views` → **`harness complete`** |

### 强制派发（ses_076d）

- **任务 C 永远派发**（candidates `--write` 落盘后）；父代理 **MUST NOT** 手写 `extract_plan.yaml`
- **任务 A**：`llm_required` 非空必派；另：某角色 `candidate_count ≥ 3`（建议 kernel）或存在 EmptyTensor/旁路候选名 → **强制 needs_llm**，即使脚本已选 1.0
- `escalate_keys` / gaps open → **必须** triage + key-resolve；**禁止**父代理直接 accepted 顶替

### KEY 分流（强制）

1. `escalate_keys` / gaps open / confidence≠high → 派 **一次** `tpl_key_triage`（身份 `<run_id>:resolve:key-triage`）
2. 按 triage：
   - **complex** → 并行 `mode=single`，身份 `<run_id>:resolve:key:<KEY_ID>`（一 KEY 一 Task）
   - **simple** → 按 `batch_hint` 组批，每批 ≤6，`mode=batch`，身份 `<run_id>:resolve:key-batch:<batch_id>`
3. **禁止**默认「每个 KEY 一个 subagent」；**禁止**把 complex 打进 batch
4. 并行 resolve 总 cap 建议 **8**（含 single + batch Tasks）

## Hard Constraints

- MUST：一次 Task 一个模板；上下文闭包（路径 + 子集 id）
- MUST：任务 A/C 派发前候选已 `--write` 落盘；任务 C 不可跳过
- MUST：派发 prompt **verbatim 用中文模板**；产物 reason/rationale 中文
- MUST NOT：把整份 `operator_graph` 塞进子代理
- MUST NOT：建库期用 `/uo-query` 做 KEY 闭合
- MUST NOT：有 `entrypoint_confirm.yaml` 却不跑 `--confirm-patch` 就 build
- MUST NOT：Phase0 explore 预扫
- MUST NOT：跳过 key-triage / 用 empty-only producer 假闭合

## Acceptance

- 每个派发有身份字符串与返回产物路径（写入 `.ascendc-agent/runs/<run_id>/subagents/`）
- check / confirm-patch / classify / **harness key gates** / **`harness complete`** 通过才算完成
- KEY 路径经 triage 分流；非 high 必有原因 + **confidence-review 裁判**；无「一律一 KEY 一 agent」

## Example identities

```text
run_042:extract:entrypoint:ir/entrypoint_confirm.yaml
run_042:extract:plan:ir/extract_plan.yaml
run_042:resolve:residual:batch0
run_042:resolve:key-triage
run_042:resolve:key:KEY_ISNZOUT
run_042:resolve:key-batch:empty_tensor_regbase
run_042:review:kb:review/kb_product_review.yaml
```

## Parallelism

- KEY resolve：triage 后并行，cap **8**
- 任务 A/C：与 KEY 串行（先入口/plan，再 KEY）
- 任务 B：单身份抽样，勿与 KEY 抢写同一 patch 而无合并约定
- kb-review：仅 integrity 后串行一次

## Stop / escalate

| 情况 | 动作 |
|---|---|
| `SUBAGENT_RESUME_UNAVAILABLE` | 告知用户；重建身份或人工接管 |
| apply/confirm 连续 2 次 rejected | 停该步，展示原因 |
| 缺 candidates 文件 | 补 `--write` 后重派，勿空跑 LLM |
| confidence_gate=fail 且报告未写满 | 继续 KEY resolve 或补 `confidence_report.md`，禁止进 review |
| triage 误判 | 父代理将 simple 升级 single，或拆 batch；勿在 triage 里闭合 |
