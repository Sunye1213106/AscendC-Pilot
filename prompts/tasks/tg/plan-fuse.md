<task>
基于 `tg/init.yaml` 与 Primary 转述的 scope 回答，交回覆盖模型 YAML（Dimension / classifier / L0–L3）。不要写 `plan.md` 散文，不要 Write。
</task>

<input>
- Init: `<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Scope answer: Host 注入的上一窗自然语言（不是磁盘 YAML 文件）
- UO query authority: `<UO_ROOT>`
</input>

<method>
`references/coverage-planning.md` 里有完整 YAML 骨架与合法 `op` 全集。**照填，不要去逆向引擎源码猜 schema。**

先过四条硬规则，再谈覆盖面：
- **H1** `controls` 与 `construct_hint.columns` 只能用 init.yaml 里 `confidence: confirmed` 且 `control.status: active` 的列。引擎把这两处**合并**校验；把 `partial`/`unresolved` 列塞进 `construct_hint.columns` 当「构造提示」是最常见的漏法，一样报错 —— 该写进 `test_harness_gap.missing_rows`。
- **H2** 每个 Target 至少被一个 **Dimension** 的 `target` 指向（Guard 的 `target` 不算）；孤儿 Target 删掉。
- **H2b** `untestable` 与 `targets` 不得重叠。想表达「该状态存在但不可达」，就**只**写 `untestable`，不要又列进 `targets` —— 否则仍是孤儿 Target，义务照样产出且永远 UNKNOWN。
- **H3** scope 门禁里由 `partial`/`unresolved` 列或「非列」决定的项，逐条写进 `untestable`，并在 `test_harness_gap.needs_binding` 点名要提级的列。
- **H4** scope 的可达性为 0（或某 partition 现有表 0 行）→ 必须写 `test_harness_gap`，且不要硬凑指向不可达 Target 的 Dimension。
- **H5** Dimension 必须与本次改动的行为面有实现层关联。判据：本次改动若回退，该 Dimension 的 partition 之间还有差别吗？照旧有差别就说明无关，删掉。宁可只有一个 Dimension，L1/L2 为空。
- **H6** 一个 Dimension 的所有 partition 必须切在同一组列上。要按两件事切就拆成两个 Dimension。
- **H7** 进同一条 L1/L2 的两个 Dimension，partition 谓词约束的列不得交叠 —— 引擎做笛卡尔展开，同列交叠会产出自相矛盾（`col=4` ∧ `col∈{5,6}`）或退化的死义务，solve 造不出行、certify 卡死。

`test_harness_gap` 是**阻塞信号**（`solve_precheck` 会停住 solve 并要求先补测试脚本仓），不是备注。判法：把将要产生的义务逐条列出（L0 每 partition / L1 每组合 / L2 每 tuple / L3 每 guard），逐条问「现有 case 表能否挑出至少一行满足它」—— 全能挑出就**不要**写 gap。

**「主行为正向 witness 不可达」不是 gap**：不可达的已进 `untestable`，而 `untestable` 不产生义务，不构成「有义务却造不出行」。此时应放行 solve 让已可解的义务先闭合，把将来要补的行写进 `untestable[].reason` / `requirement.text`。交了 gap 就在最终消息里明确提示 Primary「本 plan 阻塞 solve」。

`requirement.text` 必须逐符号标注本次新增 vs 既有，不要并列成「新增 X、Y、Z」。

谓词字面量类型对齐 `init.yaml` 的 `domains.<col>.profile.inferred_type`：`int` 列写数字不加引号（`value: 4`），`enum-string` 列写字符串。引擎 `eq`/`in` 会把 `4` 和 `"4"` 当成同一个值。字面量仍按 `inferred_type` 写：`int` 列不要加引号。

`case.*` / `replay.*` / `probe.*` **只有两段**。TilingData 在源码里是嵌套结构，但解码器展平且不带 struct 名，写成 `replay.<struct>.<field>` 会被 `plan_validate` 打回。字段名查 UO `kernel_tiling_view` stub 的叶子名。

若主行为门禁全部落在非 confirmed 列上：只交付能用 confirmed 列观测的次级 Target（如新字段在既有路径上的默认值 / 布局对齐），其余进 `untestable` + `test_harness_gap`。诚实的小 plan 优于指向不可达 Target 的大 plan。
</method>

<output>
最终消息只交 `schema: tg-plan/v3` 的 YAML（可围栏）。禁止写「测什么 / 覆盖什么 / 怎么判定」三节散文（那是 Primary 的）。不要 Write staging / parts / 正式 `tg/plan.md`。

**最终消息的正文必须就是 YAML 全文。** Host 只读最终消息（`output_mode: return_value`），中间消息取不到。不要只交摘要，不要写「见上文」/「已在上面给出」/「YAML 在前一条消息」—— 那等于本窗白跑。YAML 之后可以再加一句「本 plan 是否阻塞 solve」。
</output>
