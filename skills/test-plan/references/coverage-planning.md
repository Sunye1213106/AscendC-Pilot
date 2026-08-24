# 覆盖模型（fuse）

把 Primary 转述的测试意图写成 **YAML 覆盖模型**：Dimension partitions / classifier、L0–L3。正式 `plan.md` 由 Primary 散文 + 本窗 YAML 经 `plan_promote` 拼成。

子代理禁止 Write；最终消息只交 YAML。不要写三节散文。

## 输入 / 输出 / 停

读：`tg/init.yaml`、注入的 scope 回答。没有 init → 停，去 `/tg-init`。scope 没说清要测什么 → 停，让 Primary 再问 scope，不要自己改成全量 TilingKey。

交回：`schema: tg-plan/v3` YAML。禁止 Write。

**最终消息的正文必须就是 YAML 本身。** Host 只读最终消息（`output_mode: return_value`）。不要只交摘要，不要写「见上文」「已在上面给出」「YAML 在前一条消息」—— 放在中间消息里的内容 Host 取不到，等于本窗白跑。

完成：每个 Dimension 有 controls、≥2 partitions、结构化 classifier；coverage 含 L0–L3；谓词都是 mapping `op=`；四条硬规则全过。

**不要去逆向 schema。**下面的骨架就是全部合法字段，谓词算子表就是全部合法 `op`。照填即可。

## 四条硬规则

先过这四条，再谈覆盖面。违反任一条，产物会被 `plan_validate` 打回。

| # | 规则 | 判定 |
| --- | --- | --- |
| H1 | **controls 只能用 `confirmed` + `active` 列** | `controls` 与 `construct_hint.columns` 里每一列，以及 partition / guard 谓词里的每个 `case.*` 字段，在 `init.yaml` 里必须 `confidence: confirmed` 且 `control.status: active`。谓词用到的 `case.*` 还必须写进该 Dimension/Guard 的 `controls`。`partial` / `unresolved` / 非 `active` 一律不许出现 |
| H2 | **每个 Target 至少被一个 Dimension 指向** | 必须是 **Dimension** 的 `target` 指向（Guard 的 `target` **不算**）。没有就删掉它，或降级进 `untestable`。孤儿 Target 只会产出永久 UNKNOWN |
| H2b | **`untestable` 与 `targets` 不得重叠** | 一个东西要么是 Target（可 HIT、有 Dimension 指向），要么在 `untestable` 里（**不出现在 `targets` 列表**）。不可达的状态**不要**先声明成 Target 再补一条 `untestable` —— 那还是孤儿 Target，义务照样产出，永远 UNKNOWN |
| H3 | **门禁项控不到 → `untestable` + `needs_binding`** | scope 的门禁合取项里，凡是由 `partial`/`unresolved` 列或「非列」（平台常量、环境值、内部派生量）决定的，逐项写进 `untestable`，并在 `test_harness_gap.needs_binding` 里点名要提级的列。不要绕过，也不要假装可控 |
| H4 | **可达性为 0 → 必写 `test_harness_gap`** | scope 的 C 项（现有 case 表满足全部门禁的行数）为 0，或 L0 某个 partition 在现有表里 0 行，就必须写 `test_harness_gap` 块。此时**不要**硬凑一堆指向不可达 Target 的 Dimension |
| H5 | **Dimension 必须与本次改动的行为面有实现层关联** | 不要为了凑满 L0 / L1 / L2 而把与本次改动无关的列做成 Dimension —— 即使它是 `confirmed` 列。宁可只有一个 Dimension |
| H6 | **一个 Dimension 的所有 partition 必须切在同一组列上** | 不许一个 partition 按 A 列切、另一个按 B 列切（「混列维度」）。一个 Dimension 回答一个问题；要按两件事切就拆成两个 Dimension |
| H7 | **进 L1 / L2 配对的 Dimension，partition 谓词约束的列不得交叠** | 引擎把 L1 / L2 做**笛卡尔展开**，同一列被两个维度各自约束时会产出自相矛盾（`col=4` ∧ `col∈{5,6}`）或退化（两边同约束）的义务。这类义务 solve 永远造不出行，worklog 不闭合，certify 卡死 |

**H1 最常见的漏法**：把 `partial` / `unresolved` 列塞进 `construct_hint.columns` 当「构造提示」。引擎把 `controls` 和 `construct_hint.columns` **合并**做同一套 bound-control 校验，塞进去一样报错。想表达「构造这条 case 需要这些列」，写到 `test_harness_gap.missing_rows` 的自然语言里，并在 `needs_binding` 点名提级。

