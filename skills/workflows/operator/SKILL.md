---
name: operator
description: >-
  可选助手：列出可用 Pilot workflow skill，或把 /uo-init 等 slash 转给 acp route。
  自然语言意图请直接加载对应 workflow skill，不要依赖本 Skill 做口语路由。
---

# operator

本 Skill **不**做自然语言意图匹配。Agent 应按各 workflow skill 的 `description` 自行决定加载哪个 Skill。

## 主链路（TilingKey 闭环）

```text
/uo-init   范围确认 → 静态扫描 → tg_host_view
/tg-init   变量绑定 / IO / TilingKey 基础信息
/tg-plan   默认全量 TilingKey 义务（也可按描述/PR）
/tg-solve  动态运行 + 引理 + 闭环证书
```

`/tk-cover` 已删除；请用 `/tg-solve`。

## 可选用法

1. 用户给出 **slash**（如 `/uo-init`）时：调用 `acp route "/uo-init"`，再 `acp start`；
2. 用户意图不清时：列出候选 workflow skill（见 `acp route` 的 `skill_candidates`），请用户确认后加载对应 Skill；
3. **禁止**维护第二套关键词/路由表。
