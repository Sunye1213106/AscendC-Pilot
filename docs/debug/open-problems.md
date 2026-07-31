# 未决问题（open problems）

## uo-update key 链（stub）

新分层 KB 尚未提供与旧 `escalate_keys` / `input_derivable` 等价的权威缺口清单。  
因此 `key_triage` / `key_resolution` / `confidence_review` 在 specs 中改为**确定性 stub**，写出 `not_applicable` / auto-accept 产物，**禁止**为它们复活 `understand-operator-old`。

后续：在稳定 ID + `quality.yaml` / gaps 合同上重写 LLM 粗分与闭合。

## KeyField 三重覆盖

不宣称 KeyField / expression / 派生三重全覆盖已达成。进度见 [handoff.md](./handoff.md) 与 [fag/](../fag/)。

## 19 维精确闭合（FAG）

**CLOSED 14/19，INPUT_DERIVABLE 12/19，free_vars 6，implicit_zero 133（exact 字段下 0）**（度量：`python scripts/_probe_derive.py`）。

**下游该读的是 INPUT_DERIVABLE 而不是 CLOSED。** `exactness` 只回答表达式闭不闭合；`IsTnd` / `IsNEqual` 判 `exact` 且零自由变量，但根落在 `TILING_DATA` 上，测试用例无从设置。（`IsPse` / `IsAttenMask` 原本同病，P1.2 已展开到 `INPUT_SHAPE` + `OPTIONAL_INPUT_PRESENCE`；`IsTnd` 的写自我路由，展开不健全，拒做。）详见 [handoff.md](./handoff.md) 的「口径变更（二）」。

~~**静态解析缺陷已见底**~~ —— **勿再引用**。`array_subscript`、`UNMAPPED_CALL`（`.second`）、`UNMAPPED_SYMBOL` 三类确实归零，但那只说明**这三类**没了。至少三处确定性缺陷仍在：

| 缺陷 | 证据 | 性质 |
| --- | --- | --- |
| `back(slicePrefix1)` 可静态闭合 | `slicePrefix1` 全仓库仅 4 处，`push_back(R1)` 在 `varlen_regbase.cpp:166`、`.back()` 在 171，中间只隔一句读 `prefix0`，无回边无分支 | 容器 SSA，不需量词 |
| `IsTnd` 丢掉输入根 | `_chase_writes` 遇到多个 guarded 常量写入直接判 `TILING_DATA`（注释自己写明了这点） | 应折成 `Ite` 链继续追到 layout attribute |
| ~~211 处隐式零默认~~ **已修** → 133，exact 字段下 0 处 | 穷尽 cascade 走 `_paths_are_covered` 判掉（213→159），再读 `FIELD_DECL` 类内初值（159→133）；`s1/s2TemplateType`=128、`dTemplateType`=64 三处**假设为假**已纠正 | 穷尽性是语法性质不必上求解器；剩余 133 处全在 overapproximated 字段下 |

注意 `back()` 闭合**大概率不降 `free_vars`**：`R1` 依赖 `deterPrefixData.prefix1.back()` 与 `mnMax`，两者都由 `CalcleTNDBandDeterPrefix` 的 `for (i < b)` 循环累加/取 max 得出。收益是让 blocker 形态诚实。

剩余 6 个自由变量**全是具名 `LOOP_ELEMENT`**，没有匿名 `VAR_UNDECIDED_*`：

| 形态 | surface | 源码 | 卡住的字段 |
| --- | --- | --- | --- |
| 元素 | `invalidS1Array[j]` ×2（两个 scope） | `normal_regbase.cpp:1546`、`varlen_regbase.cpp:897` | 全部 5 个 |
| 元素 | `parseInfo[(s2Outer(fBaseParams) - 1)][LENGTH_IDX]` | `normal_regbase.cpp:1558` | SplitAxis, IsBn2MultiBlk |
| 摘要 | `size(syncRounds)`、`size(syncRoundRanges)` | `varlen_regbase.cpp:716` | SplitAxis |
| 摘要 | `back(slicePrefix1)` | `varlen_regbase.cpp:171` | SplitAxis |

消掉这 6 个需要**循环出口摘要 / 量化推理**。见下节，它们全部由输入决定，不该出判断题 —— 现已从 LLM 队列移除。

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

