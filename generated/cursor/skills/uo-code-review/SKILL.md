---
name: uo-code-review
description: 已有 KB 上双路审查：Bug（CBM 主、KB 补）与 Functional（KB 主、CBM 补）。 写出 review/**；不改
  diff/**；不装 code-review-graph。
disable-model-invocation: true
argument-hint: '[path] [--op-name <name>] [--mode both|functional|bug] [--requirements
  <path>] [--base <rev>]'
---

# Skill: uo-code-review

## Harness control plane（唯一权威）

本 Skill **不**拥有阶段/门禁/完成态。每一轮只做：

1. `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run）或读 `harness status`
2. `harness next --project $PROJECT_ROOT` → 取 `phase_label_zh`、`allowed_actions`、`open_items`
3. 按返回的 **一个** `action_id` 执行对应领域方法（见 references / prompts）
4. 需要时 `harness advance <next_phase>` / `harness rework --reason <code>`
5. 终态仅 `harness complete`；禁止自行宣布 done / `passed`

Gate 失败 → 保持 phase，status=`rework_required` 或 `human_required`；勿当作立即 blocked。


## Purpose

定稿 KB → **双路审查报告**（`review/**`）：缺陷证据链 + 功能/语义完整性。

## Trigger

- 适用：`/uo-code-review`、缺陷 / 需求完整性审查
- 不适用：建库（`/uo-init`）、KB 问答（`/uo-query`）、只生成 `diff/`（`/uo-update`）

人读 Step 明细：`docs/uo-code-review-workflow.md`。  
阶段合同：`prompts/review/workflow.md`。

## Inputs

| 权威 | 说明 |
|---|---|
| `$UO_ROOT/manifest.yaml` | 须存在 |
| fresh `indexes/kb_graph.sqlite` | Functional 主图 |
| `cbm/index_meta.json`（`indexed_via: mcp`） | Bug 主图 |
| 可选 `--requirements` / `--base` | 需求矩阵 / 对比修订 |
| 建议已有 `diff/` | 变更聚焦 |

辅助：`prompts/review/bug_review.md`、`functional_review.md`、`clauses/ascendc_redlines.md`、
`agents/uo-code-reviewer.md`。

## Outputs

**正式：** `review/bug_report.{yaml,md}`、`review/functional_report.{yaml,md}`、
`review/index.yaml`、`review/summary.md`（随 `--mode`）。  
**禁止：** 覆盖 `diff/**`；安装/依赖 code-review-graph；静默单图降级。

## Invariants

| 路 | 主图 | 补图 |
|---|---|---|
| Bug | CBM | `kb_graph` |
| Functional | `kb_graph` | CBM |

- Bug 结论不得只靠 KB；功能/语义结论不得只靠 CBM 调用图
- 证据须可定位到 `file:line`（优先 CBM MCP）
- 读门禁：overview / 热文件 Grep → 小窗 Read → CBM；禁整读 operator_graph / exhaustive 全文

## Tool Policy

### MUST use

- `prepare_review_context.py`；`ready=false` 则停
- Bug 路：`bug_review.md` + CBM MCP；Functional 路：`functional_review.md` + kb_graph

### MAY use

- 有界派发 `uo-code-reviewer` subagent
- `--mode bug|functional` 单路

### MUST NOT

- 装 CRG；覆盖 `diff/**`；`ready=false` 时硬跑；无证据下发 finding

## Workflow

变量：`SCRIPT_DIR=$PLUGIN_ROOT/engines/uo/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.ascendc-agent/uo`。

### Phase 1: 就绪校验

- **Entry：** 用户触发 `/uo-code-review`
- **Actions：** 检查 manifest、fresh sqlite、CBM meta；建议 diff/`--base`
- **Exit：** 双图就绪（或 mode 所需图就绪）
- **Failure：** `ready=false` → **STOP**（提示 export_kb_graph / Phase0 索引）

### Phase 2: 打包上下文

- **Actions：**

```powershell
python -X utf8 "$SCRIPT_DIR/prepare_review_context.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --mode both
```

- **Artifacts：** context pack（含 cbm.impact 等）
- **Exit：** pack 可读

### Phase 3: Bug 路（mode=both|bug）

- **Actions：** 按 `bug_review.md`：CBM impact / `trace_path` / `search_graph` 为主；kb_graph 旁证；条例 `clauses/`
- **Artifacts：** `review/bug_report.yaml` + `.md`
- **Exit：** 每条 finding 有证据或显式 skip reason

### Phase 4: Functional 路（mode=both|functional）

- **Actions：** 按 `functional_review.md`：有 requirements 做需求矩阵；否则做语义完整性
- **Artifacts：** `review/functional_report.yaml` + `.md`
- **Exit：** 覆盖项均有终端状态

### Phase 5: 汇总

- **Actions：** 写 `review/index.yaml` + `summary.md`
- **Exit：** index 指向两路报告

## Semantic Escalation

- 需理解 Host/Kernel/KEY 语义 → 经 kb_graph / CBM 证据，必要时有界 subagent
- MUST NOT：凭记忆或纯命名直觉下缺陷结论

## Failure Taxonomy

`NO_EXISTING_KB` · `GRAPH_NOT_READY` · `TOOL_FAILURE` · `INSUFFICIENT_EVIDENCE` · `VALIDATION_FAILURE`

## Quality Gate

- [ ] `prepare_review_context` ready
- [ ] 按 mode 写出对应 report
- [ ] Bug/Functional 主补图未对调
- [ ] 未改 `diff/**`；未装 CRG
- [ ] index + summary 存在

## Stop Conditions

- 缺 KB / 缺所需图 → **STOP**
- context `ready=false` → **STOP**
- 证据不足的候选 finding → 记 `INSUFFICIENT_EVIDENCE`，禁止编造 file:line