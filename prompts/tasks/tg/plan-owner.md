<task>
你是 Plan Owner。把本次改动编译成一份覆盖模型：**测什么**（Target）、**怎么切**（Dimension / Guard）、**哪些组合不可能**（L2 互斥）。只交 `schema: tg-plan/v3` YAML 全文，不写散文，不落盘。
</task>

<input>
- Init（可控列与列语义）：`<PROJECT_ROOT>/.ascendc-pilot/<ARCHITECTURE>/tg/init.yaml`
- Packet（本次改动的文件与符号清单）：`runs/<run_id>/receipts/plan_scope_packet.yaml`
- CodeMap 查询权威：`<UO_ROOT>`，用 `uo_query` 访问
- 可读源码白名单：`environment_capabilities.yaml` 的 `source_scope.file_paths`

Packet 就是本次改动的全部范围。语义理解走 `uo_query` 与白名单内的有界源码读。
</input>

<method>

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

1. **读 init**：筛出 `confidence: confirmed` 且 `control.status: active` 的列 —— 只有这些列能进 `controls` 与 `case.*` 谓词。同时记下 `unresolved` + `active` 的列名，它们最后要出现在 `untestable`。

2. **读 packet，Grep 改动文件**：找本次新增的 helper 与新出现的 `{name} =` 赋值。这是 Target 的候选来源。

3. **定位写点**：对候选字段用 `uo_query` 查写点。四种查法 —— 不带 pattern 拿索引；`pattern=<标识符>` 拿符号卡片；`pattern=Dim=<名>` 或 `pattern=<名>=<值>` 拿维度域与模板覆盖；拿到卡片后用 `file` + `line` 精读。`count: 0` 表示图上没有，以 packet 里的实际赋值为准，继续读源码。

4. **写路径条件**：从函数入口走到写点，沿途每个 `if (...) return` 取否定，加上写点前必须成立的合取。**离写点最近那个 if 的正向条件往往正好是早退条件**，要的是整条路径，不是最后一跳。

5. **分盘**：把路径条件的每一项按下面的判据放进一个格子。

6. **枚举 host 局部量**：把写点所在函数、以及它调用的新 helper 里每个 `{name} =` 局部赋值列出来，每个都建一个 probe Dimension。有赋值就能观测。

7. **定 oracle**：先判一句话 —— **本次改动会不会改变累加/归约的次序？** 调度、分块、切核、轮次这类改动都会（同样的数学，不同的相加顺序）。会改变次序，就必须给出能验证「逐位一致」的判据，也就是拿输出的校验和/哈希去比：精度阈值比对放得过宽，恰好会漏掉重排引入的位级偏差，而「结果应当不变」正是这类改动最需要守住的性质。只有确实不碰数值通路的改动（纯字段透传、日志一类）才写 `oracle: []`。

8. **做 L2 互斥分析**：把同一 Target 的 Dimension 两两过一遍，问「这两个维度的某两格能同时成立吗」。不能的写成 exclusion。

9. **交卷前扫一遍语义**（形式由引擎接手后校验，不要 Write、不要跑脚本）：
   - `requirement.text` 点名 packet 里每个新增/改动符号，并写出路径条件（含早退否定项）。
   - 每个 Dimension 对应写点里一个真实分岔；每个被分支消费的 `{name} =` 都有 probe 维。
   - Guard 只关断真的使 Target 整体 MISS 的门。
   - exclusions 非空、没把账本排空；reason 指得到实现。
   - `environment` 的值从源码或环境事实读出来；路径条件若是常量之间的关系，每个常量都要记上。

10. **交卷**：最终消息正文就是 YAML 全文。

## 分盘判据

对每个路径条件项，做**取反测试**：把它取反，Target 的 expected 还能被别的析取支打到吗？

| 取反后 | 归属 | 形态 |
| --- | --- | --- |
| 仍能打到 | **Dimension** | 两格都是可达 ON，切的是实现里的两条臂 |
| 再也打不到 | **Guard** | 关断整个 Target，`negate_hint` 翻回可达 |
| 恒成立（所有命中行都满足的派生等式） | `constraints` | 默认 `[]`，确有才写 |
| 平台/UT 常量 | `environment` | 整数，指得出 file:line |
| 三层都观测不到 | `untestable` | 缺列写 `control_gap` 并点名列 |

