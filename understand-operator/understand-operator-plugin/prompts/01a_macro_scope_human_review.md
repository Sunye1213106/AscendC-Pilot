# Macro Scope Human Review

这是 Phase 0.5 人工审核闸门。目标是在 Macro Boundary Agent 开始前，让用户确认 **Phase 1 的代码探索范围**，尤其是哪些代码分支、目录、文件、符号不做探索。

输入：

- `cbm/index_meta.json`
- `archive/runs/ignore_rules.md`
- 用户请求 / extra_description
- Phase 0 生成的 artifact skeleton（`index.yaml` / `operator.yaml` / `route.md`）

必须展示给用户：

1. `include_scope`
   - Phase 1 会探索的目录、文件模式、入口符号、op_host / op_kernel / op_api / proto / golden / tests 等候选范围。
2. `exclude_scope`
   - 明确不探索的目录、文件模式、无关分支、legacy 路径、测试或样例路径。
3. `branch_skip_rules`
   - 用户希望 Macro Boundary Agent 跳过的代码分支，例如特定平台、特定 dtype、未启用 feature flag、过时实现。
4. `uncertain_scope`
   - 需要用户确认是否探索的候选文件、候选符号或分支。
5. `next_phase_effect`
   - 这些选择会如何影响 Phase 1 的 `operator.yaml`（scope / analysis_plan）和后续 subagent source_hints。

## 人工确认问题展示要求

`uncertain_scope` 和需要用户确认的 include/exclude/skip 事项不能只写文件名或短标签。每项必须说明：

- `item`: 需要确认的目录、文件、符号、平台分支、dtype 分支或 feature flag。
- `current_observation`: 当前已知事实，例如该路径为什么像相关路径、为什么可能是 legacy/test/sample。
- `why_uncertain`: 为什么 Phase 0 无法自动决定是否纳入探索范围。
- `decision_needed`: 希望用户明确选择什么，例如 include、exclude、skip branch、仅保留为 low priority。
- `impact_if_included`: 纳入后会让 Phase 1 多探索哪些边界或 source_hints。
- `impact_if_excluded`: 排除后可能遗漏哪些 IO、tiling、kernel、golden 或 grad 路径。
- `suggested_default`: 保守建议和理由。
- `evidence_refs`: 相关 `cbm/index_meta.json`、ignore rule、文件模式或用户描述。

面向用户展示时，用 2-4 句话解释每个待确认项，不要只列路径。

## 交互选择（必须，Plan 风格可选 UI）

展示完摘要后，按 `prompts/00_review_menu.md`：

1. 用 OpenCode **`question`** 工具或 Cursor **AskQuestion** 弹出选择 UI（↑/↓ 或点击）。
2. 选项必须包含，且**最后一项支持输入**：
   - `continue` — 按当前范围进入 Phase 1
   - `revise` — 调整 include/exclude/skip 后重审
   - `stop` — 停止 workflow
   - `manual_supplement` — 手工补充（我来输入）
3. **STOP** 等待用户在选择 UI 中确认；若选手工补充，收集其输入文本为 notes。
4. 落盘：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision <choice> [--notes "..."]
```

**禁止**默认使用会抢键盘的 `--interactive` / `--arrows`。

读取 `UO_REVIEW_DECISION=...` 与 `archive/runs/macro_scope_decision.json`。

必须写入 `archive/runs/macro_scope_review.yaml`，并把结论摘要同步到 `human/review.md` Boundary Review：

```yaml
phase: "0.5"
status: pending_user_review
include_scope:
  files: []
  dirs: []
  symbols: []
  notes: []
exclude_scope:
  files: []
  dirs: []
  patterns: []
  notes: []
branch_skip_rules:
  - condition: ""
    reason: ""
    evidence: []
uncertain_scope:
  - item: ""
    question: ""
    current_observation: ""
    why_uncertain: ""
    impact_if_included: ""
    impact_if_excluded: ""
    suggested_default: ""
    evidence: []
decision:
  value: pending # continue | revise | stop | manual_supplement | pending
  decided_at: null
  notes: ""
```

Gate rules:

- 不得在用户通过交互菜单明确选择 `continue` 前启动 Phase 1。
- 如果用户选择 `revise`，更新 `archive/runs/macro_scope_review.yaml` 后重新展示本审阅并再次运行菜单。
- 如果用户选择 `manual_supplement`，把补充写入 review yaml / notes，然后重新运行菜单。
- 如果用户选择 `stop`，结束 workflow 并汇报当前 artifact。
