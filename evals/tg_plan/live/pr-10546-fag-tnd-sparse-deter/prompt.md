<task>
你是 Plan Owner。把本次改动编译成一份覆盖模型：**测什么**（Target）、**怎么切**（Dimension / Guard）、**哪些组合不可能**（L2 互斥）。只交 `schema: tg-plan-fill/v1` 填空 YAML，不写散文，不落盘。引擎会展开成 `tg-plan/v3`。
</task>

<input>
- Init: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/init.yaml`
- Packet: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_10546_eval/receipts/plan_scope_packet.yaml`
- UO query authority: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad/.ascendc-pilot/arch35/uo`
- Source scope: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_10546_eval/actions/plan_ingest/environment_capabilities.yaml` 的 `source_scope.file_paths`（路径相对 project_root）
- project_root: `D:/PR-review/TEST/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-10546/attention/flash_attention_score_grad`
</input>

<method>

先读 `D:/PR-review/AscendC-Pilot/evals/tg_plan/live/pr-10546-fag-tnd-sparse-deter/method.md`，那就是本窗形式规范。禁止打开 `evals/fixtures`。禁止读 plan.golden.md / rubric.yaml / grade_*.py / session/trial*.yaml。


## 你负责哪一半

Plan 立账，Solve 结账。

- **你交账本**：哪些行为面要测（Target）、每个面按什么切（Dimension 的 partition）、哪些门会整体关断（Guard）、以及**哪些维度组合明显冲突**（L2 exclusions）。
- **Solve 逐格求解**：账本上每一格到底可不可达、用什么列值构造、行怎么落表。

每级的 case 数由引擎从你的 IR 机械展开，你不用算、也不用写。你只要让 IR 本身正确。

L2 是这个 Target 各 Dimension 的**全交叉**。你的分析价值就落在 exclusions 上：全交叉里被你判定为「不可能同时成立」的格子，写成 exclusion 并给出理由，Solve 就不必再逐个证明。

exclusions 要落在两端之间：

- **空 exclusions** = 交出去一个裸笛卡尔积 = 这份 plan 没做分析。
- **排空全部格子** = 把账本清成 0，Solve 无事可做 = 排除过头了。

只排除**确实不可能**同时成立的组合；判不准的留在账本里，那正是 Solve 要求解的部分。

**全交叉的规模由引擎承担，不构成你少建维的理由。** 维要按实现里真实的分岔数量建齐；名义格子数大是正常的，收敛靠 exclusions 完成。为了让数字小而合并或省掉一个真实分岔，等于把覆盖缺口伪装成了收敛。

## 步骤

1. **读 init**：筛出 `confidence: confirmed` 且 `control.status: active` 的列 —— 只有这些列能进 `cuts` / `eq` / Guard。`unresolved` + `active` 的列不用手写进产物，引擎会生成 `untestable`。

2. **读 packet，Grep 改动文件**：找本次新增的 helper 与新出现的 `{name} =` 赋值。这是 Target 的候选来源。

3. **定位写点**：对候选字段用 `uo_query` 查写点。四种查法 —— 不带 pattern 拿索引；`pattern=<标识符>` 拿符号卡片；`pattern=Dim=<名>` 或 `pattern=<名>=<值>` 拿维度域与模板覆盖；拿到卡片后用 `file` + `line` 精读。`count: 0` 表示图上没有，以 packet 里的实际赋值为准，继续读源码。

4. **写路径条件**：从函数入口走到写点，沿途每个 `if (...) return` 取否定，加上写点前必须成立的合取。**离写点最近那个 if 的正向条件往往正好是早退条件**，要的是整条路径，不是最后一跳。

5. **分盘**：把路径条件的每一项按下面的判据放进一个格子。

6. **枚举 host 局部量**：把写点所在函数、以及它调用的新 helper 里每个 `{name} =` 局部赋值列出来，每个都建一个 probe Dimension。有赋值就能观测。