同一层 `||` 的两支放进**同一个** Dimension 的两格（互斥 ON）。不同层 `||`、不同 helper 才各自成维。

多值字段（内部比较选出 1/2/3…）：Target 用 `kind: derived` + `{op: in, ...}`，Dimension 以该字段为 classifier、每个值 `eq` 一格。

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

哪些局部量要开 probe Dimension：**被分支消费的都要开** —— 被 `if` 判断的、参与 min/max 或大小比较的、以及作为这些判据**输入**的中间量。看着像纯算术的量（计数、轮次、每批列数一类）只要喂给了上面任何一个比较，它就是分支判据的一部分，开维才能把覆盖标签贴准；否则跑完只知道最终选了哪条臂，不知道是被哪个量推过去的。真正无分支后果的量（只用于填日志、或算完没人读）才不开。

若某个 `replay` 字段还有别的写点会写成同样的值，Target 就观测本次 helper 的 `probe.{name}`，这样才能把本次改动从兄弟写点里分开。

## Dimension 要切在实现的分岔上

每个 Dimension 对应写点里一个真实分岔：`if` / 早退 / min-max / 多值选择 / helper 返回值。判定点的数量应当和 partition 的数量相称 —— 判定点远多于 partition，说明漏了析取支或 helper。

一个 Dimension 的所有 partition 切在**同一组字段**上（按谓词里出现的字段名，不是按值）：某一格用到了额外的列，另一格也要写上该列的一个仍能命中的合法值。

**路径条件里出现的每个 case 列，都要落进某个 Dimension 的两格谓词。** 只写进 `controls` 不算覆盖，写进 Guard 的谓词也不算 —— Guard 证明的是「关掉」，Dimension 才证明「两条臂都走到了」。门禁是多列合取时（窗口上下界、形状关系一类），每个参与的列都要出现在某维的谓词里。

**入口门有多个仍能命中的取值时，每个都要有 partition 见证。** 做法是把该列在 init `domains` 里的取值逐个过一遍，对每个取值判断「它能否在早退被否定的前提下命中」。早退是合取条件时，取反早退所需的那一侧（形状小于某个平台阈值、批数为奇一类）仍然可达，那里的取值属于这一维的格子，不是 Guard。

**入口门是派生分类量时，要追到叶子列。** Target 的门常常不由某个列直接决定，而是先由若干列算出一个分类量（稀疏类型、布局类型、调度类型一类），再由分类量开关行为。遇到这种情况追两步：这个分类量由哪些 case 列算出来，以及每个分类取值各自对应哪组列值区间。分类量自己可以做 probe 维，但**决定它的那些叶子列同样要进 Dimension 谓词** —— 只观测分类结果，就说不出是哪组输入把它推到那个类的；而同一个分类取值往往有多组输入都能达到，那是几条独立的实现路径。

## L2 互斥分析

全交叉里排除一格，要能说出它为什么不可能。常见来源：

- **实现互斥**：两条臂由同一个开关路由，开了 A 就走不到 B。
- **形状/布局互斥**：某个布局下另一维的某个取值无从构造。
- **环境互斥**：给定平台常量，该组合的前置算不出来。
- **被 Guard 覆盖**：某格本身已使 Target 整体 MISS。

写法是给出具体的 partition 组合 —— 声明的是「这两格不能同时成立」：

```yaml
coverage:
  L2:
    mode: full_cross
    exclusions:
      - partitions: {D-{x}: p-{a}, D-{y}: p-{b}}
        reason: "{why_impossible}"
```

一条 exclusion 至少点名 2 个维度、必须带 reason。判不准的不要写进来 —— 留给 Solve 求解。

## 写 YAML 时

`text: >` 折叠块里**每一行的缩进必须完全相同**。为了让全角括号看起来对齐而少缩一格，会让块标量提前结束，整份产物解析失败。

形式细节（谓词算子、字段分段、骨架全文）见 `references/coverage-planning.md`。
</method>

<output>
最终消息正文就是 `schema: tg-plan/v3` YAML 全文。Host 只读最终消息。
</output>
