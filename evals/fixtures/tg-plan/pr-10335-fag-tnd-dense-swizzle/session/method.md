# 覆盖模型（Plan Owner）

把「测什么」和覆盖模型写成一份 YAML。禁止 Write；最终消息正文必须就是 YAML。Host 只读最终消息。

读 `tg/init.yaml` + scope。没有 init → 停 `/tg-init`。scope 不清 → 停，回 Primary。照骨架填，不要逆向 schema。禁止读现有 `tg/plan.md` 当模板。

## 快速诊断

每个路径合取项只进一个格子。判定式：**把该项取反后，Target.expected 还能被别的析取支打到吗？**

```
到写点的合取 / 析取
    │
    ├─ 取反后 expected 再也打不到？
    │   └─ Guard（关断整个 Target）。negate_hint 翻回可达。不要当 Dimension 第二格。
    │      probe 量杀整 Target → 用驱动它的 confirmed 列写 Guard；禁止把 probe==0 丢进 constraints 代替 L3
    │
    ├─ 取反后另一支仍能打到 expected？
    │   └─ Dimension（切臂 / 切值）。两格都是可达 ON，不是「开/关」。
    │      同一层 || 的两支放进**同一维**两格（互斥 ON）。不要拆成两个 on/off 维再 L1 交叉
    │
    ├─ 多值字段（内部 round/cost 选出 1/2/3…）？
    │   └─ Target：kind derived + op in values。[replay_field expected] 必须是标量。
    │      Dimension：classifier=replay.<field>，每值 eq 一格。禁止拆 Target / ne 第二格。默认 0 走 Guard（H10）
    │
    ├─ 所有 partition 都成立的派生等式（比率两侧）？
    │   └─ constraints。禁止：钉 Dimension 正在切的列、钉 Guard.controls、只用一个因子冒充比率、
    │      把杀整合取或可切的 probe 布尔堆进来（前者 Guard，后者 Dimension）
    │
    ├─ 平台/UT 字面量（aicNum、coreNum）？
    │   └─ environment，必须能指出 file:line。禁止编造
    │
    └─ unresolved+active 列 / 三层都观测不到？
        └─ untestable control_gap（点列名）或 opaque
```

host 有 `<name> =` → `probe.<name>`，不是 opaque，也禁止用无关列组合去**猜**这个量。
两格都能 HIT 的 probe 必须自己一维（classifier=`probe.<name>`）；不要只出现在 constraints。

## 硬规则

H1–H7 管形式，H8 管可达，H9–H10 管覆盖面。形式绿但覆盖面缩成个位数，一样是失败。

| # | 规则 |
| --- | --- |
| H1 | `controls` / `construct_hint.columns` / 谓词里的 `case.*` 只能是 `confirmed`+`active` |
| H2 | 每个 Target 必须被 **Dimension** 的 `target` 指向（Guard 不算） |
| H2b | `untestable` 与 `targets` 不得重叠 |
| H3 | 直接列 → Dimension/Guard；派生等式 → `constraints:`；核数 → `environment:`。`untestable` 只留给缺列或真 opaque。可切 probe 进 Dimension，杀整合取进 Guard，二者都不要改写成 constraints |
| H4 | 现有表 0 行不是 gap |
| H5 | Dimension 必须对应写点里的实现分岔（if / 早退 / min-max / 多值 / helper 返回值）。禁止用无关幅度凑数；也禁止瘦到只剩入口维。每条新增判定点都要有 Dimension 或 Guard，禁止只写进 requirement.text。同一层 `\|\|` 两支 = 同一维两格互斥 ON；不同层 `\|\|` / 不同 helper 才各自成维。补 Guard 不得删已有析取维 |
| H6 | 一个 Dimension 的所有 partition 切在同一组字段上（同一层 `\|\|` 每格都要带上该层用到的全部 case 列）。禁止把不同层 `\|\|` / helper 折进同一维的 `and` |
| H7 | 同一条 L1/L2 里各 Dimension 的谓词字段集合不相交；跨层（case/probe/replay）可以配 |
| H8 | `partition ∧ constraints ∧ environment ∧ 路径条件 ∧ Target HIT` 可满足。L0 每格、L1 每个笛卡尔格都不能是死格。路径条件含每个被跨过早退的**否定项**。兄弟/legacy 整串门不是本行为前置约束 |
| H9 | 观测面：`replay.<TILING_FIELD>` → `probe.<host 赋值名>` → `case.<col>` → 才允许 opaque |
| H10 | 多值字段：Target 用 `derived`+`in`；Dimension 每值 `eq` 一格。禁止 `replay_field` expected 写成列表，禁止拆 Target，禁止 `ne`/off 第二格 |