### LOOP_ELEMENT 的语义边界（判断已反转：不再派给 LLM）

`invalidS1Array[j]` 这类量，循环建立的是一个**量化命题**，本分析不计算量化命题。此前据此把 `PRESORT_LOOP_ELEMENT` 排除在 `NON_ESCALATING` 之外，理由是"量化命题算判断题"。**这个理由不成立，已改为归入 `NON_ESCALATING`。**

推翻它的是下面这张表：这 6 个量全部由算子输入决定，源码把怎么算它们写得一清二楚。所以缺的不是**信息**（模型能补的只有信息），而是**推理能力**。一个被问"这个量是不是输入派生的"的模型会答"是" —— 答对了，而表达式一点没变得更可解。更糟的是这个"是"会让 guard 从记录里消失，账面收敛而语义不变。

同时 `gaps.py` 那道二层过滤从「看 reason 文本」改为「看 presort」：reason 说的是归一化**怎么**失败的，与该不该问是两件事。一个 loop element 若失败在 `UNMAPPED_SYMBOL` 上，它带的 reason 是可升级的，旧的 `SCHED_SOFT` 检查照样放它过去。

它们的取值**完全由算子输入决定** —— 填充与读取路径里都没有 `coreIdx` 之类的 host 侧贪心装箱状态：

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

一处必须记住的差异：`invalidS1Array` 的**两个 scope 语义不同** —— Normal 路径（`normal_regbase.cpp:1546`）是整数区间，Varlen 路径（`varlen_regbase.cpp:897`）用 **float** 边界且每 batch `assign` 重建。所以按 scope 分成两个变量不只是保守，是必需的，两者不能共用一套摘要。

另几个形态各自需要的东西不同：

- `parseInfo[(s2Outer-1)][LENGTH_IDX]` 是**前缀和末项**（即有效基本块总数），`Σ max(end_i - begin_i, 0)` 可闭式求和。顺带一条算子缺陷线索：`s2Outer == 0` 时 `parseInfo[-1]` 下溢，arch35 无保护而 arch22 有。
- `size(syncRounds)` / `size(syncRoundRanges)` 是**受限 count-if，不是全 coreId 的计数**：迭代域被 `continue` 过滤，且 Dense 用 `coreId > aicNum - 1`、Band 用 `coreId >= aicNum - 1`（两者不同），只有 `coreId != 0` 才 push。按"对全部 coreId 计数"建模会得到错的上界。
- `back(slicePrefix1)` 走容器 SSA，见本节开头的表，不需要量化。

**循环摘要现在是 K6 判定的头号卡点，不再只是"闭合度"问题。** K6 已接主链（handoff F.13），8705 个合法 key 里 8704 判 `unknown`，唯一原因是 5 个维度（`SplitAxis` / `DeterType` / `IsBn2MultiBlk` / `IsNzOut` / `IsTndSwizzle`）被 `omit`，而 `omit` 的触发点全是未建模的循环归约变量：`m0Max` / `m1Max` / `m2Max`（`CalcleTNDCausalDeterPrefix` 里 `m2Max = std::max(m2Max, …)`）、`s1Inner` / `s2Inner`、`deterTilingSplitMode`、`i` / `j` / `batchIdx` / `comBIdx`、`s1s2TemplateSize.first/.second`、`fBaseParams.sparseType`，共 13 个。

它们**不能**用一个编造的常量顶替：把变量替换成远低于真实范围的数会让 `x < m0Max` 恒假，那是收紧方向，会伪造矛盾。所以只能 `omit` 到摘要做出来为止。顺带一个反直觉的收益 —— `omit` 之后 `Z3Backend` 构造从 37 分钟没跑完变成 **0.2s**，因为最贵的树正是这 5 棵。

变量 identity 是 `(scope, container, 完整下标链, slot)`，摘要则是 `(scope, container, kind)`：同函数同一读取点共用一个变量（守卫不能被两种矛盾方式满足），不同函数的同名容器不被静默等同。`invalidS1Array` 因此是 2 个变量（`GetParseS1S2OuterInfo` 与 `FillBlockInfoLoadBalanceForBn2` 各一个）。

`slot` 与**完整下标链**进 identity 都是 soundness 要求，不是可选项：`.first` 是索引、`.second` 是上界，`[i]` 与 `[i-1]` 是前缀和的相邻项 —— 任一处共用变量都会让求解器断言两个恒不等的量相等。

