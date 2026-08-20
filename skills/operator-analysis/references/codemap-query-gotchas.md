# UO CodeMap Query — Gotchas

高信号易错点。流程见 `uo-product-map.md` 与 `capabilities/uo-query/METHOD.md`。

- **CodeMap 优先于源码通读**：已有 `.uo` 时先调用插件 `pilot_cli` `uo-query`；不要一上来 grep 整棵算子树。
- **缺 `.uo` 不搜索仓库根目录**：工作目录是确定的（`.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`）。找不到就 AskQuestion（`/uo-init` 或源码作答），禁止 Glob/dir 找产物。
- **CLI**：形态见 code-access 不变量。不要写 regex `\|`。
- **卡片 snippet 视为已 Read**：命中已带 `file:line` 与 snippet 时不要再 Read 同一段。路径从卡片 `file` / `next` 复制，禁止猜相对路径。
- **空结果 ≠ 不存在**：`count:0` 先按 `hint` 缩短标识符再查；禁止仓级 `findstr`/`grep`/`rg`。最后才 `pilot_cli` `ro-search --pattern <pat> --paths <已 citation 文件>`。
- **SEL 全集**：第一页 snippet 不是全部合法组合。声称某维没注册必须有 `dim_coverage` 或 `total_matched`。
- **Host branch ≠ Kernel branch**：不得因命名相似直接等同。
- **字段定位看卡片写读**：问句里的局部名常常不是 TILING_FIELD 名；空了看 `next` / `canonical` / `hint`。
- **入口 ≠ 内层函数名**：多阶段 launch 先看无参数索引里的 PIPE 阶段。
- **同名函数**：看卡片全部 kind 与 `edges`，不要只信第一页。
- **宏与 compile-time**：运行时值不能回填成宏条件的唯一真值。
- **unresolved 不可凭命名闭合**。
- **只读**：不得改 `.uo`、不得宣布 workflow PASS。
- **查询完成后立即作答**：禁止仅为问题分类而停滞。
- **`source_span` / 卡片 snippet 足够引用**：不为拿行号而 Read 同一 span。
- **锁当前 architecture**：禁止用其他 arch 的命中闭合本 arch claim。
- **先 verdict 后证据**：差分题禁止「根因已定位」。