`constraints` 与任何 Guard 的 `controls`、任何 Dimension 正在切的列**不相交**。否则 Guard 造不出来，等于没写。

同一合取不要既做 Dimension 的 off 格又做 Guard。`case.*` 必须是 init 列名原文（`Input_Layout` 不是 `input_layout`）。同一 Dimension 两格谓词不得相同，也不得一格蕴含另一格（禁止 `ge 0` 当第二格）。

早退合取的一部分成立时，另一部分不成立仍可能到达写点。不要把 legacy 入口的奇偶/下界整包抄进 `constraints:`。

写点函数里每条新增 `if` / 早退 / min-max 至少落到一个 partition 或 Guard。每个 Dimension ≥2 partitions。`negate_hint` 必须翻 Guard 谓词，不能和 predicate 同值。

发出前扫 init mapping：每个 `unresolved`+`active` 列名必须原样出现在 `untestable`。漏列名 = 失败。

init 已标明 deterministic md5，或改动重排累加顺序仍声称结果不变 → `oracle` 写 md5/精度，禁止 `[]`。

`construct_hint` / `test_harness_gap` 可整块省略。列都能构造就不要写 harness gap。

## 可达性（H8）

`uo_query` 出 Target 字段唯一写点，有界读该函数 + 调用者。路径条件 = 沿途每个 `if (...) return` 的否定 ∧ 写点前必须成立的合取。只抄离写点最近那个 if 的正向条件，往往正好触发早退。

- 否定项优先用 partition 消掉，不要用 constraints 把空间收死。
- 每条 `constraints[]` 必须能指出对应路径条件哪一项；指不出或被蕴含 → 删。
- 某 partition 不可满足 → 换值、降 Guard、或换切分字段。
- RHS 含 `||`：两支都能打到 expected → **同一维**两格互斥 ON（例如 A=1∧B=0 / A=0∧B=1）。禁止拆成两个 on/off 维再 L1 交叉（(off,off) 是死格）。不能打到 → 外层失败才 Guard。
- helper 只杀一支时：可单独成维（unsafe 格靠另一支 HIT）；不要和切那一支的维做 L1。
- L1 只配笛卡尔每格都能 Target HIT 的对。

## 观测与规模（H9 / H10）

classifier 给跑完的行贴标签。`case.*` / `probe.*` / `replay.*` 都合法。

- probe 用有辨识度的长名（禁 `p`/`q`/`m`/`n`/`l1`）；赋值须无条件执行。
- 发出前清点写点每一层 `||` 和每个 helper：同一层两支同一维；不同层才分维。每个 host `<name> =` 若两格都能 HIT，必须有 probe Dimension。判定点远多于 partition → 漏覆盖、误判 opaque、或把判定点堆进了 constraints。
- 谓词跨 case/probe/replay 时 L1 通常不该空。

## 谓词

`op` 仅：`eq ne in not_in lt le gt ge mod_eq is_null is_present and or not`

- `and`/`or`：`{op: and, args: [<pred>, <pred>]}`；`not`：`{op: not, arg: <pred>}`
- `in`/`not_in` 用 `values:`；`mod_eq`：`{op: mod_eq, left: <field>, divisor: <n>, value: <expect>}`
- 字段只有两段：`case.<列>` / `replay.<叶子字段>` / `probe.<长名>`。禁止 `replay.<struct>.<field>`、禁止 `environment.*`
- `constraints[]` 必须有 `id`；`eq` 用 `{op: eq, field: probe.x, value: <标量>}`，禁止 `left`/`right` 对象
- 字面量对齐 init `inferred_type`：int 不加引号
- `evidence.field` 不能是 precision / md5（进 `oracle`）
- 多值 Target：`kind: derived` + `{op: in, field: replay.x, values: [1,2,3]}`。`replay_field`/`probe` 的 `expected` 必须是标量
- Guard 谓词根必须是 `case.*`，且带非空 `negate_hint`

## 骨架