**identity 里还缺一维：容器是否静止**（已修，见 handoff F.14）。`(scope, container, kind)` 对可变容器不够 —— `prefix1.back()` 在同一函数里的 `push_back` 前后被读，共用一个变量就是断言源码不提供的等式。判据只能建立在 IR 真有的东西上（写点带行号，读点不带）：多个函数写它，或读取点所在函数自己也写它 → 隔离。反例同样真实：`max(actualSeqQlen)` 跨 5 个维度的等式是**对的**，不能一并丢掉。

### 写记录里两个静默缺口（已修，见 handoff F.16）

两条都属于"IR 说的比源码少"，而下游会把残缺的写序列当完整的用。修完之后 `prefix0` 的写序列由 7 条补全为 11 条（4 `replace` + 7 `append`）。

- ~~成员路径上的整容器 `operator=` 被完全丢弃~~。`_record_operator_assign` 的 `path.count(".") < 1` 限制已放开，成员路径记为 `kind="replace"` 的真写。全集实测只有 **14 条**，全部是 `deterPrefixData.{prefix0,prefix1,prefix2,deterPrefix,deterPrefixAlign} = SliceVector(自身, step)` —— 没有 `std::string` 或其他自定义赋值类型的实例。
- ~~`push_back` 的元素冒充容器的定义式~~。元素移入新的 `FuncRecord.appends` / `FuncSummary.appends` 槽，`assigns` 不再被污染（实测"容器的 assigns 条目是元素"从若干条降为 **0**，46 个元素一条不少地保留在新槽里）。

**它们此前为何没有造成错误答案，以及这对 P1.4 意味着什么。** 这 5 个路径全部被 `source_resolver.py:722-729` 的名字白名单短路成 `TILING_DATA` 根，`_chase_field` 因此从不去追它们的写序列 —— 白名单**掩盖**了这两个缺陷。反过来说，**去掉那个白名单（P1.4）会立刻激活它们**。所以顺序是固定的：先让写记录诚实，再动白名单。这也是这两条先于 P1.4 修掉的原因。

~~**还差一项 IR 补强，挂在 P2 前面**：`WalkResult.controls` 没被带进 `HostIR`。~~ **已修（handoff「循环与分支现在是结构化的」）**：`PathCond` 加了结构化 `kind` / `is_decision`，`controls` 带进 `HostIR` 并提供 `loop_at(file, line)` 查归纳变量。原诊断说"退化成 `for(` 字符串前缀匹配"，措辞要修正一半：循环的 `PathCond.text` 本来就是 `clang_walk` 自己合成的 `f"{kind}({cond})"`，producer 与 consumer 同仓，正则是精确匹配而非猜格式；真正的缺口是 `kind` 只存在于文本里、且归纳变量无处安放。

**7 个成员的默认值永远读不到，这是算子侧性质而非工具缺陷。** `fBaseParams.{b,bandIdx,s1Token,s2Token,blockOuter,isSparse,deterSparseType}` 声明处**没有类内初始化器**；对象由 `tiling_templates_registry.h:33` 的 `new (std::nothrow) T(context)` 分配（default-init 而非 zero-init），构造函数体为空且无 mem-initializer，全 `op_host` 树无 `memset` / 整体赋值（已搜索确认 0 命中）。所以它们在首次写之前的值**确实不确定**。`field_decls` 里它们的 `init` 记为 `None` —— 这比"没去读"是更强的结论，但仍不允许发明默认值。这 7 处应重新分类为比"假设为 0"更严重的问题，而不是等着被关掉。

两类在本算子上**没有实例**、但跨算子仍需要的能力（不要为它们在 FAG 上造方案）：

- `shrink`：这棵算子树里没有 `clear` / `pop_back` / `erase` / `resize` / `swap` 调用（已全文搜索确认）。分类逻辑保留，在这里永远不命中。
- **局部引用别名**。原以为是阻塞项，实测不是：host 侧的引用别名全部形如 `auto &qShape = ...GetStorageShape()`，绑定的是 `gert::Shape`，**没有一个绑到可变容器**，也**没有任何经别名的写**（无 `SetDim`，无对别名的再赋值）。`auto &x = expr` 的值追溯本来就由 `fr.locals[x] = expr` 覆盖。所以"经非 const 引用的写记到别名路径上"这个缺陷在 FAG 上无实例。

