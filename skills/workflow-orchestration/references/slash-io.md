# Slash 输入 / 输出

对照磁盘产物：缺输入就先跑上游节点。专家打了某个 slash 则只跑该节点。

## `/uo-init`

- 入：算子源码 + architecture，且还没有 `.uo`
- 出：`.uo` CodeMap
- 语义：建图，不经 query
- 调用：`pilot_run(workflow=uo-init)`

## `/uo-update`

- 入：已有 `.uo` + **diff**（PR / git / `/ce-apply` 产出）
- 出：更新后的 `.uo`
- 无 diff 不准走
- 调用：`pilot_run(workflow=uo-update)`

## `/uo-query`

- 入：`.uo` + 问题（可带 diff / 符号 / 位置）
- 出：对话答案，不写正式产物
- 调用：`pilot_cli` `uo-query` 或 Task(agent=uo-query)。禁止 `pilot_run`

## `/uo-investigate`

- 入：`.uo` 的 unresolved
- 出：调查结论，不改 `.uo`
- 调用：`pilot_run(workflow=uo-investigate)`

## `/ce-plan`

- 入：`.uo`；语义一律 `/uo-query`
- 出：`ce/plan/{slug}_plan.md`（可接到 `/ce-apply` 和 `/tg-plan`）
- 调用：`pilot_run(workflow=ce-plan)`

## `/ce-apply`

- 入：`ce/plan.md` + `.uo`；语义 `/uo-query`
- 出：算子源码 **diff**（回到变更入口，下一步 `/uo-update`）
- 调用：`pilot_run(workflow=ce-apply)`

## `/ce-review`

- 入：变更（PR / git / apply-diff）+ `.uo`；语义 `/uo-query`
- 出：审查结论（对话不落盘，可接到 `/tg-plan`）
- 调用：`pilot_run(workflow=ce-review)`

## `/tg-init`

- 入：**`.uo`（产物边）**；测试脚本仓 **可选**；语义 `/uo-query`
- 出：`tg/init.yaml`
- 进入前必须问用户有没有测试脚本仓：
  - **有：** 扫描脚本仓（含 xls/xlsx），列映射绑到 CodeMap；有仓但 mapping 空则失败
  - **无：** 用 `/uo-query` 读算子输入 API，按 API 设计 `init.yaml` 控制面
- 调用：`pilot_run(workflow=tg-init)`

## `/tg-plan`

- 入：`tg/init.yaml` + `.uo` + 可选 `ce/plan.md` / 审查结论；语义 `/uo-query`
- 出：`tg/plan.md`
- 调用：`pilot_run(workflow=tg-plan)`

## `/tg-solve`

- 入：`tg/plan.md` + `init.yaml` + `.uo`；语义 `/uo-query`
- 出：cases 表 + `tg/worklog.md`
- 调用：`pilot_run(workflow=tg-solve)`

## `/handoff`

- 入：当前会话正式产物
- 出：`session_handoff.md`
- 调用：`pilot_run(workflow=handoff)`
