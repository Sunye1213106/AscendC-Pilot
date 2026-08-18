# 产品流水线

编排权威是这张图，不是脚本 DAG。`.uo` 到 TG 有两条边：产物边进入 `/tg-init`；语义边经 `/uo-query`。

```text
无.uo源码 ──► /uo-init ──┐
                        ▼
变更输入 ──► /uo-update ► [ .uo ] ──┬──► /uo-query ──► /uo-investigate
PR / git / apply-diff       ▲      │          │
        ▲                   │      │          │ 语义扇出
        │                   │      │   ┌──────┼──────┬─────────┐
        │                   │      │   ▼      ▼      ▼         ▼
        │                   │      │ ce-plan ce-apply ce-review
        │                   │      │   │      │      │
        │                   │      │   ▼      ▼      ▼
        │                   │      │ plan.md  diff  审查结论
        │                   │      │   │      │      │
        └──────回环─────────┴──────┘   │      │      │
                         /uo-update    │      │      │
                                       │      │      │
        .uo 产物边 ──► /tg-init ───────┘      │      │
                         │  init.yaml         │      │
                         ▼                    │      │
                      /tg-plan ◄──────────────┴──────┘
                         │
                         ▼
                      plan.md → /tg-solve → cases → /handoff
```

交叉只三条：query 扇出；`ce-plan` / `ce-review` 汇入 `/tg-plan`；apply-diff 回变更入口再 `/uo-update`。
