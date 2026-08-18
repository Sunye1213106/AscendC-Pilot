# 主控形成 Goal Contract

读 `references/slash-io.md` 与 `references/product-pipelines.md`。这里负责**一次性**把自然语言目标变成结构化交付，不负责每个 workflow 完成后重新选路。

## 显式 slash

用户打了 `/uo-init` … `/handoff`：只 `pilot_run(workflow=该 id)`。不要改写成别的 slash，也不要创建跨 workflow TaskPlan。

## 自然语言

1. 识别用户真正要的最终交付，用 workflow id 表达，不按固定短语匹配。例如：只审查 → `ce-review`；要可执行 case → `tg-solve`；要改代码 → `ce-apply`。前置依赖交给 runtime 展开。
2. 识别 source：PR URL → `source.kind=pull_request` + URL；否则使用明确的 local/git_diff/commit_range。PR 只是事实源，不等于用户一定要 review 或 case。
3. 把同一轮已知约束写入 `constraints`，尤其 `test_script_root`、level/focus 等；已经给过的输入不得再问。
4. 形成一次性的 JSON：

```json
{
  "schema": "pilot-goal-contract/v1",
  "user_text": "用户原文",
  "objective_zh": "最终交付",
  "source": {"kind": "pull_request", "url": "..."},
  "needed_workflows": ["tg-solve"],
  "constraints": {"test_script_root": "..."}
}
```

5. 调 `pilot_run(workflow=goal-intake, intent=<上述 JSON>)`。`goal-intake` 是确定性 promoter，不调用第二个 Intent LLM；它负责校验、PR exact-head workspace、依赖展开和 TaskPlan 落盘。
6. 后续严格跟随 runtime `next_workflow_id`。不得重新读取用户原文决定下一跳。

## 依赖语义

- PR + TG：UO → `ce-review` → `tg-init` → `tg-plan` → `tg-solve`。`ce-review` 输出 planning context（改动范围、影响范围、风险、测试意图/目标），`tg-plan` 的核心输入是该上下文 + `tg/init.yaml`。
- PR + review-only：UO → `ce-review`，不添加 TG。
- 本地 TG：不强制 CE review；可使用用户意图、CE plan、已有 review planning context 或 handoff。
- 语义查询一律 `/uo-query`（`pilot_cli` 或 Task），不进入 TaskPlan。

## 禁止

- 黄金句/关键词 → 固定流水线的生产路由
- 每个 workflow 完成后重新解释 NL
- 第二轮 Intent LLM
- Grep 算子仓代替 uo-query
- 发明 workflow、算子或 architecture
