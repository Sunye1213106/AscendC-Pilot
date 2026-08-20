---
name: code-engineering
description: >
  用命名 markdown 计划做 AscendC 改码。把需求 grill 成 {slug}_plan.md、按未完成
  todo 改码（含测试脚本缺口）、或写会话交接时使用。边界：不是只读审查（那是 /ce-review）；
  不是 TilingKey 搜索。验证走 /tg-plan，不是 CE。
---

# 代码工程

本 skill 用于 `/ce-plan`、`/ce-apply`、`/handoff`。
只读审查走 `/ce-review`（code-review skill）。测试义务由 `/tg-plan` 汇总。

## 入口对照

| 入口 | 做什么 |
| --- | --- |
| `/ce-plan` | 用户要改什么 / 实现什么：用 UO 语义 grill，写出带明确 todo 的 `{slug}_plan.md`。不以 PR 为输入 |
| `/ce-apply` | 按未完成 todo 改 `op_host/` / `op_kernel/` / `common/` / `test_script/`。也可按 tg-plan 的 `test_harness_gap` 说明书生成或修改测试脚本（含随机数） |
| `/handoff` | 换窗口 / 交给同事：只引用路径，写 `session_handoff.md` |

## 硬规则

1. CE 正式产物只有 markdown：`{slug}_plan.md` 与 `session_handoff.md`。禁止写任何 CE yaml。
2. 语义查询走 `pilot_cli uo-query`。
3. `/ce-plan` 不以 PR 为输入。`/ce-review` 无 diff 则停。
4. `/ce-apply` 不审、不查图、不另造测试意图文件。查图是 `/ce-plan` 与 `/ce-review`。验证去 `/tg-plan`，TG 自己读计划 md 或审查对话。
5. LLM 禁止写 `.uo`。apply 刷图由引擎嵌套 `uo-update`。

## 能力路由

- Grill：`capabilities/ce-intent-grill/METHOD.md`
- 写出计划：`capabilities/ce-plan-draft/METHOD.md`
- 中途改需求：`capabilities/ce-plan-revise/METHOD.md`
- 按 todo 改码：`capabilities/ce-apply/METHOD.md`
- 会话交接：`capabilities/session-handoff/METHOD.md`
- 形状参考：`examples/deter-band-schedule_plan.md`
