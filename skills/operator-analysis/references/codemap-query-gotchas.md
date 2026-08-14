# UO CodeMap Query — Gotchas

高信号易错点。流程见 `uo-product-map.md` 与 `capabilities/uo-query/METHOD.md`，不要在此复述预算表。

- **CodeMap 优先于源码通读**：已有 `.uo` 时先结构化查询；不要一上来 grep 整棵算子树。
- **缺 `.uo` 不考古**：工作目录是确定的（`.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`）。找不到就 AskQuestion（`/uo-init` 或源码作答），禁止 Glob/dir 找产物。
- **Host branch ≠ Kernel branch**：不得因命名相似直接等同。
- **字段定位看 writer，不看最后赋值**：保存→修改→恢复的临时赋值不是最终来源。
- **宏与 compile-time**：运行时值不能回填成宏条件的唯一真值。
- **unresolved 不可凭命名闭合**。
- **只读**：不得改 `.uo`、不得宣布 workflow PASS；Explorer 不写文件。
- **查完就答**：不要为空转路由停住；不静默扩大到 full reachability。
- **用图，不用仓内 Glob**：`impact` / `locate` 先于 Grep。
- **`source_span` 足够引用**：不为拿行号而 Read；无 span 标 `PARTIAL` / `UNKNOWN`。
- **锁当前 architecture**：禁止用其他 arch 的命中闭合本 arch claim。
- **先 verdict 后证据**：禁止把结论埋在长推理末尾。
