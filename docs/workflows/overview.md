# 工作流总览

| Slash | Skill | 引擎入口 |
|-------|-------|----------|
| `/uo-init` | uo-init | `uo_init.pilot_engines` |
| `/uo-update` | uo-update | `uo_init.update` |
| `/uo-query` | uo-query | `uo_init.uo_query` |
| `/tg-init` / `/tg-plan` / `/tg-solve` | tg-* | `testcase_agent` + UO KB |
| `/ce-review` | ce-review | CE + UO KB |

产物根：`<算子>/.ascendc-pilot/{uo,tg,ce,...}/`。

详见：

- [uo-init.md](./uo-init.md)
- [uo-update.md](./uo-update.md)
- [uo-query.md](./uo-query.md)
- [tg.md](./tg.md)
- [ce-review.md](./ce-review.md)
