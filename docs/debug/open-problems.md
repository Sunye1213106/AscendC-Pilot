# 未决问题（open problems）

## uo-update key 链（stub）

新分层 KB 尚未提供与旧 `escalate_keys` / `input_derivable` 等价的权威缺口清单。  
因此 `key_triage` / `key_resolution` / `confidence_review` 在 specs 中改为**确定性 stub**，写出 `not_applicable` / auto-accept 产物，**禁止**为它们复活 `understand-operator-old`。

后续：在稳定 ID + `quality.yaml` / gaps 合同上重写 LLM 粗分与闭合。

## KeyField 三重覆盖

不宣称 KeyField / expression / 派生三重全覆盖已达成。进度见 [handoff.md](./handoff.md) 与 [fag/](../fag/)。

## 19 维精确闭合（FAG）

**CLOSED 14/19，free_vars 6**（度量：`python scripts/_probe_derive.py`）。

**静态解析缺陷已见底**：`array_subscript`、`UNMAPPED_CALL`（`.second`）、`UNMAPPED_SYMBOL` 三类全部归零。剩余 6 个自由变量**全是具名 `LOOP_ELEMENT`**，没有匿名 `VAR_UNDECIDED_*`：

| 形态 | surface | 源码 | 卡住的字段 |
| --- | --- | --- | --- |
| 元素 | `invalidS1Array[j]` ×2（两个 scope） | `normal_regbase.cpp:1546`、`varlen_regbase.cpp:897` | 全部 5 个 |
| 元素 | `parseInfo[(s2Outer(fBaseParams) - 1)][LENGTH_IDX]` | `normal_regbase.cpp:1558` | SplitAxis, IsBn2MultiBlk |
| 摘要 | `size(syncRounds)`、`size(syncRoundRanges)` | `varlen_regbase.cpp:716` | SplitAxis |
| 摘要 | `back(slicePrefix1)` | `varlen_regbase.cpp:171` | SplitAxis |

剩余工作只剩一类：**循环出口摘要 / 量化推理**。见下节，它们全部由输入决定，不该出判断题。

每桩掉一层都要重新量一次分布 —— 整条守卫塌缩会掩盖它后面的阻塞点。而且**不能只看 `free_vars`**：本轮两次遇到这个数骗人（一次是伪区分导致假涨，一次是救回约束导致真涨），判据见 [handoff.md](./handoff.md) 末尾的度量清单。

### `.second` 的结论：不是解析 bug，是漏了近似（已修）

`s1ValidIdx[i].second` 的 IR 是 `Call("field:second", (Select(...),))`，外层是 `Call`，因此绕过了三处只认裸 `Select` 的 cut point，掉进文本路径被判 `UNMAPPED_CALL`。

**值得记下的是错误的修法**：曾试图在 `PredicateNormalizer._leaf` 绕到 `resolve_call` 的 `field:` 分支（`source_resolver.py:439-456`）。零位移 —— 那个分支内部仍是文本路径，而 `s1ValidIdx` 是循环内 local `vector<pair>`，本来就没有输入根可继承。**"解析不出来"和"不该被解析出来"是两件事**，这里是后者：正确落点在 cut point，不在 resolver。已撤除该改动。

### 展开后的下标不能用作 identity（已修，本轮最值得记的一条）

`_container_of`（`derive_key_fields.py:1803-1804`）会剥掉**所有**嵌套下标（它答的是"这是哪个容器"，输入根在基名上），而 `_loop_element_var` 的 surface 只取最内层 index。于是不同元素拿到同一变量：`calculatedBlockInfo[b][0][SUM_ALL]`（`varlen_regbase.cpp:991`）与 `[b-1][0][SUM_ALL]`（`:997`）、`parseInfo[i][LENGTH_IDX]`（`normal_regbase.cpp:1529`）与 `[i-1][LENGTH_IDX]`（`:1531`）。

**风险方向和一般过近似相反**：合并两个不同未知量等于断言它们相等，约束**变强**，可能**误杀合法 key**。它们是前缀和、相邻项恒不等，所以这是假等式而非过近似。

**第一次修法是错的，记下来避免重走。** 只把 surface 换成完整下标链，`free_vars` 从 6 暴涨到 21（`parseInfo` 一个容器 11 个变量）。原因是展开后的下标已经不是下标：

```
parseInfo[let $1 = (((((True && True) && True) && True) && True) ? SetSparseParams(context_, fBaseParams) : 0) …
```

外层 `i` 被内联成含守卫与 `SetSparseParams(...)` 的巨型表达式，同一源码读取点在不同展开路径上形状不同，被拆成源码里并不存在的十几个变量。**过粗换成了过细。**

根本解法：下标**不参与跨函数深展开**（`_expand` → `_expand_surface`）。依据是一个逐处核实过的事实 —— **没有任何路径消费下标的值**：`Select` 在归一化时被 `_element_or_cut` 整体替换，index 只用于渲染与 identity。既然值从不使用，展开它没有收益，只带来路径敏感噪声。

浅展开与完整下标链**必须一起用**：只浅展开则 `[i][LENGTH_IDX]` 与 `[i-1][LENGTH_IDX]` 仍撞在最内层；只用完整链则是上面的伪区分。

