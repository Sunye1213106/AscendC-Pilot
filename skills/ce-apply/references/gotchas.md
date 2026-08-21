# Code Engineering — Gotchas

- **两条场景不要混用**：`/ce-plan` 不以 PR / diff 为输入；`/ce-review` 审已有 diff。贴 GitCode/GitHub PR URL 会走 `/ce-review`，但必须在对应算子仓打开、已有 `.uo`，HTTPS 回退需要 `GITCODE_TOKEN` / `GITHUB_TOKEN`。无 diff 时 `/ce-review` 停。
- **正式产物只有 markdown**：`ce/plan/{slug}_plan.md` 与 `session_handoff.md`。禁止写任何 CE yaml（含 `tg_plan_intent.yaml`、`change_capture.yaml`、`ce/review/`）。
- **语义走 `uo-query`**：形态见 code-access 不变量。
- **apply 只做未完成 todo**：没有 `- [ ]` 就先 `/ce-plan`。不内嵌双轴审查，不另造测试意图文件。
- **验证不在 CE**：建议测试走 `/tg-plan`。TG 自己从计划「测试内容」节、审查对话或 `session_handoff.md` 总结。
- **handoff 只引用路径**：不要把 `{slug}_plan.md` 全文抄进总结。
- **LLM 禁止写 `.uo`**：apply 刷图由引擎嵌套 `uo-update`。