~~顺带一条不构成不健全但会误分类的：`deterPrefixData` 按名字被写死为 `TILING_DATA` 根。~~ **已修（handoff F.17）**：改为按"字段被 host 写过"这一结构性判据认定聚合体。原诊断有一处偏差 —— `deterPrefixData` 其实**不在** `class_fields` 里（它是 3 个函数的局部变量），`source_resolver.py:722-729` 那条白名单从未命中它；真正生效的硬编码点是 `_PARAMS_DERIVED_RE` 里字面写的 `deterPrefixData`，经 `_chase_field` 的局部 RHS 兜底分支起作用，覆盖 94 条写。

新判据留下一条需要留意的性质：它**依赖写记录存在**。若某算子的 tiling 聚合体字段写全部落在被 `_in_scope` 过滤掉的 TU 里，该符号会降级为 `TILING_DATA_NO_WRITER`（上报为 gap），而不是被假设成 tiling 根。方向保守，但会表现为"本该 closed 的字段变成 gap"。

## 算子侧缺陷线索（需上报算子方，不是本工具的缺陷）

派生的副产物。两条都不能在 UO 里"修"，只能报出来：

- ~~**`OutDType` 值域与 TPL 声明不一致。**~~ **已求证为本工具的假阳性，不要上报算子方。** 详见下节「`domain_violations` 比的是错的东西」。`OutDType = InputDType` 这个派生结论本身正确（`..._tiling_common_regbase.cpp:1180` 就是直接赋值、无映射），错的是拿什么去比。
- **`parseInfo[s2Outer - 1]` 在 `s2Outer == 0` 时下溢。** arch35 无保护，arch22 有。发现于给 `parseInfo[(s2Outer-1)][LENGTH_IDX]` 做前缀和摘要时。
- **varlen 的 `invalidS1Array` 拿 block 下标去比 token 坐标（疑似漏了 `/ s1CvInner`）。** 证据是同构对照：normal 与 varlen 做同一件事——标记哪些 S1 block 落在区间 `[begin, end)` 内——但只有 normal 做了域换算。
  - normal `GetParseS1S2OuterInfo`（`..._normal_regbase.cpp:1515-1525`）：`BEGIN_IDX = leftIntersectionPoint / s1CvInner`，`END_IDX = (min(…, s1) + s1CvInner - 1) / s1CvInner`，溢出分支同样除。`:1538` 用 block 下标 `j` 比较，**同域**。
  - varlen `FillBlockInfoLoadBalanceForBn2`（`..._varlen_regbase.cpp:877-878`）：`acturalS1Begin` / `acturalS1End` 的上限是 `actualS1Len`（token 数），**没有除 `s1CvInner`**；而 `:889` 的 `k` 来自 `invalidS1Array.assign(actualS1Outer, …)`，`actualS1Outer = ceil(actualS1Len / s1CvInner)`，是 block 下标。
  - 同一函数内有反证：`:881` 写着 `acturalBlockInfo[i][j] = acturalS1Num / s1CvInner`，作者清楚两个域要换算。
  - 后果不是精度略差：`s1CvInner > 1` 时 `k < acturalS1End` 几乎恒真（block 下标远小于 token 数），几乎所有 block 被标 true，`:899` 的 `!invalidS1Array[j]` 几乎永不成立。按 `:897` 注释「BN2场景下检查是否无效基本块行，用于清零GM」，这是**漏清零 GM**。
  - 三种可能待算子方确认：该路径上 `s1CvInner` 恒为 1；`acturalS1Begin/End` 在更早处已转 block 域（当前源码看不出）；确实是漏了换算。**UO 侧必须忠实建模 `k >= acturalS1Begin` 原样**，不能替作者补上 `/ s1CvInner` —— 那会把算子 bug 藏进工具里。

## varlen 的 `isInvalidRow` 是顺序赋值，跨 batch 不能折叠成 OR

`FillBlockInfoLoadBalanceForBn2` 的 batch 循环里有两处写 `isInvalidRow`，语义不同：