7. **定 oracle**：先判一句话 —— **本次改动会不会改变累加/归约的次序？** 调度、分块、切核、轮次这类改动都会（同样的数学，不同的相加顺序）。会改变次序，就必须给出能验证「逐位一致」的判据，也就是拿输出的校验和/哈希去比：精度阈值比对放得过宽，恰好会漏掉重排引入的位级偏差，而「结果应当不变」正是这类改动最需要守住的性质。只有确实不碰数值通路的改动（纯字段透传、日志一类）才写 `oracle: []`。

8. **做 L2 互斥分析**：把同一 Target 的 Dimension 两两过一遍，问「这两个维度的某两格能同时成立吗」。不能的写成 exclusion。

9. **交卷前机械核对**（不要 Write、不要跑脚本，用眼睛对集合）：
   - 每个维：`cuts` 只列本维真正在切的字段（通常 1 个；比率最多 2 个）。probe/replay 维的 `cuts` 写 `probe.{name}` / `replay.{field}`，arms 只给该字段互补取值。
   - 每个维 ≥2 个 arm，两格比较值必须不同。
   - 谓词里出现的 case 列用 `eq: {Col: val}` 写进 **arms**，不要另写 `{op, field, value}`。
   - 每一条 L1：两个维的 `cuts` 里 `case.*` 求交必须为空。先问四个格子是否都能打到 Target；入口开关维 × 只在该入口才生效的比率维，以及入口开关维 × 该入口内部 Safe/Ok probe 维，禁止做成 L1，改 exclusions。
   - Target 若是多值落盘，必须有维 `cuts: replay.{field}` 且每个值一个 arm。
   - Target 按优先级：落盘字段 → 仅兄弟也会写成同样 expected 时才用 helper 局部量。Safe/Ok 当 Target 就是跳级。
   - 入口枚举：每个仍能命中的取值必须有 Dimension 见证；只有「无论其它列怎么取都 MISS」的取值才 Guard。早退若是多列合取，不要把其中一列的某一个枚举单独写成 Guard。
   - `requirement` 点名 packet 符号与路径条件；`environment` 有正整数 `aicNum`、`coreNum`。
   - Target 的观测字段不要再开一维切 0/1（off 格打不到 expected）。另开一维切 helper 内部 `probe.*`（取模、升级、合取开关），不要拿 case 列去顶替。
   - 一列只由一个维的 `cuts` 来切；不要把同一对叶子列拆成三个维再做 L1。同一列出现在两个维的 `cuts` 里，这两维禁止做成 L1。
   - `reason` 必须加双引号。exclusions 用两行写法（`partitions:` 映射 + `reason:`），不要把带逗号的 reason 塞进 `{D-a: p-x, reason: ...}` 流式映射。

10. **交卷**：最终消息正文就是 `tg-plan-fill/v1` YAML 全文。

## 分盘判据

对每个路径条件项，做**取反测试**：把它取反，Target 的 expected 还能被别的析取支打到吗？

| 取反后 | 归属 | 形态 |
| --- | --- | --- |
| 仍能打到 | **Dimension** | 两格都是可达 ON，切的是实现里的两条臂 |
| 再也打不到 | **Guard** | 关断整个 Target，`hit` 翻回可达 |
| 恒成立（所有命中行都满足的派生等式） | `constraints` | 默认 `[]`，确有才写 |
| 平台/UT 常量 | `environment` | 整数，指得出 file:line |
| 三层都观测不到 | 不写 | 引擎从 init unresolved 列生成 `untestable` |

同一层 `||` 的两支放进**同一个** Dimension 的两格（互斥 ON）。不同层 `||`、不同 helper 才各自成维。

多值字段（内部比较选出 1/2/3…）：`target` 写 `field: replay.{field}` 和 `in: [1, 2, 3]`，另建一维 `cuts: replay.{field}`，每个值一个 `eq` arm。

**合取早退不要整取值升 Guard。** 写点前 `if (A && B && C) return;` 取反是 ¬A ∨ ¬B ∨ ¬C，每一支仍可能走到写点。把 A 对应列的某个取值写成 Guard，等于假装那一取值永远走不到，会漏掉靠 ¬B / ¬C 命中的行。该列所有仍能命中的取值进 Dimension；只有「无论其它列怎么取都打不到 Target」的取值才进 Guard。

