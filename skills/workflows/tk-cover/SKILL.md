---
name: tk-cover
description: 已弃用独立流水线；/tk-cover 重定向到 /tg-solve（TilingKey 全覆盖闭环）。用户说 tk-cover 时加载本
  Skill，然后执行 acp start tg-solve。
---

# tk-cover → tg-solve

`/tk-cover` 不再保留独立 workflow pipeline。请加载 `tg-solve` 并执行：

```text
acp start tg-solve
```

`export_codemap` 已迁入 `uo-init`（`export_tg_host_view`）；lemma / coverage 走
`tg-solve` 的 `lemma_*` 与 `closure_audit` / `closure_certify`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|

<!-- END GENERATED ACTIONS -->