```yaml
schema: tg-plan/v3
requirement:
  id: R-<slug>
  text: >
    <逐符号标新增 vs 既有。写出到写点的路径条件，含早退否定项；析取支写明哪些能打到 expected>

targets:
  - id: T-<slug>
    evidence: {kind: replay_field, field: replay.<tiling_field>, expected: 1}
  # 多值字段改用：
  # evidence:
  #   kind: derived
  #   predicate: {op: in, field: replay.<tiling_field>, values: [1, 2, 3]}

dimensions:
  - id: D-<arm>
    target: T-<slug>
    controls: [<confirmed_col>]
    classifier: {requires: [case.<confirmed_col>]}
    partitions:
      - {id: p-arm-a, predicate: {op: eq, field: case.<confirmed_col>, value: <v_on_a>}}
      - {id: p-arm-b, predicate: {op: eq, field: case.<confirmed_col>, value: <v_on_b>}}
  - id: D-<mode>
    target: T-<slug>
    controls: [<confirmed_col>]
    classifier: {requires: [replay.<tiling_field>]}
    partitions:
      - {id: p-1, predicate: {op: eq, field: replay.<tiling_field>, value: 1}}
      - {id: p-2, predicate: {op: eq, field: replay.<tiling_field>, value: 2}}
  - id: D-<probe>
    target: T-<slug>
    controls: [<confirmed_col>]
    classifier: {requires: [probe.<long_name_with_assignment>]}
    partitions:
      - {id: p-a, predicate: {op: eq, field: probe.<long_name_with_assignment>, value: <va>}}
      - {id: p-b, predicate: {op: eq, field: probe.<long_name_with_assignment>, value: <vb>}}

guards:
  - id: G-<slug>
    target: T-<slug>
    controls: [<confirmed_col>]
    predicate: {op: ne, field: case.<confirmed_col>, value: <v_on>}
    negate_hint: {<confirmed_col>: <v_on>}

coverage:
  L0: {dimensions: [D-<arm>, D-<mode>, D-<probe>]}
  L1:
    combinations:
      - {dims: [D-<a>, D-<b>], reason: "<实现里为何交互>"}
  L2: []
  L3: {guards: [G-<slug>]}

oracle: []
constraints:
  - id: c-<slug>
    predicate: {op: eq, field: probe.<long_name>, value: 1}
environment:
  aicNum: <int from UT/platform file:line>
  coreNum: <int from UT/platform file:line>

untestable:
  - id: u-<col>
    kind: control_gap
    reason: "<unresolved 列挡住哪块覆盖>"
    needs_binding:
      - {column: <col>, want: "confirmed+active，并证实 <传导链>"}
```

## 步骤