`construct_hint.columns` 只放 `confirmed`+`active` 列；没有这样的列可放就整个省掉 `construct_hint`。

H1 的推论：如果主行为的门禁**全部**落在非 confirmed 列上，那这一轮就没有合法的确定性 Dimension 可建。正确做法是只交付那些能用 confirmed 列观测的次级 Target（例如新字段在既有路径上的默认值 / 布局对齐），其余全部进 `untestable` + `test_harness_gap`。**交一份诚实的小 plan，比交一份指向不可达 Target 的大 plan 有用。**

H5 的判据：问「本次改动如果回退，这个 Dimension 的 partition 之间还会有差别吗？」答案是「照旧有差别、跟本次改动无关」，就删掉它。L1 / L2 宁可为空，也不要拿无关维度配对。

H6 / H7 的自检：把每个 Dimension 的每个 partition 谓词引用的列写出来。同一 Dimension 的各 partition 列集合必须**相同**（H6）；要放进同一条 L1 / L2 的两个 Dimension，列集合必须**不相交**（H7）。有交叠就别配对 —— L1 留空是合法的。

`test_harness_gap` 是**阻塞信号**，不是备注：`solve_precheck` 见到它未闭合会直接停住 solve，要求先补测试脚本仓再回 `/tg-init`。

**判 gap 的机械做法**：把你这份 plan 将要产生的义务逐条列出来 —— L0 的每个 partition、L1 的每个组合、L2 的每个 tuple、L3 的每个 guard。对每一条问一句：**用现有 case 表能不能挑出至少一行满足它？**

- 全都能挑出 → **不写** `test_harness_gap`。
- 有任何一条挑不出 → 写 gap，并在 `reason` 里点名是哪条义务挑不出。

最容易搞错的一点：**「主行为正向 witness 不可达」不是 gap。** 不可达的东西已经进了 `untestable`，`untestable` **不产生义务**，因此不构成「有义务却造不出行」。这种情况下 plan 应当放行 solve，让已可解的那批义务先闭合；把「将来要补的行」写进 `untestable[].reason` 或 `requirement.text` 说明即可。写了 gap 就等于把这批本来能跑的义务一起挡在门外。

交了 gap 块，就要在最终消息里明确告诉 Primary「本 plan 阻塞 solve，需先补仓」，否则散文那侧不会带上对应标题，阻塞信号会静默丢失。

## 谓词算子

`op` 只能取这些：

```text
eq  ne  in  not_in  lt  le  gt  ge  mod_eq  is_null  is_present  and  or  not
```

- `and` / `or`：`{op: and, args: [<pred>, <pred>]}`
- `not`：`{op: not, arg: <pred>}`
- `in` / `not_in`：用 `values: [...]`，不是 `value:`
- `mod_eq`：`{op: mod_eq, left: <field>, divisor: <n>, value: <expect>}` —— 奇偶 / 对齐约束用这个
- 其余：`{op: <op>, field: <field>, value: <v>}`

字段只能是 `case.*` / `replay.*` / `probe.*` 或可解析的裸 symbol。自由文本谓词不得进 YAML。

**字段只有两段。** `replay.<字段名>`、`case.<列名>`。TilingData 在源码里是嵌套结构，但解码器展平且不带 struct 名，所以**不要**写 `replay.<struct>.<field>` —— `plan_validate` 会打回。详见 `refs/test-plan/evidence.md` 的「字段粒度」。

**字面量类型必须对齐 `init.yaml`。** 查 `domains.<col>.profile.inferred_type`：
- `int` / 数值型 → 写数字字面量，**不加引号**：`value: 4`、`values: [5, 6]`
- `enum-string` / 字符串型 → 写字符串：`value: BNSD`

引擎的 `eq` / `in` 会把数字和数字字符串当成同一个值（`4` 与 `"4"` 相等）。**仍然按 `init.yaml` 的 `inferred_type` 写字面量**：`int` 列不要加引号。大整数不要指望 float 归一。

`evidence.field` 不能是 oracle 量（含 `precision`、以 `md5` 结尾等）——那些进 `oracle`，不是 Target 观测点。

## 骨架

占位符用 `<>` 标出，全部替换成本次的真实名字。字段集合就这些，不要发明新字段。