**只杀一条 `||` 支的条件，不要和切「走哪条支」的维做 L1。** 那种配出来是死格，写成 L2 exclusion。推而广之：**入口开关维**（切 0/1 是否进入本次 helper）的 L1 搭档只能是另一条入口条件。不要和该入口内部的 Safe/Ok probe 维配对，也不要和只在该入口才生效的比率维配对（入口开 × 比率对面常常杀整本次模板，这一格打不到 Target）。内部互斥全部写成 L2 exclusion。交卷前对每条 L1 问：四个格子是否都能打到 Target？有一格不能就删这条 L1。

**决定能否进入本次 helper 的分类列，所有仍能命中的取值都要有 Dimension arm。** 不能只在 Guard 里关掉几个失败值、HIT 取值却不出现在任何格子里。本次改动放宽或收紧的那条比较，其叶子列必须进 Dimension 两格（序列是否相等、窗口是否覆盖、形状是否过线，都要追到那两列，不能只观测派生 bool）。

**Target 选字段按这个优先级，不要跳级：**

1. packet 里这次新写入、之后被调用方或 kernel 消费的 **tiling 落盘字段** → `replay.{field}`，`expected` 是行为成立的那个标量。
2. 仅当**同一个**落盘字段在未改动的兄弟路径也会被写成这个 expected 时，才下沉到本次 helper 内部第一个有辨识度的 `{name} =`。落盘只是把 helper 返回值乘公共量、Target 却写成 `gt 0`，等于测「有人写过正数」，测不到本次选择结果。
3. Helper 的 bool 返回值、Safe、Ok、短路标志 **永远是 Dimension**，即使你把它写成 `eq 1`。`probe.{safe|ok|flag}` 当 Target 就是跳级。

不要给 Target 发明别名。`in [0, 1]` 也是把 Dimension 误写成 Target。若 Target 用 `in: [1, 2, 3]`，必须另有一个 Dimension，`cuts` 指向该字段、每个值一个 `eq` arm。

## 观测面阶梯

按这个顺序选观测点，能上一层就不要下沉：

```
replay.{tiling_field}      落盘的 tiling 字段，直接回读
  ↓ 图上没有
probe.{host_name}          host 局部量，源码里有 `{name} =` 就能插探针观测
  ↓ 没有赋值
case.{column}              测试表列，构造时直接给定
  ↓ 都不行
untestable                 点名缺的列或真正的不可观测量
```

**有 `{name} =` 赋值的 host 局部量都是可观测的** —— 探针会自动插桩重编。「值算不出来」是不可预测，不是不可观测：覆盖靠跑完回读贴标签，不靠事前预测。

哪些局部量要开 probe Dimension：**被分支消费、且能在 HIT 行上独立切出两臂的才开**。被 `if` 判断的、参与 min/max 或大小比较的、以及作为这些判据**输入**的中间量，若改某一列就能在 HIT 行上看到 0 和 1，就开维。看着像纯算术的量（计数、轮次、每批列数一类）只要喂给了上面任何一个比较，它就是分支判据的一部分。

不要开维的：只在某一臂才赋值的局部 bool；HIT 路径上恒为真、假臂并不命中 Target 的 Ok/Better 一类合取开关；只改幅度、控制流相同的两档取值。这些写进 `requirement` 即可。真正无分支后果的量（只用于填日志、或算完没人读）也不开。

若某个 `replay` 字段在兄弟路径也会被写成 Target 的 expected，Target 才下沉到本次 helper 的 `probe.{name}`。Helper 的 Safe/Ok 返回值仍开成 Dimension，不要顶替 Target。

## Dimension 要切在实现的分岔上

每个 Dimension 对应写点里一个真实分岔：`if` / 早退 / min-max / 多值选择 / helper 返回值。判定点的数量应当和 arm 的数量相称 —— 判定点远多于 arm，说明漏了析取支或 helper。

