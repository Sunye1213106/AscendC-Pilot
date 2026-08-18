# Code Engineering — Gotchas

- **两条场景不要串台**：`/ce-plan` 不以 PR / diff 为输入；`/ce-review` 贴 PR 链接即 fetch 该 PR，不以设计改码为职责。无 diff 时 `/ce-review` 停。
- **正式产物只有 markdown**：`ce/plan/{slug}_plan.md` 与 `session_handoff.md`。禁止写任何 CE yaml（含 `tg_plan_intent.yaml`、`change_capture.yaml`、`ce/review/`）。
- **语义只走四种 `uo-query` 形态**：标识符 / `Dim=V` / `--file --line` / 无参数索引。禁止 `acp uo impact`、`explain-*`、`search`、`locate`。
- **apply 只做未完成 todo**：没有 `- [ ]` 就先 `/ce-plan`。不内嵌双轴审查，不另造测试意图文件。
- **验证不在 CE**：建议测试走 `/tg-plan`。TG 自己从计划「测试内容」节、审查对话或 `session_handoff.md` 总结。
- **handoff 只引用路径**：不要把 `{slug}_plan.md` 全文抄进总结。
- **LLM 禁止写 `.uo`**：apply 刷图由引擎嵌套 `uo-update`。