```yaml
schema: tg-plan/v3
requirement:
  id: R-<slug>
  text: >
    <本次要回归的行为一句话。**必须逐个符号标注**哪些是本次新增、哪些是既有
     （既有的写「既有字段/既有函数，本次仅新增写入路径」之类），不要把新增的和
     既有的并列成「新增 X、Y、Z」。如果主行为不可达，在这里写清结论>

targets:
  - id: T-<slug>
    # field 只有两段：replay.<解码后的纯字段名>，不要带 struct 前缀
    evidence: {kind: replay_field, field: replay.<tiling_field>, expected: <value>}
  - id: T-<slug2>
    evidence:
      kind: derived
      predicate: {op: gt, field: replay.<tiling_field>, value: 0}

dimensions:
  - id: D-<slug>
    target: T-<slug>
    controls: [<confirmed_col>]
    classifier:
      requires: [case.<confirmed_col>, replay.<tiling_field>]
    construct_hint:
      columns: [<confirmed_col>, <another_confirmed_col>]
    partitions:
      - {id: <p1>, predicate: {op: eq, field: case.<confirmed_col>, value: <v1>}}
      - {id: <p2>, predicate: {op: eq, field: case.<confirmed_col>, value: <v2>}}

guards:
  - id: G-<slug>
    target: T-<slug>
    controls: [<confirmed_col>]
    predicate: {op: ne, field: case.<confirmed_col>, value: <v>}
    negate_hint: {<confirmed_col>: <v>}

coverage:
  L0: {dimensions: [D-<slug>]}
  L1:
    combinations:
      - {dims: [D-<a>, D-<b>], reason: "<这一对为什么在实现里真的交互>"}
  L2: []
  L3: {guards: [G-<slug>]}

oracle: []

untestable:
  - id: u-<slug>
    reason: >
      <门禁项 X 由 partial/unresolved 列或非列决定，不能写成确定 classifier；
       给出该列名与 confidence，或说明它是平台/环境常量>

test_harness_gap:
  done: false
  reason: "<现有 case 表 N 行中 0 行可命中；缺哪几个门禁项>"
  observed: {corpus_rows: <n>, rows_satisfying_full_gate: 0}
  needs_binding:
    - {column: <col>, want: "confirmed+active，并证实 <传导链>"}
  missing_rows:
    - "<把门禁合取项写成一行 case 需求>"
  alternative_carrier:
    - "<若另有更直接的回归载体（如 host UT 可直接断言 tiling），在此点名>"
```

`guards` 的 `predicate` 是「使 Target 不成立」的条件，`negate_hint` 是翻回去的赋值。两者都必须能从 case 列构造 —— 别拿 `replay.*` 当 guard 谓词根，那样 solve 无法构造 negation。

`oracle` 默认 `[]`；用户没点精度 / 性能就不要加。

`test_harness_gap` 不适用时整块省略。

## 步骤

1. 读 scope 的四项必答（可控面 / 触发门禁 / 可达性 / 新增 vs 既有）。缺项就停，回 Primary。
2. 按 H1 筛出可用列集合。**先筛列，再想 Dimension。**
3. 按 H3 把门禁里控不到的项逐条写进 `untestable`。
4. Dimension root 到 controls。列必须在可用集合里（H1），且在 init 列或 `added_columns`。
5. 划 semantic partitions。不是枚举原始 B/N/S/D，也不是把某个列的取值逐个列出来当 partition —— partition 要对应**实现里真的分岔**（同一列的不同取值可能落进同一分支，或某个取值会提前返回保持默认）。
6. 为每个 Dimension 定义 deterministic classifier。`requires` 必须是 Replay 能给的 `case.*` / `replay.*` / `probe.*`。
7. 删除 unobservable / uncontrollable / 与意图无关的轴。按 H2 清掉孤儿 Target。
8. L0：每 partition 一个 witness。无 Dimension 时 L0 可空。
9. L1：只选 UO 有交互的 pair，并写 `reason`。
10. L2：只选有明确高阶实现关系的 tuple。
11. L3：每个 Guard 生成最小 negation obligation。
12. 按 H4 决定要不要写 `test_harness_gap`。
13. 用户**点名**全量 TilingKey 才 `coverage.enumerate: legal_keys`。禁止自行 `mode: T=D`。

## 发出前自检

逐条核对。任一条不过就改，别提交。

