---
name: operator
description: >-
  可选助手：列出可用 Pilot workflow skill，或把 /uo-init 等 slash 转给 acp route。
  自然语言意图请直接加载对应 workflow skill，不要依赖本 Skill 做口语路由。
---

# operator

选择正确工作流；领域方法见 `skills/domain/operator/SKILL.md`。

## 主链路

```text
/uo-init → /tg-init → /tg-plan → /tg-solve
```

审查：`/ce-review`。查询：`/uo-query`。更新：`/uo-update`。

## Pilot

1. 用户给出 slash 时：`acp route "<slash>"`，再 `acp start`
2. 意图不清时：列出 `skill_candidates`，确认后加载对应 workflow Skill
3. 禁止维护第二套关键词路由表