1. 读 init + packet。筛 `confirmed`+`active`。列出 `unresolved`+`active` 列名（最后必须进 untestable）。
2. `uo_query` 写点 → 有界读函数+调用者 → 写出路径条件（含否定项、析取支）。
3. 按快速诊断把合取项分到 Dimension / Guard / constraints / environment / untestable。核对三不相交。
4. 入口用 case，内部门用 probe，多值字段用 replay。每个 Dimension ≥2。写点里还没落地的 if/min-max 优先建维，不要先删再变瘦。
5. 逐 L0 partition 过 H8：该格 ∧ Target HIT 可满足。off 格若杀整 Target → 改 Guard。
6. L0 全维度；L1 只配实现里真交互、字段不相交、且笛卡尔每格都能 HIT 的对；L3 放使 **整个** Target 不成立的门。
7. 清点判定点；`requirement.text` 写可达性（含否定项与析取支），并点名 packet 里每个新增/改动符号（host 写点与 kernel 被改函数都要出现）。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 没有 init / scope 不清 | 停 |
| `partial`/`unresolved` 列 | `untestable` `control_gap`，点列名，不进 controls |
| 派生等式 / 核数 | `constraints:` / `environment:`（有出处）。杀整合取/可切 probe 不要进 constraints |
| 现有表 0 行 | 不是 gap |
| 写点前 `if (...) return` | 路径条件取否定；能用 partition 消掉就放 partition |
| 写点 RHS 含 `\|\|` | 两支都能 HIT → **同一维**两格互斥 ON；不要拆成两个 on/off 维 |
| 同一层 `\|\|` 两格 case 列集合不同 | H6：每格都要带上该层用到的全部 case 列；缺列的那格用与另一格互斥、且不把本臂 ON 切出空洞的界（不要只写其中一列） |
| helper 只杀一支却和切臂维做 L1 | 笛卡尔有死格；helper 只放 L0，或不配这条 L1 |
| replay_field expected: [1,2,3] | 改 `derived` + `op: in`；Dimension 再 eq 分格 |
| constraints `left: {field:}` / `environment.*` | `{op: eq, field: probe.x, value: <int>}`；核数进 environment 整数 |
| L1 配出 Target 不可达的格子 | 删这条 combination |
| partition 一格蕴含另一格（第二格只有 ge 0） | 废格；两格必须互斥可分。H6 补列可以用不缩小本臂的合取，但不能当第二格的全部谓词 |
| 把 helper 和入口布尔折进同一维 and | H6 违规；helper 自己一维（两格都 ON） |
| 补了 Guard 但 Dimension 只剩 2–3 个 | 析取维被删了；补 L3 不得换预算删维 |
| partition 恰好触发早退 | 换值或降 Guard |
| 约束列出现在 Guard.controls | 删这条 constraint，否则 Guard 死 |
| 约束说不出对应哪项合取 | 删；多半抄了兄弟分支 |
| 多值字段由内部比较决定 | Target `derived`+`in`；Dimension 每值 eq；不要拆 Target / eq+ne / expected 列表 |
| Guard 谓词根是 probe.* | 升到驱动它的 confirmed 列；probe 只做 Dimension classifier |
| 同一合取既 off 格又 Guard | 取反后整 Target 不可达 → 只留 Guard |
| case.* 自造列名 | 用 init 列名原文 |
| 同一 Dimension 两格谓词相同 | 废维；去切尚未覆盖的 if/min-max |
| host 局部量有 `<name> =` | `probe.<name>`，不要用无关列组合冒充 |
| 两格只改幅度、没有实现分岔 | 不要用它凑数；去切尚未覆盖的 if/min-max |
| 判定点很多 partition 个位数 | 漏覆盖、误判 opaque、或把 if/probe 堆进了 constraints；补维 |
| 杀整 Target 的 probe 只出现在 constraints | 升到驱动列写 Guard；L3 不得只剩 layout/B |
| 可切的 probe 只出现在 constraints | 改成 Dimension（classifier=`probe.<name>`，两格都 ON） |
| 枚举值因部分走 legacy 被整支删掉 | 取反早退合取后仍 HIT 的取值必须有 partition |
| 新增 helper 返回值只杀一支 | Dimension（两格都 ON），不要只写进 requirement 散文 |
| negate_hint 取值仍让 Guard 谓词为真 | 必须使谓词为假（翻回可达） |
| 谓词跨 case/probe/replay | L1 应当非空 |
| 用户没点且改动无关精度 | `oracle: []` |
| packet 有 kernel/host 符号但 requirement 没点名 | 补进 text，标新增 vs 既有 |

## 反模式

- 写散文 / Write 磁盘 / 默认全量 Key
- unresolved 列进 controls；漏掉 unresolved 列名
- 为凑 L0/L1 造无关 Dimension；同列两维放进同一条 L1
- 把 corpus 0 行或派生/环境写成 untestable
- 只抄最近一个 if 的正向条件；把 legacy 入口门抄进 constraints
- 只断言 `> 默认值`；host 有赋值的量写成 opaque
- 每个枚举值一个 Target 再配 on/off Dimension
- 同一合取既做 Dimension 的 off 格又做 Guard
- `case.*` 不用 init 列名原文；同一 Dimension 两格谓词相同
- 用 Guard 把仍能打到 expected 的析取支标死
- 把同一层 `||` 拆成两个 on/off 维再 L1 交叉；把多层 `||` / helper 折进一个 Dimension 的 `and`
- `replay_field` expected 写成列表；constraints 用 left/right 对象或 `environment.*`
- L1 配出 Target 不可达的死格；partition 一格蕴含另一格
- `constraints` 钉死 Guard 或 Dimension 正在切的列
- 用 constraints 代替 Guard（L3 只剩 1–2 扇门）
- 把可切 probe / 杀整合取堆进 constraints，Dimension 只剩枚举值加两三个入口列
- 写点 helper 的返回值只写进 requirement.text
- 用无关列组合冒充 probe 局部量
- probe 短名或 `if` 体内才赋值
- Guard 绑 expected=0/DISABLED 的 Target
- `requirement.text` 漏掉 packet 里的新增/改动符号（尤其 kernel 被改函数）