- [ ] **H1** `controls` 与 `construct_hint.columns` 里每一列，在 `init.yaml` 里都是 `confirmed` + `active`
- [ ] **H2** 每个 `targets[].id` 都至少被一个 **Dimension** 的 `target` 指向（Guard 指向不算）
- [ ] **H2b** `untestable[]` 里的条目没有同时出现在 `targets[]` 里
- [ ] **H3** scope 门禁里控不到的项，逐条在 `untestable` 有对应条目
- [ ] **H4** 逐条义务核对过可构造性；全可解 → 没写 `test_harness_gap`
- [ ] **H5** 每个 Dimension：本次改动若回退，它的 partition 之间就不该再有差别
- [ ] **H6** 每个 Dimension 的所有 partition，谓词引用的列集合完全相同
- [ ] **H7** 同一条 L1 / L2 里的两个 Dimension，谓词列集合不相交
- [ ] `requirement.text` 里本次新增 / 既有逐符号标注清楚
- [ ] 每个谓词字面量的类型对齐 `init.yaml` 的 `domains.<col>.profile.inferred_type`（`int` 列不加引号）
- [ ] 所有 `case.*` / `replay.*` / `probe.*` 都只有**两段**，没有 `replay.<struct>.<field>` 这种子结构前缀
- [ ] `evidence.field` 都是 `case.*` / `replay.*` / `probe.*`，且不是精度 / md5 这类 oracle 量
- [ ] 每个 Guard 有非空 `negate_hint`，且谓词根是 case 列（不是 `replay.*`）
- [ ] 最终消息正文就是 YAML 全文，不是摘要、不是「见上文」

## 常驻判断

```text
accuracy PASS 但 Evidence 没打到 ≠ 已覆盖
Host TilingKey HIT ≠ Target HIT（除非 evidence 就是那条 field）
自由文本谓词不得进 YAML
只有 confirmed 控制关系才能写成确定 classifier
可达性为 0 的 Target 不是覆盖，是 gap
```

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 init.yaml | 停，去 `/tg-init` |
| scope 没说清测什么 / 缺四项必答 | 停，回 Primary / scope；不要编全量 key |
| 用户点名全量 tilingkey | `enumerate: legal_keys` |
| 某维控不到列 | `untestable` + reason（H3） |
| 门禁全落在非 confirmed 列 | 只交次级可测 Target + `test_harness_gap`；不硬凑（H1 推论） |
| 缺列或缺生成器 / 可达 0 行 | `test_harness_gap`（H4） |
| Target 没有 Dimension 指向 | 删或降级（H2） |
| 想表达「这个状态存在但不可达」 | 只写 `untestable`，**不要**同时列进 `targets`（H2b） |
| 一个 Dimension 的 partition 切在不同列 | 拆成两个 Dimension（H6） |
| 两个 Dimension 约束同一列 | 不要放进同一条 L1 / L2（H7） |
| 义务都能用现有行构造 | **不要**写 `test_harness_gap`，否则白挡 solve |
| 正向 witness 不可达、已进 `untestable` | 不是 gap（untestable 不产生义务）；别因此阻塞 solve |
| 用户没点精度/性能 | `oracle: []` |
| 想去读引擎源码确认 schema | 别去；本文骨架与算子表即全部合法字段 |

## 反模式

- 写 plan.md 散文三节（那是 Primary 的）
- 默认全量 Key
- 把 unresolved / partial 绑定写成确定 classifier（H1）
- 把 `partial` / `unresolved` 列塞进 `construct_hint.columns`（H1，最常见的漏法）
- 为了凑满 L0 / L1 / L2 造与本次改动无关的 Dimension（H5）
- 一个 Dimension 里混用两组切分列（H6）
- 把约束同一列的两个 Dimension 放进同一条 L1 / L2（H7，会生成造不出行的死义务）
- 义务本来都能构造，却写了 `test_harness_gap`，白白挡住 solve
- 把「正向 witness 不可达」当成 gap（它是 `untestable`，不产生义务）
- 把不可达状态又声明成 Target 又写进 `untestable`（H2b；那还是孤儿 Target）
- 拿 Guard 的 `target` 冒充 H2 要求的 Dimension 指向
- `requirement.text` 里把本次新增的符号和既有符号并列成「新增 X、Y、Z」
- 留孤儿 Target（H2）
- 把 scope 说的「门禁项控不到」悄悄降级成一句 `untestable` 附注，却照旧把 L0–L3 建在该 Target 上
- 可达性 0 行却不写 `test_harness_gap`（H4）
- 把某个列的取值逐个列成 partition，不管它们在实现里是否真的分岔
- 逆向引擎源码去猜 schema
- Write 磁盘
