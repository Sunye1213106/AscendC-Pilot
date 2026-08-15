# UO CodeMap Query — Gotchas

高信号易错点。流程见 `uo-product-map.md` 与 `capabilities/uo-query/METHOD.md`，不要在此复述预算表。

- **CodeMap 优先于源码通读**：已有 `.uo` 时先结构化查询；不要一上来 grep 整棵算子树。
- **缺 `.uo` 不考古**：工作目录是确定的（`.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`）。找不到就 AskQuestion（`/uo-init` 或源码作答），禁止 Glob/dir 找产物。
- **CLI**：`--pattern`（`--query` 是别名）。`Dim=V,Other=V` 走 `template_match` / `legal_key`。不要写 regex `\|`。
- **空结果 ≠ 不存在**：`count:0` 先按 `hint` 缩短标识符再查；禁止仓级 `findstr`/`grep`/`rg`。最后才 `acp ro-search --paths <已 citation 文件>`。
- **SEL 全集**：第一块 `ARGS_SEL` 不是全部合法组合。声称某维没注册必须有 `template_match.dim_coverage` 或 `legal_key.total_matched`。
- **Host branch ≠ Kernel branch**：不得因命名相似直接等同。
- **字段定位看 writer，不看最后赋值**：保存→修改→恢复的临时赋值不是最终来源。问句里的局部名常常不是 TILING_FIELD 名；`field` 空了看 `local_aliases` / `suggested_retries`，再查一轮即可。
- **入口 ≠ 内层 Process**：Pre/Main/Post 先 `kernel_launch` / `pipeIn` / KERNEL / `*_entry*.h`，禁止把 `Process()` 里的 V1–V6 或 `*_apt.cpp` 当成三相。
- **Host TilingContext ≠ kernel_api**：`SetScheduleMode` / `SetBlockDim` 用 `locate`。`SyncALLCores` 是工程方法，也用 `locate`，不要当 CANN `kernel_api`。
- **同名函数**：`.h` 虚函数不是唯一实现；看 `locate` 的全部 `definition_sites`。
- **宏与 compile-time**：运行时值不能回填成宏条件的唯一真值。
- **unresolved 不可凭命名闭合**。
- **只读**：不得改 `.uo`、不得宣布 workflow PASS；Explorer 不写文件。
- **查完就答**：不要为空转路由停住；不静默扩大到 full reachability。
- **用图，不用仓内 Glob**：`impact` / `locate` / `template_match` 先于 Grep。
- **`source_span` 足够引用**：不为拿行号而 Read；无 span 标 `PARTIAL` / `UNKNOWN`。跨窗扩到 SEL 闭合 / 下一 TPipe 允许。
- **锁当前 architecture**：禁止用其他 arch 的命中闭合本 arch claim。
- **先 verdict 后证据**：禁止把结论埋在长推理末尾。差分题禁止「根因已定位」。
