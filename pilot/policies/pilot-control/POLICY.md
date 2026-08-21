# Policy: pilot-control

## Purpose

Pilot 独占状态、合法边、门禁与完成态。Host 传输细节见 `pilot/policies/invariants/host-runtime-contract.md`。

## Rules

1. 只能执行 `pilot_run` / `dispatch-result` 返回的 Action。`pilot_cli next` 是诊断只读，不推进工作流。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 Host `complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。进入 `human_required` 后必须弹出可点选框，禁止仅用文字说明而不给出选项。Host 原生框未出现（`ask_ui_shown=false`）时主控必须用 `question` 补上同一组选项；pending / `host_owned_ask` 不得被理解成框已弹出。用户打断确认框并在对话里另作回复时，取消该 pending（`interpret-user-turn`），不要重问上一题；未点选不等于批准删除/重开。
5. 禁止直调领域 CLI；须经 `pilot_run` / `pilot_cli`。正式产物须 Pilot 签发收据。
6. 禁止跳步：必须执行 `recommended_next_action`。OpenCode 上确定性段由 Host `pilot_run` 驱动。
7. Lease：Action `allowed_write_paths` **必须**可读。
8. **`uo-query` 不是 Host Session Driver 工作流**（`host_driver=False`）：禁止 `pilot_run workflow=uo-query`。`host_driver=False` ≠ 没有 method bundle。简单查询主控直接调用 `pilot_cli` `uo-query`（stdout）；复杂查询委派 Task，主控综合。子代不得 Write `answer.yaml`。
9. 关键参数不明确 → 立刻 AskQuestion。`requires_architecture=true` 必须同时有 `--project` 与 `--architecture`。禁止静默默认 architecture，禁止在仓库根目录搜索以猜测 arch。
10. 产物根 = `--project` 算子目录。`.ascendc-pilot/` 只建在算子包下。
11. 查询/TG/CE 无 `.uo` 时路径是确定的；AskQuestion（查询：`/uo-init` 或源码作答；TG/CE 先 `/uo-init`），禁止 Glob 找产物。
12. 面向用户的表述：`needs_human_decision` / 阶段总结必须意图+动作+后果。禁止把 referee 内部术语贴给用户。
13. User Goal（全量 case）走 `control/user_goal.yaml` + `pilot_run` 的 `--intent`；不是查询路由启发式。
14. `complete` 必须释放本产物族锁；（UO 写工作流）发布 digest。不同族并行。