结果：`free_vars` 6→5、`max_chars` 173K→80K、耗时 27.5s→11.6s、`implicit_zero` 215→211（那 4 处是为求下标值而做的零假设，值既然不用，假设本就多余），且各字段 `input_roots` / `value_leaves` **完全不变**（可确认没丢约束）。

**为什么 `invalidS1Array[j]` 一直是干净的**：`j` 的所有定义都在 `for`/`while` 头下，`_loop_scoped_only`（`:788-797`）判 true，`_expand_name` 直接返回 leaf；`i` 有 unguarded init 或可用守卫，走了 `_chain` 全量替换。

### 容器摘要也需要 cut（已修）

`size()` / `back()` 走 `_container_reduction`，它只能按"填充容器的输入"命名摘要；`syncRounds` / `slicePrefix1` 是循环内构造的局部容器，没有这种根，返回 `None` 且调用点无兜底 → 整条守卫塌缩。这是同一个病的第三个变体（裸下标 → 元素 slot → 容器摘要），修法对称：`_loop_reduction_var`，identity `(scope, container, kind)`。三条 cut 共用 `_loop_local_var` 记账。

**这一步让 `free_vars` 从 5 涨回 6，而这是对的**：`SplitAxis` 的变量总数同时 34→39，即多 5 个变量参与约束而只多 1 个自由变量 —— 那 4 个是原本被塌缩吞掉的已解析输入约束（`CORE_LIST_NUM` 比较等）。用 1 个自由变量换回 4 个真实约束。

### LOOP_ELEMENT 的语义边界

`invalidS1Array[j]` 这类量，循环建立的是一个**量化命题**，本分析不计算量化命题。故 `PRESORT_LOOP_ELEMENT` **不在** `NON_ESCALATING` 里。

**修正一处此前的判断**（源码调查已核实，见下）：先前把这些说成"真实分析边界、唯一正当的 LLM 面"，**不准确**。它们的取值其实**完全由算子输入决定** —— 填充与读取路径里都没有 `coreIdx` 之类的 host 侧贪心装箱状态：

| 变量 | 依据 |
| --- | --- |
| `invalidS1Array` | 只依赖 s1/s2 outer、token、sparse 几何（`normal_regbase.cpp:1511-1549`） |
| `parseInfo` | 同上（`:1512-1531`）；分核用均匀 `blockFactor=(fusedOuter+aicNum-1)/aicNum`，非贪心 |
| `syncRounds` / `slicePrefix1` | 由 sparse 几何与核数决定的循环出口计数 / 末项 |

同文件里确实有 `coreIdx` 贪心装箱（`CaclePerCoreBlockInfoBn2`，`varlen_regbase.cpp:921-949`），但那条路径与上面的量分离。

所以缺的**不是信息，是量化推理能力**。以 `invalidS1Array` 为例，语义可以闭式写出来：

```
invalidS1Array[j] = ∃i. (parseInfo[i].begin ≤ j < parseInfo[i].end)
isInvalidRow      = ∃j. ¬invalidS1Array[j]
                  = 「存在一个 s1 outer 行不被任何 s2 列区间覆盖」
```

这是一个**区间覆盖**判定，由 sparse 几何（token / cvS2Inner / s1Outer / s2Outer）完全确定，原则上可推出闭式或用量词编码给 Z3。**正当出路是循环出口摘要 / 区间覆盖闭式，而不是出 LLM 判断题。** 判断题只应用在源码真的没说清语义的地方。

另两个形态各自需要的东西不同：`parseInfo[(s2Outer-1)][LENGTH_IDX]` 是**前缀和末项**（即有效基本块总数），这类量通常可闭式求和；`size(syncRounds)` / `back(slicePrefix1)` 需要循环出口的计数 / 末元素摘要。

变量 identity 是 `(scope, container, 完整下标链, slot)`，摘要则是 `(scope, container, kind)`：同函数同一读取点共用一个变量（守卫不能被两种矛盾方式满足），不同函数的同名容器不被静默等同。`invalidS1Array` 因此是 2 个变量（`GetParseS1S2OuterInfo` 与 `FillBlockInfoLoadBalanceForBn2` 各一个）。

`slot` 与**完整下标链**进 identity 都是 soundness 要求，不是可选项：`.first` 是索引、`.second` 是上界，`[i]` 与 `[i-1]` 是前缀和的相邻项 —— 任一处共用变量都会让求解器断言两个恒不等的量相等。

## diag_align.py 的判据已陈旧

`python .probe_cache/diag_align.py` 当前报 `fields_fail=2 ['IsTnd','IsNEqual'] | inv_fail=2 ['I4','I5']`。**这 4 条都不是回归**：

- `IsTnd` / `IsNEqual`：脚本用自带的简化 `value_leaves`（`diag_align.py:137-146`），没有合并 `smt_value_leaves`。裸布尔字段展开后没有 `Ite`，在它那里恒为 0 个叶子，于是撞上 `MIN_LEAVES=2`。probe 对同两个字段报的是 `leaves=2`。
- `I4` / `I5`：在 live Expr 树上按子串找 `hasRope` / `QUERY_ROPE`，而树里的符号是 `queryRope` 等，永远不命中。

修它需要让 diag 的叶子口径与 `derive()` 对齐（`derive_key_fields.py` 里 `leaves |= smt_value_leaves(out.value_expr)`），并把 I4/I5 的 token 表对齐真实符号名。在此之前**不要把 handoff 里"期望 fields_fail=0"当成判据**。
