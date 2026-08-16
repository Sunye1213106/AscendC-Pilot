# Context（agent 常驻词表）

用这里的词思考和说话。人类全表：`docs/reference/glossary.md`。

**CodeMap** — UO 写入的 `.uo` 源码语义图。不是通用 call-graph。
**digest** — session binding 上的 `canonical_graph_digest`。fresh = digest 匹配，不是「刚建过库」。
**短问** — 一名字、一 mode、一两跳；一次 `acp uo-query` stdout 即完成。
**深问** — 画图 / 多变体 / METHOD ≥2 行 / 差分；同一轮 `Task(agent=uo-query)`。
**可见 LLM 路由** — 查询不是 Host workflow：先对人说出短问或几个 Task，再动手。
**Open** — 未闭合集合。CE：`Open = O - V - X`。TG：`T` 中尚未进入 `(R∩T)∪E` 的元素。两套账本，不要合并。
**Tier A/B/C** — A 权威窗口，B 由 A 确定性推出，C 是线索。C 不能把义务送进 `V` 或 `X`。
**R / E / T / D** — TG：`R` Host replay 见证，`E` 源码不可达引理，`T` 已批准目标，`D` 声明 legal key。完成：`T = (R∩T) ∪ E` 且 `R∩E = ∅`。`Replay reject ≠ E`。
**quality.yaml** — 建库评价看 `grade` / `locate_blocking`，不看 unresolved 条数。

## 同名不可互换

跨 UO / TG / CE 传递时必须带限定，不能按名字合并：

| 词 | UO | TG | CE |
| --- | --- | --- | --- |
| obligation | `key_field_obligations`（legacy） | `coverage_obligations.yaml` | 账本 `ce-{risk_class}-{digest}` / `O-V-X` |
| fingerprint | graph 直方图 digest | kb 文件 sha256 | `cm_graph_fingerprint` 或 git revision；fresh 比 handle.digest |
| kind | `EntityKind`（FIELD ≠ TILING_FIELD） | binding：`key_dim` / `key_dim_host` | risk 路由 |
| TilingKey | CodeMap 维实体 | contract 里 `D` 是 packed int | dispatch 锚点 |