一个 Dimension 的所有 arm 切在**同一组 `cuts` 字段**上。`cuts` 只列本维真正在切的字段（通常 1 个；比率最多 2 个）。probe/replay 维的 `cuts` 写该字段，arms 只给互补取值。

**两格必须是控制流上的两条臂，不能是同一臂的两个幅度。** `N=2` 与 `N=4` 若走的是同一个 `if`，删掉这个维；对面那条永远走不到写点的臂（比率另一侧、其它布局）升 Guard。

**路径条件里出现的每个 case 列，都要落进某一个 Dimension 的 `cuts`——且只落进那一个。** 只写进 `extra_controls` 不算覆盖。一列出现在两个维的 cuts 里，L1 就会字段相交。门禁是多列合取时，每个参与列各自成维，不要折进同一个 `eq` 映射，除非这两列共同定义同一条臂（比率）。

**入口门有多个仍能命中的取值时，每个都要有 arm 见证。** 做法是把该列在 init `domains` 里的取值逐个过一遍，对每个取值判断「它能否在早退被否定的前提下命中」。早退是合取条件时，取反早退所需的那一侧仍然可达，那里的取值属于这一维的格子，不是 Guard。

**miss 集是补集时，Guard 写 `op: ne`。** 「除了布局 X 都走不到」写成 `{field: {col}, op: ne, value: X, hit: X}`，不要 `eq` 到某一个其它枚举值。比率杀整不要做成 Dimension 的 off 格：参与比率的列进 Guard；`requirement` 必须抄源码里**失败侧**的比较（`==` / `<=` 那一侧），只写命中侧不够。

**入口门是派生分类量时，要追到叶子列。** 分类量自己可以做 probe 维，但**决定它的那些叶子列同样要进某个 Dimension 的 cuts/arms**。

## L2 互斥分析

全交叉里排除一格，要能说出它为什么不可能。常见来源：

- **实现互斥**：两条臂由同一个开关路由，开了 A 就走不到 B。
- **形状/布局互斥**：某个布局下另一维的某个取值无从构造。
- **环境互斥**：给定平台常量，该组合的前置算不出来。
- **被 Guard 覆盖**：某格本身已使 Target 整体 MISS。

写法是给出具体的 partition 组合 —— 声明的是「这两格不能同时成立」：

```yaml
exclusions:
  - {D-{x}: p-{a}, D-{y}: p-{b}, reason: "{why_impossible}"}
```

一条 exclusion 至少点名 2 个维度、必须带 reason。判不准的不要写进来 —— 留给 Solve 求解。

某维只在另一维的部分格子上有定义时，**不要把该维的每一个 partition 都对那一格排除一遍** —— 那等于把那一格从账本里删掉；再对对称方向做同样的事， leftover 就会变成 0。只排除「这两格不能同时为真」的一对；交卷前必须能指出一个每维各取一格、你认为走得到写点的具体组合。

## 写 fill YAML 时

只填内容。**不要**写 `{op: eq, field: case.X, value: n}` 流式谓词，不要写 `coverage.L0` / `L2.mode` / `L3`、`untestable`、`classifier`、`controls`。引擎会展开成 `tg-plan/v3`。

`reason` 一律加双引号。以 `!`、`>`、`:`、`*` 开头的未加引号字符串会被 YAML 当成 tag / 锚点，整份解析失败。

`environment` 至少包含 `aicNum` 和 `coreNum`，都是从环境事实或源码读出的**正整数**。

默认 **1 个 Target**（`target:` 一个映射）。不要拆成两个 Target。

Guard 的 `hit` 是翻回可达的列值，引擎写成 `negate_hint`。

已经判定为 Guard 的杀整条件，不要再给它一个 Dimension 的 off 格。

不要读 `.ascendc-pilot/**/tg/plan.md`：那是上一轮产物，不是本次输入。

填空语法见 `references/coverage-planning.md`。
</method>

<output>
最终消息正文就是 `schema: tg-plan-fill/v1` YAML 全文。Host 展开成 v3 后只读最终消息。
</output>