```cpp
if ((actualS2Outer == 0) != (actualS1Outer == 0)) {   // :853
    fBaseParams.isInvalidCol = (actualS1Outer == 0);
    fBaseParams.isInvalidRow = (actualS2Outer == 0);  // 赋值，可把 true 覆盖回 false
}
// …填掩码…
for (size_t j = 0; j < invalidS1Array.size(); j++) {  // :898
    if (!invalidS1Array[j]) { fBaseParams.isInvalidRow = true; break; }   // 单向置位
}
```

`:855` 是**赋值**而非 `|=`，所以第 `i` 个 batch 能把第 `i-1` 个 batch 在 `:900` 置的 `true` 重置为 `false`。任何把多 batch 摘要成 `initial OR uncovered_0 OR uncovered_1 OR …` 的写法都会得出**相反**的答案，不只是偏松。正确形式是有序 fold：每个 batch 先按 `:853` 的条件做可能的覆盖式赋值，再 OR 上该 batch 的 uncovered。`isInvalidCol` 同理（`:854` 赋值 vs `:886` 置位）。

这条约束对任何未来的循环摘要都成立，与选哪条 IR 路线无关。

## `domain_violations` 比的是错的东西（P0.2 的设计缺陷，唯一已知报例已证伪）

原设计判 `value_leaves ⊆ TPL domain`。**`value_leaves` 是表达式里出现过的字面量集合，不是该维度可达的取值集合** —— 任何 `Ite` 死分支里的常量都必然被计入，同一个值还会以折叠数字（`4`）和未折叠枚举拼写（`DTYPE_ENUM_INDEX_4`）两种形态各算一次。所以它比的是"语法上出现过的常量"对"语义上声明合法的值"，两边不是同一种东西。原先记在这里的"报的是真实冲突的下界"这个说法要撤销：下界性只在"叶子都可达"时成立，而这个前提不成立。

唯一的报例 `OutDType` 已求证为假阳性，证据是决定性的：**8705 个合法 key 里 `InputDType` 只取 0/1/2/3，根本没有 4/5/6**，且 `(InputDType, OutDType)` 严格 `in == out`（3296/3296/2112/1），与 `outDtype = inputDtype` 完全吻合。`ASCENDC_TPL_UINT_DECL(InputDType, …, 0…6)` 是**声明域**，真正的合法集是 65 个 `ASCENDC_TPL_ARGS_SEL` 组的并集，没有一组选用 4/5/6。arch35 host 在 `..._tiling_common_regbase.cpp:1146-1148` 用一个 early return 同时拒掉 FP8_E5M2 / FP8_E4M3FN / **HIFLOAT8**（三者一起，不是分开处理），所以 host 与模板是一致的。

> 顺带纠正一个容易复现的误判：网上/直觉版本的分析会说"HIFP8 先写成 6，再被 `out_dtype` 属性检查改写为 BF16"。arch35 tiling 侧 `fBaseParams.outDtype` **只有 1180 行一处赋值，没有任何重写**；那段 `out_dtype == 1 → BFLOAT16` 的逻辑在 `flash_attention_score_grad_infershape.cpp:141-177`，决定的是输出 tensor 的 dtype，与 tiling key 无关。

正确的判据是求解器问题而非枚举问题：**存在一组满足约束的输入，使该维度取值 `v` 且 `v` ∉ SEL 合法域吗**。K6 那条链（`acp_common` 的 Z3）已具备这个能力，改造应复用它，而不是继续数字面量。改名成 `INTERMEDIATE_DOMAIN_EXCEEDS_TEMPLATE` 之类解决不了问题 —— 现在报的连"中间赋值域"都不是，比中间赋值域还宽。

**另一个独立缺陷（修了上面这条也不会消失）**：`clang_walk.py:1186-1187` 的 `_ERROR_EXIT_RE` 有意丢弃所有错误退出守卫的否定，理由是"取反只是重述『输入合法』，而这已被假设"。这个论证把两类守卫混为一类：`if (shape == nullptr) return FAILED` 是**重述型**（取反无信息），`if (queryType == DT_HIFLOAT8) return FAILED` 是**排除型**（把具体输入值排除出可达域，取反是真实约束）。arch35 有 65 处 `return GRAPH_FAILED` 全按重述型处理，实测后果是 1180 行那个写的 `path_conditions` 为**空**。恢复排除型之前要先量化两类各占多少、以及恢复后表达式膨胀多少 —— 当初抑制的动机是防止一打守卫挂到后面所有代码上，那个顾虑本身是真的。

