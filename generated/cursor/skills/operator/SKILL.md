---
name: operator
description: AscendC 统一入口别名。/operator 或自然语言意图 → 仅调用 harness route，不自建路由表。
disable-model-invocation: false
argument-hint: <自然语言或 /uo-init|/tg-plan|…>
---

# Skill: operator

## Harness control plane（唯一权威）

本 Skill **不**拥有阶段/门禁/完成态。每一轮只做：

1. `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run）或读 `harness status`
2. `harness next --project $PROJECT_ROOT` → 取 `phase_label_zh`、`allowed_actions`、`open_items`
3. 按返回的 **一个** `action_id` 执行对应领域方法（见 references / prompts）
4. 需要时 `harness advance <next_phase>` / `harness rework --reason <code>`
5. 终态仅 `harness complete`；禁止自行宣布 done / `passed`

Gate 失败 → 保持 phase，status=`rework_required` 或 `human_required`；勿当作立即 blocked。


## Purpose

把用户意图交给 **唯一路由器** `harness route`，再按返回的 `workflow_id` 启动对应 Skill / `harness start`。

本 Skill **不是**第二套路由器；禁止在此维护 slash/关键词副本。

## Procedure

1. 取用户原文（去掉前导 `/operator` 后的剩余文本；若为空则 AskQuestion 澄清）。
2. 执行：

```bash
harness route "<用户原文>"
```

3. 若 `ok=false`：展示 `candidates` / `error`，请用户澄清；**STOP**。
4. 若 `ok=true`：
   - `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run 或不匹配）
   - `harness next --project $PROJECT_ROOT`
   - 按 `workflow_id` 加载同名领域 Skill（`uo-init` / `tg-plan` / …）执行 **一个** action
5. 禁止直接 `python …/build_layered_kb.py` 或 `tg-solve` 绕过 Harness。

## MUST NOT

- 在本文件或 Prompt 中复制维护 `SLASH_MAP` / 关键词规则
- 自行宣布 workflow 完成
- 把 `/operator` 当作可跳过 Harness 的快捷执行器