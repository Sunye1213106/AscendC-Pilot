# UO CodeMap Query — Gotchas

高信号易错点（不是查询流程复述）。

- **CodeMap 优先于源码通读**：已有 `.uo` 时先用 `CodeMapQuery` / 固定查询；不要一上来 grep 整棵算子树。
- **Host branch ≠ Kernel branch**：二者不得因命名相似直接等同；中间必须经 TilingKey / TemplateArg / 模板实例映射。
- **字段定位看 writer，不看最后赋值**：保存→修改→恢复的局部变量，临时赋值不是最终来源。
- **宏与 compile-time**：`#if` / 模板参数必须保留 compile-time provenance；运行时值不能回填成宏条件的“唯一真值”。
- **unresolved 不可凭命名闭合**：相似度、匈牙利命名、注释猜测都不能把 unresolved 标成 resolved。
- **只读边界**：uo-query 不得修改 `.uo`、不得写 gap patch、不得宣布 workflow PASS。
- **缺视图时先物化**：`tg_host_view` / legal-key 视图缺失时，提示 `uo_init.dump --materialize-tg`，不要发明维度。
- **回答缺 `path:line` 不合格**：只复述图节点 / 字段名、不给源码 `path:line`（或 `path:start-end`）→ 不合格。图命中带 span 时必须写入最终回答；无 span 标 `PARTIAL` / `UNKNOWN`，禁止编造行号。
