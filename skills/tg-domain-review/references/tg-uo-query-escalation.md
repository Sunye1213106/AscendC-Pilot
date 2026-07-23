# TG 算子语义 → Task Follow `/uo-query` → merge

**权威副本：** `tg-init/references/tg-uo-query-escalation.md`（本文件仅为别名指针，勿在此写第二套规则）。

摘要（与权威副本一致）：

- Lexicon = 可执行真值；必须 `--merge-uo-resolve` + `--verify-csv-closure`
- `confidence=high` only；chain→CSV；禁伪 `not_csv` / `already_bound_in_kb`
- **只写 `$OUT_ROOT`**；禁止 Edit `$UO_ROOT/**`
- **父代理**可跑 merge/verify/confirm CLI；**禁止**循环 `uo_kb_query` 当主路径（图查询在 uo-query Task 内）
- mid/kernel 套娃自动 WHILE；禁止问用户「是否继续」
- unsolved：可读 UO gaps 作证据，uo-query 闭合到 CSV（不回写 UO 图）