同一份源码里另有两处"曾支持 HIFP8、后回退"的残留，可作为契约脆弱点的实证报给算子方（不是功能 bug）：`OUTDTYPE_ATTR_IDX = 11`（`..._common_regbase.h:85`）只有定义、零使用；`..._common_regbase.cpp:1155` 的 `if (queryType != ge::DT_HIFLOAT8)` 在 HIFLOAT8 已于 1148 行被拒的前提下**恒真**。

## 具名常量表是扁平的，裸名会互相覆盖

`variable_model._named_constants_from` 把每个枚举成员同时写进 `Enum::MEMBER` 和裸 `MEMBER` 两个键，后扫到的**直接覆盖**先前的裸名。所以裸名的值只在"全仓库该名字唯一"时才可信：实测 `TND` 的裸名是 **4**，而 `LayoutEnum::TND` 是 **3**（4 来自另一个枚举的 `NTD_TND`）。

后果是查裸名会拿到别的枚举的值。K6 侧已按"整组符号一起读或一起编码"回避（见 handoff F.13），但**读裸名的其它调用点仍暴露在这个问题下** —— `lookup_constant` 的兜底就是 `symbol.split("::")[-1]`。要根治得让扁平表在裸名冲突且取值不同时**丢弃**该裸名，而不是留一个赢家。

另一条同类隐患：`registry_capable.parse_enums` 遇到值不是字面量（`DT_FLOAT = ::C_DT_FLOAT`）时求不出值，兜底是**沿用递增计数继续往下数**。枚举一旦有保留空位（`ge::DataType` 在 4 之后跳到 6），从该处起的成员全部发错值，而且不报错。目前没有调用点会扫到这种头（`ge::DataType` 是抄录进 `GE_DATA_TYPE` 的），但**把 CANN 的 `graph/types.h` 加进扫描列表就会踩上**。

## LLM 通道能表达什么

`gap_patch` 的 patch schema 是 `{var_id, op, value}`（`BINDING_OPS` 只有比较与 `in`），所以它**只能表达"某个已知变量与某常量的一条比较"**。这是有意的封闭词表，但也意味着：

- 循环摘要、量词、聚合**无法**由 LLM 补 —— `Σ`、`∃`、count-if 都写不进这个 schema。所以剩余 6 个 `LOOP_ELEMENT` 即使派给模型也接不回来，这是把它们移出 LLM 队列的第二个理由（第一个见上节）。
- 共享 Constraint IR（`acp_common/constraint_ir.py`）同样没有聚合与量词节点：`variables` 是 flat 列表、类型只有 `bool|int|enum`，没有索引变量概念。要支持有界聚合得先引入绑定范围结构，并让 `z3_backend` 的 `_compile_bool` / `_compile_value` 跟着降。

已加的护栏（`apply_bindings_to_derivation` 消元后校验、不落地就回退，见 [handoff.md](./handoff.md) F.12）不依赖 LLM 自律，也不关心替换为什么没生效 —— 所以上面这些表达力缺口现在只会表现为"binding 被拒 + `reverted` 计数上升"，不会再表现为账面收敛。

## diag_align.py 的判据已陈旧

`python .probe_cache/diag_align.py` 当前报 `fields_fail=2 ['IsTnd','IsNEqual'] | inv_fail=2 ['I4','I5']`。**这 4 条都不是回归**：

- `IsTnd` / `IsNEqual`：脚本用自带的简化 `value_leaves`（`diag_align.py:137-146`），没有合并 `smt_value_leaves`。裸布尔字段展开后没有 `Ite`，在它那里恒为 0 个叶子，于是撞上 `MIN_LEAVES=2`。probe 对同两个字段报的是 `leaves=2`。
- `I4` / `I5`：在 live Expr 树上按子串找 `hasRope` / `QUERY_ROPE`，而树里的符号是 `queryRope` 等，永远不命中。

修它需要让 diag 的叶子口径与 `derive()` 对齐（`derive_key_fields.py` 里 `leaves |= smt_value_leaves(out.value_expr)`），并把 I4/I5 的 token 表对齐真实符号名。在此之前**不要把 handoff 里"期望 fields_fail=0"当成判据**。
