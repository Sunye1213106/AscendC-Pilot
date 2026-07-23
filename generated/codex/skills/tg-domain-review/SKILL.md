---
name: tg-domain-review
description: RETIRED user skill. Binding/domain orchestration is inside /tg-init.
  Do not install; use /tg-init.
argument-hint: use /tg-init instead
disable-model-invocation: true
---

# /tg-domain-review → 用 /tg-init

## Harness control plane（唯一权威）

本 Skill **不**拥有阶段/门禁/完成态。每一轮只做：

1. `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run）或读 `harness status`
2. `harness next --project $PROJECT_ROOT` → 取 `phase_label_zh`、`allowed_actions`、`open_items`
3. 按返回的 **一个** `action_id` 执行对应领域方法（见 references / prompts）
4. 需要时 `harness advance <next_phase>` / `harness rework --reason <code>`
5. 终态仅 `harness complete`；禁止自行宣布 done / `passed`

Gate 失败 → 保持 phase，status=`rework_required` 或 `human_required`；勿当作立即 blocked。


本 Skill **已退役**（不再安装）。绑定与域确认内嵌于 `/tg-init`。

权威：`skills/tg-init/SKILL.md` · `prompts/init/dispatch.md` ·
`skills/tg-init/references/tg-uo-query-escalation.md`