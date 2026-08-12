# UO CodeMap Query — Gotchas

高信号易错点（不是查询流程复述）。完整 METHOD 见 `capabilities/uo-query/METHOD.md`；产品地图见 `uo-product-map.md`。

- **CodeMap 优先于源码通读**：已有 `.uo` 时先用结构化 `acp uo-query`；不要一上来 grep 整棵算子树。
- **Host branch ≠ Kernel branch**：二者不得因命名相似直接等同；中间必须经 TilingKey / TemplateArg / 模板实例映射。
- **字段定位看 writer，不看最后赋值**：保存→修改→恢复的局部变量，临时赋值不是最终来源。
- **宏与 compile-time**：`#if` / 模板参数必须保留 compile-time provenance；运行时值不能回填成宏条件的“唯一真值”。
- **unresolved 不可凭命名闭合**：相似度、匈牙利命名、注释猜测都不能把 unresolved 标成 resolved。
- **只读边界**：uo-query 不得修改 `.uo`、不得写 gap patch、不得宣布 workflow PASS。
- **交付是 return_value**：最终消息输出 `kb-answer-v1`；Primary 用 `--result-file` finalize。禁止代写 `uo/checks/*`。
- **claim 够了必须停**：不静默扩大到 full reachability；optional（RoPE/DTemplate）可 PARTIAL，不得阻塞主答案。重复确认不是新证据。
- **硬预算**：uo-query≤6、ro-search≤2、Read≤2、总工具≤10（硬顶 12）；同 span 不读两次。
- **`source_span` 足够引用**：不为拿行号而 Read。
- **缺视图 / VIEW_STALE**：engine fallback canonical；不要发明维度。
- **回答缺 `path:line` 不合格**：无 span 标 `PARTIAL` / `UNKNOWN`，禁止编造行号。
- **先 verdict 后证据**：禁止把结论埋在长推理末尾。
