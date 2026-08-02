# KeyField 派生修复 — 交接

> **调试产物，不是工作流契约 / 验收依据。**  
> 生产入口：uo-init Action `derive_key_fields` → `uo_init.host_derivation` / `derive_key_fields.py`。  
> 探针：`scripts/_probe_derive.py`（薄封装，勿当唯一入口）。

面向「接手这项工作的下一个人」。目标是让 KB 侧把算子的 TilingKey 各维派生到输入根，再驱动 TG 做逐 key Z3。**不要为 FAG 做特化**，机制要能迁移。

---

## 数字看哪里（2026-07-31 定）

| 用途 | 文件 | 谁写 |
| --- | --- | --- |
| **权威机器结果** | `docs/debug/current-status.md`、`docs/debug/history.jsonl`、`docs/fag/fag_arch35.md` | `scripts/_probe_derive.py` 每次全量跑自动写 |
| 说明性文档 | 本文件、`docs/debug/open-problems.md` | 手写 |

**本文件与 `open-problems.md` 不得作为 gate，其中的数字是当时的注解，可能落后于机器结果。** 此前顶部长期挂着手写指标，改一次派生就过期一次，而过期的数字被当作门槛比没有数字更糟——所以指标表已删除，下面各节保留的数字只用于解释「某次改动带来了什么变化」，判断现状请读 `current-status.md`。

## 当前状态（能力项，非指标）

| 项 | 状态 |
| --- | --- |
| **19 维精确闭合 / 输入可控** | 见 `current-status.md`。下游该读的是 `INPUT_DERIVABLE`，不是 `CLOSED` |
| 隐式零默认 | 压在 exact 字段下的 **0 处**（原 6）——穷尽 cascade 判掉 + 读声明初值；剩余全在 overapproximated 字段下 |
| 派生进主链 Action | **已到**（`derive_key_fields` + `host_derivation.yaml`） |
| 共享求解器 | **已到**：`engines/common`（`acp_common`），TG / UO 同一套 IR 与 Z3 语义 |
| 19 维结构对齐 | **FAIL=0**；`domain_violations` 唯一报例（OutDType）**已求证为本工具假阳性**，检查本身有设计缺陷 —— 见「`domain_violations` 比错了东西」 |
| LLM 封闭回环 | 已联调；「只改账不改式」现由消元后校验 + 回退挡住，见 F.2 / F.12。**`LOOP_ELEMENT` 已移出 LLM 队列，且不再回收** |
| key 判定 8705 / K6 真 Z3 | **已到**：8705 个合法 key 全部过 Z3，**19/19** 维进求解器；当前 **2592 `unknown` + 6113 `unreachable`**（见 G） |
| `unreachable` 的逐条证据 | **未做**（批次 C）。6113 条目前只有 `unsat_core` + `checked_dims`，不足以逐条复核，数量是否偏高尚未证实 |
| G0 fixture / K5 / K7 | **未做** |

**不能宣称三重全覆盖已达成。**

### 口径变更：`derived` 不是验收指标（2026-07-30）

旧快照 `derived 19/19 partial 0 unresolved 0` **是假成功，勿再引用**。`status` 只回答「有没有表达式」，不回答「这个表达式还等不等于源码的意思」。19/19 是靠 `derive()` 里一条兜底分支（见到输入根就判 derived）得到的，而那些表达式里大半守卫已被换成自由布尔量。

现按 `exactness` 分级，`status` 降为它的投影：

| exactness | 含义 | status |
| --- | --- | --- |
| `exact` | 表达式只依赖真实输入变量 | derived |
| `constant` | 无变量，恒定值 | derived |
| `overapproximated` | 含 `VAR_UNDECIDED_/SCHED_/REACHED_/INIT_/LOOPELEM_` 自由量 | partial |
| `partial` | 还有 unresolved 子项 | partial |
| `unresolved` | 没有表达式 | unresolved |

### 验收口径再改（2026-07-31）：不再以 `CLOSED 19/19` / `free_vars = 0` 为目标

**旧目标「19/19 且 `free_vars = 0`」已作废，勿再引用。** 剩下的自由变量里，`invalidS1Array` × 2 与 `parseInfo[last]` 的量化上界依赖 shape，要精确表达就得往共享 Constraint IR 里加索引变量、绑定范围与求和 lowering —— 那是把这个项目从「关系提取器」推成「抽象解释器」，投入产出已经倒挂。这三个**有意保留过近似**，由真实 Host tiling 回放兜底（见下节）。

静态侧的停止线定在：**有界循环 + 条件事件计数 + 语义互斥**的关系摘要做完即止。

新的验收看 K6 的判决分布，不看 `CLOSED` 是否上涨：

```
unreachable_count   必须增加
unknown_count       不得增加
reachable_count     不得凭空增加
死分支              被证明 UNSAT
```

正确性最终由动态兜底，而不是靠静态做到 19/19：

```
Z3 生成输入 witness → 执行真实 Host tiling → 读回实际 19 维 TilingKey → 与预测比对
状态分四档：unreachable_static / candidate_static / confirmed_runtime / runtime_mismatch
```

静态多产生的候选会被真实 tiling 过滤掉，只有回放成功的才计入 KEY 覆盖。所以 `invalidS1Array` 不精确**不影响 case 正确性**，只影响候选数量。

#### 这条验收标准当前测不出来，原因已定位（2026-07-31）

有界基数摘要做完后实测 K6：8705 个合法 key 里 **8704 unknown / 1 unreachable**，与做之前逐项相同。不是摘要没生效，而是**判决被更上游的东西挡住**：每个 unknown 的理由都是同一句

```
5 dimension(s) not constrained: [SplitAxis, DeterType, IsBn2MultiBlk, IsNzOut, IsTndSwizzle]
```

这 5 个正是 `overapproximated` 的 5 个，而它们现在只剩 `invalidS1Array` × 2 与 `parseInfo[last]` 三个自由变量 —— 也就是上面明确决定**有意保留**的那三个。

结论要记住的一点：**消掉 `size()` 是必要不充分的。** 只要这 3 个还在，K6 就不会有任何判决变化，`unreachable_count 必须增加`这条标准在动态回放接上之前无法满足。当前能核的是它的另外三条（unknown 不增、reachable 不凭空增、unreachable 不减），三条都过。

历史快照（当时口径，仅供对照，勿作现状）：

```
CLOSED 14/19   unique free_vars=6   implicit_zero=211   ~12s
exact=13  constant=1  overapproximated=5   max_chars=80326
SCHED=0  REACHED=0  array_subscript=0  UNMAPPED_CALL=0  UNMAPPED_SYMBOL=0
```

当时残余 6 个**全部具名可解释**（不再有 `VAR_UNDECIDED_*` 匿名布尔量）：

| 变量 surface | 源码 |
| --- | --- |
| `invalidS1Array[j]` ×2（两个 scope） | `normal_regbase.cpp:1546`、`varlen_regbase.cpp:897` |
| `parseInfo[(s2Outer(fBaseParams) - 1)][LENGTH_IDX]` | `normal_regbase.cpp:1558` |
| `size(syncRounds)`、`size(syncRoundRanges)` | `varlen_regbase.cpp:716`（**已消元**，见「有界基数摘要」） |
| `back(slicePrefix1)` | `varlen_regbase.cpp:171`（**已消元**，见 `LAST_PUSH_DOMINATES_BACK`） |

5 个未闭合：`SplitAxis / DeterType / IsBn2MultiBlk / IsNzOut / IsTndSwizzle`。

`free_vars` 逐步位移（每步单独量化，`docs/debug/history.jsonl`）：

| 步 | 改动 | free_vars | 说明 |
| --- | --- | --- | --- |
| 基线 | scope-aware `_container_element` 后 | 19 | array_subscript 31 个变量 |
| ① | `value_expr` 按 DAG 序列化 | 19（不变） | 纯序列化修复，语义不动；恢复了度量能力 |
| ② | 下标处 cut point | 12 | array_subscript 31→0 |
| ③ | `_expand_container_surface` 补 scope | 9 | `qValue`/`kvValue` 4 个假过近似消除 |
| ④ | 元素 slot（`v[i].second`）纳入 cut | 6 | `UNMAPPED_CALL` 归零；`SplitAxis` 单字段 8→6 |
| ⑤ | 下标**浅展开** + 完整下标链做 identity | 5 | 同时修掉过粗与过细；`max_chars` 173K→80K、27.5s→11.6s、`implicit_zero` 215→211 |
| ⑥ | 容器摘要（`size()`/`back()`）纳入 cut | **6** | `UNMAPPED_SYMBOL` 归零；`SplitAxis` vars 34→**39**（救回 4 个真实输入约束） |

**CLOSED 停在 14 是符合预期的**：②④⑥只是把过近似从"整条守卫"收窄到"一个元素/一个摘要"，并没有消元；③⑤消掉的是本来就不该存在的过近似。要再涨 CLOSED 必须真正消元。

**⑥ 让 free_vars 从 5 涨回 6，这是对的。** 判据不能只看这一个数：`SplitAxis` 的变量总数同时从 34 涨到 39，即多了 5 个变量参与约束而只多 1 个自由变量 —— 那 4 个是原本被整条守卫塌缩吞掉的**已解析输入约束**（`CORE_LIST_NUM` 比较等）。用 1 个自由变量换回 4 个真实约束，且过近似从"整条守卫不可知"收窄到"3 个容器摘要不可知"。

剩下 6 个**全是 `LOOP_ELEMENT`**（元素 3 个 + 容器摘要 3 个），已没有静态解析缺陷可修：它们是循环建立的量化命题，本分析不计算。见 [open-problems.md](./open-problems.md)。

### 口径变更（二）：`CLOSED` 也不等于「下游可用」

`exactness` 回答的是**表达式**闭不闭合，不回答「测试用例能不能把它调出来」。这两件事在 FAG 上差 4 个字段：

```
CLOSED 14/19   INPUT_DERIVABLE 10/19   free_vars=6   implicit_zero=211
```

`IsTnd` 是最干净的例子：SMT 形态就是一条 `layoutType == 4`，零自由变量，判 `exact` 毫无争议 —— 但 `layoutType` 是 resolver 停在的 host tiling 状态，不是它背后的 layout 属性。生成器无论怎么设输入都碰不到它。`IsPse` / `IsAttenMask` / `IsNEqual` 同理。

所以新增一个与 `exactness` 正交的维度 `input_closure`（`kb_model.classify_input_closure`，由 `root_vars` 现算而非另存，两者不可能不一致）：

| input_closure | 含义 | 算可用 |
| --- | --- | --- |
| `controllable` | 根全在 `CONTROLLABLE_ROOTS`（shape / dtype / format / value / attr / optional presence / session option） | 是 |
| `platform_locked` | 还含 `PLATFORM_* / COMPILE_* / TEMPLATE_LITERAL / CONSTANT` —— 不是旋钮，但给定 CANN profile 后固定 | 是 |
| `host_state` | 含 `TILING_DATA / TILING_KEY / EXTERNAL` 或调度根，**也包括任何没分类的根** | 否 |
| `none` | 无根（常量字段） | 是 |

未识别的根一律归 `host_state`：反过来猜会拿一个没人分类过的根去宣称维度可控。

`input_derivable` 三处判据统一为 `exactness ∈ {exact, constant} 且 input_closure ≠ host_state`：

| 落点 | 旧判据 | 问题 |
| --- | --- | --- |
| `host_derivation.py` `to_key_derivations` | `status == "derived" and bool(root_vars)` | `TILING_DATA` 也算 True |
| `kb_export.py` `ir/input_derivable.yaml` | 读 `input_realization_mode == "host_derivation"` | 只要有 binding 就给**全部 19 维**标 True |
| `materialize_tiling.py` `input_realization` | 硬编码 `True` | binding 只说明找到了 encode 点 |

后两处现在都读同一个 per-field 判据（真源在 derivation，`materialize_into_kb` 新增 `derivation` 入参；**没有 derivation 时一律 False**）。

顺带修正一个反向错误：`IsRegbase` 是 `constant`、无根，旧判据 `bool(root_vars)` 把它判成 False。常量字段不需要设任何东西就能取到它的值，应算可用。所以净变化是 −4 +1 = **13 → 10**。

**账面变差但正确**，与当初 `derived 19/19` 落回 `exact 10/19` 同性质。

### 值域一致性：`domain_violations`

`value_leaves ⊆ domain` 的通用哨兵（`FieldDerivation.domain_violations`）。FAG 上立刻抓到一条：

```
WARNING: OutDType encodes ['4', '5', '6'] but the template declares ['0', '1', '2', '3']
```

这**不是派生 bug**。源码就是直接赋值、无任何映射（`..._tiling_common_regbase.cpp:1180` `fBaseParams.outDtype = fBaseParams.inputDtype;`），所以派生给出 `OutDType` 与 `InputDType` 表达式相同是对的。缺陷在算子侧：TPL 只声明 `OutDType` 取 0-3，host 在 FP8/HiFloat8 路径会写 4/5/6 并编进 key。需要单独报给算子方。

两个实现细节，都关乎这个检查有没有区分度：

- **只判能定值的叶子**。`value_leaves` 里同时有折叠后的数字和没折叠的枚举拼写（`DtypeEnum::FLOAT32`、`TILING_KEY_1`），把后者也算越域会让 19/19 全报警，检查即失效。所以报的是真实冲突的**下界**。
- **`InputDType` 是对照组**：它带着与 `OutDType` 完全相同的叶子集合，但声明 0-6，因此干净。没有这个对照就说不清检查是不是碰巧过的。

### 为什么一个下标能毁掉整条守卫（②的动机）

展开后的守卫是路径上**所有**源码守卫的合取。`_ValueNormalizer._leaf/_bool/_value` 三处遇到无法解析的 `Select` 就 `raise NormalizeError`，异常冒泡到 `_guard_uncached`，后者把**整条守卫**换成一个自由布尔量。

实测：31 个 `blocked_on=array_subscript` 的变量里，只有 1 个的守卫原文真是 `!(invalidS1Array[j])`；其余 30 个是巨型合取，文本开头分别是 `inputLayout == 'SBH'` 的 layout cascade、`SetSparseParams(...)`、`platformInfoPtr == None`。一个下标把它们旁边的 layout / platform / attribute 约束全丢了。

在下标处截断后，这些约束被救回来 —— 直接证据是 root 集合变大：`IsNzOut`/`IsTndSwizzle` 多出 `OPTIONAL_INPUT_PRESENCE`/`SESSION_OPTION`/`INPUT_DTYPE`，`DeterType` 多出 `PLATFORM_ARCH`。

### `_expand_container_surface` 漏打 scope（③）

`Select.array` 走 `_expand_container_surface`，**不是** `_expand_surface`。F.8 那次只给后者补了 `replace(e, scope=fn)`，容器路径漏了，于是每个跨函数容器都不带 scope、被拿到 encode 函数里解析、丢掉输入根。

`qValue` 在 `GetShapeAttrsInfo` 里是 `actualSeqQlenTensor->GetData<int64_t>()`（`..._tiling_normal_regbase.cpp:220-239`），root=`INPUT_VALUE`；在 encode 作用域是 `UNMAPPED_SYMBOL`。修 scope 后 `qValue`/`kvValue` 的 4 个变量直接变成正常的 `VAR_ELEM_*`。

**教训**：`test_container_element_uses_the_scope_on_the_array_ref` 一直是绿的，因为它手工构造 `Ref("qValue", scope=...)`，绕过了展开阶段。断言"下游会用 scope"不等于断言"上游会打 scope"，两端都要测。

### 元素的 tuple slot 绕过了 cut point（④）

②只在**裸 `Select`** 上截断。`s1ValidIdx[i].second` 的 IR 是 `Call("field:second", (Select(...),))`（`cpp_expr.py:224-235` 把无括号成员访问编码成 `field:`），外层是 `Call`，于是 `_leaf/_bool/_value` 三处的 `Select` 判断全部落空，掉进文本路径：`dotted_path` 渲染不了下标（`source_resolver.py:376-387` 遇到非 `Ref` 基底返回 `None`），`_leaf_text` 退化成调用语法 `second(?)`，re-parse 后 `field:` 标签丢失，最终按"没人声明过的函数"判 `UNMAPPED_CALL`。**同一个语义（循环内元素、无闭式），裸下标被正确近似，取了成员就把整条守卫判死。**

修法是让 slot 走同一个 cut：`_element_member` 识别 `Call(<slot accessor>, (Select(...),))` 并转交 `_element_or_cut(base, slot=...)`。三处入口都接（`_value` 里放在 `_pure_helper` 之后，让已有路径先有机会）。

两条边界，都有单测钉住：

- **slot 是变量身份的一部分**。`.first` 是索引、`.second` 是上界，共用一个变量会让求解器断言两者相等，从而满足任何输入都满足不了的守卫。identity 因此是 `(scope, container, index, slot)`。
- **只兜底、不抢活**。`_expand_call` 早已能把 slot 从看得穿的 tuple（`make_pair`、其上的 `Ite`）里投影出来；到得了这里的都是它投影失败的残留。`make_pair` 基底必须仍返回 `None`，否则静态已知的分量会退化成自由变量。

顺带撤掉了一处**无位移改动**：先前在 `PredicateNormalizer._leaf` 加过 `_member_atom`，想绕到 `resolve_call` 的 `field:` 分支（`source_resolver.py:439-456`）。它零位移，因为那个分支内部仍是文本路径（`_expr_text(args[0])` → `resolve("s1ValidIdx[i]")`），而 `s1ValidIdx` 是循环内 local `vector<pair>`，**本来就没有输入根**可继承。这不是解析 bug，是该走近似的东西没走近似 —— 换句话说，问题的正确落点从一开始就在 cut point 一侧。

### 下标不该被展开（⑤，本轮最重要的一处）

起因是查 ④ 之后剩下的变量时，发现 `calculatedBlockInfo` 的 surface 记成了 `calculatedBlockInfo[SUM_ALL]` —— 中间的 `[b][0]` 不见了。`_container_of`（`derive_key_fields.py:1803-1804`）会 `while isinstance(arg, Select)` 剥掉**所有**下标，而 `_loop_element_var` 的 surface 又只取最内层 index。于是不同元素拿到同一个变量：

- `calculatedBlockInfo[b][0][SUM_ALL]`（`varlen_regbase.cpp:991`）与 `[b-1][0][SUM_ALL]`（`:997`）
- `parseInfo[i][LENGTH_IDX]`（`normal_regbase.cpp:1529`）与 `[i-1][LENGTH_IDX]`（`:1531`）

它们是**前缀和**，相邻项恒不等，所以这不是"过近似"而是**假等式**；方向与一般过近似相反 —— 约束变强，会误杀合法 key。

**第一次尝试是错的，记下来避免重走**：只把 surface 改成完整下标链，`free_vars` 从 6 暴涨到 **21**（`parseInfo` 一个容器就 11 个变量）。原因是展开后的下标**已经不是下标**了：

```
parseInfo[let $1 = (((((True && True) && True) && True) && True) ? SetSparseParams(context_, fBaseParams) : 0)
let $2 = (!((platformInfoPtr == None)) ? 32 : …
```

外层 `i` 被内联成一个含守卫与 `SetSparseParams(...)` 的巨型表达式，同一个源码读取点在不同展开路径上形状不同，于是被拆成十几个源码里并不存在的变量。**过粗换成了过细，两者都错。**

根本解法是让下标**不参与跨函数深展开**（`_expand` → `_expand_surface`，`derive_key_fields.py:1275-1289` 与 `:1397-1402`）。依据是逐处核实过的一个事实：**没有任何路径消费下标的值** —— `Select` 在归一化时被 `_element_or_cut` 整体替换成一个自由变量，index 只用于渲染与 identity。既然值从不使用，展开它没有收益，只带来路径敏感的噪声。

为什么 `invalidS1Array[j]` 一直是干净的、而 `parseInfo[i]` 不是：`j` 的所有定义都在 `for`/`while` 头下，`_loop_scoped_only`（`:788-797`）判 true，`_expand_name` 直接返回 leaf；`i` 有 unguarded init 或可用守卫，于是走了 `_chain` 全量替换。

浅展开 + 完整下标链一起用才完整（只要其一都不够：只浅展开则 `[i][LENGTH_IDX]` 与 `[i-1][LENGTH_IDX]` 仍撞在最内层）。收益超出预期，且**约束一个没丢**（各字段 `input_roots` 与 `value_leaves` 前后完全一致）：

| | 改前 | 只改完整链 | 浅展开 + 完整链 |
| --- | ---: | ---: | ---: |
| free_vars | 6 | 21 | **5** |
| max_chars | 173604 | 173604 | **80326** |
| 全量耗时 | 27.5s | — | **11.6s** |
| implicit_zero | 215 | 215 | **211** |

`implicit_zero` 少的 4 处是为了求下标的值而做的零假设 —— 值既然从不使用，那 4 个假设本就不该存在。

### 容器摘要也需要 cut（⑥）

`size()` / `back()` 走 `_container_reduction`，它只能按"填充容器的输入"给摘要命名；`syncRounds` / `slicePrefix1` 是循环内构造的局部容器，没有这种根，于是返回 `None` 且调用点无兜底，整条守卫塌缩。这是 ②④ 同一个病的第三个变体（裸下标 → 元素 slot → 容器摘要），修法对称：`_loop_reduction_var`，identity 为 `(scope, container, kind)`。

三条 cut 现在共用 `_loop_local_var` 记账，避免 VarSpec 构造逻辑三份。

### 隐式零默认（213 → 159 处）

`_chain` 构建 if/else-if 链时，最内层那个 `Ite` 的 else 没有来源，就填 `Const(0)`（「字段默认为零」）。这**不是**自由变量，不计入 `free_vars`，但它是一个我们从没读过声明就下的断言，所以现在逐处记录到 `implicit_defaults`。

原先 211 处，**且压在 6 个已判 `exact` 的字段下**（InputDType、S1TemplateNum、S2TemplateNum、OutDType、DTemplateNum、IsDNoEqual）。即当时的 `exact` 判据尚不足以保证正确 —— 口径以 `python scripts/uo_key_status.py .probe_cache/fag_derive.json` 末尾两行为准。

**这个风险面现在是 133 处 / 0 个 `exact` 字段。** 分两步走到的：穷尽性判定先把 6 个收到 3 个（`InputDType` / `OutDType` / `IsDNoEqual` 是 dtype cascade 被判穷尽的直接结果），读声明初值再把剩下 3 个（DTemplateNum / S1TemplateNum / S2TemplateNum）关掉——那 3 个的声明初值是 128/128/64 而非 0，属于**假设为假**而不只是未证明。比计数更要紧的是这一条：**下游无条件信任的 `exact` + `drivable` 标签，现在不再背着未证明假设**。剩下 133 处全部压在已判 `overapproximated` 的字段下，下游本来就不会盲信。

多数其实**语义上不可达**。以 layout cascade 为例（`..._tiling_normal_regbase.cpp:99-320`）：

```cpp
if (strcmp(inputLayout, "SBH") == 0)      { fBaseParams.b = …; }
else if (strcmp(inputLayout, "BSH")  == 0) { … }
else if (strcmp(inputLayout, "BNSD") == 0) { … }
else if (strcmp(inputLayout, "TND")  == 0) { … }
else /* BSND */                            { fBaseParams.b = …; }
```

分支是穷尽的，`Const(0)` 那条路走不到。但**求解器不知道**——它会认为字段可以取 0，于是放行本不存在的 key。方向是过近似（多放行），不是漏判。

#### 穷尽的那部分已经不再记假设（P1.3 前半，2026-07-31）

原先判断「正确解法是用 `prove_implies` 证守卫析取为真」——这判断是错的，**代价被高估了**。`if/else-if/else` 的穷尽性是语法性质，不需要求解器：走一遍 `PathCond` 的决策树即可。

`PathCond` 本来就带 `negated`，但 `DefSite.guards` 存的是 `pretty()` 之后的文本（negated 被压成 `!(…)` 字符串），结构在这一步丢了。所以 `DefSite` 加了 `conds`（原始 `PathCond` 元组），判定在 `derive_key_fields._paths_are_covered` / `_covers`：

- 每一层要求所有路径在决策**同一个** `(file, line, text)`，然后 then / else 两侧各自递归；
- 路径走空 = 这一侧被无条件写到，覆盖其下全部；
- 路径对「下一个判什么」不一致 → 判否。方向安全：把真假设漏报才是危险，多报无害。

必须按路径树递归、不能只找「一正一负配对」：else-if 级联的各条路径**长度不等**（`(A假)`、`(A真,B假)`、`(A真,B真)`），配对法认不出来，而它恰是 layout / dtype 的实际形态。

两处收紧是抽查真实数据抓出来的，都关乎正确性：

1. **顶层的无 guard 写不算「覆盖其余」。** 函数**内部**它确实覆盖，但它是否执行取决于该函数被不被调用，且哪条写生效是 `_chain_sites` 的折叠顺序决定的。放宽这一条会让 `this.b`（18 条无 guard 写散在十几个函数里）被静默判为穷尽。
2. **跨函数不算穷尽。** 两个函数各写同一条件的一侧，合起来看像穷尽，但任一个都可能被单独调用。`_chain_sites` 里加 `len({s.function for s in sites}) == 1`。

收紧前 354 个多写字段被判穷尽，收紧后 22 个 —— 全是同函数内逐层取反的真级联。抽查 `fBaseParams.g`（`..._normal_regbase.cpp:103/142/182/294/326`）：5 条正对应 SBH / BSH / BNSD / TND / `} else {` BSND，最后一条落在真 `else` 上，与源码一致。

**第三处收紧：early-return 蕴含的否定可能不完整。** 隔离调查警告 `GetDTemplateType` 的穷尽判定「成立得侥幸」，核实后确认这是真隐患。`_guard_clause_negation` 为 `if (c) { …; return; }` 之后的语句补一条 `!c`，但只补**最外层**的 `c`：面对

```cpp
if (d <= NUM64)       { …; return; }
else if (d <= NUM128) { …; return; }   // 这几层的条件从不被取反到路径上
…
return NUM768;                          // 只拿到 !(d<=NUM64)
```

收尾语句记录的 guard **弱于真实**，于是它的路径在 `_covers` 递归里**提前走空**，那一层就直接判「这侧被无条件写」，跳过了对该层决策两侧的检查 —— 漏报假设的方向。

这种路径与真正的 `else` 分支在 `PathCond` 上完全同形（都是 `negated=True` + 同 file/line），只能靠来源区分，所以加了 `kind="guard_clause"` 与 `records_what_follows`。判据必须精确到**这个 `if` 有没有 else 链**：`if (c) {…return;}` 无 else 时 `!c` 就是完整条件（`ProcessPseInfo` 给 `pseOptional` 赋值正是这个形态，两条写恰是正反两侧的真穷尽），只有带 else 链时才不完整。第一版按「凡 implied 皆不可信」处理，`IsPse` / `IsAttenMask` 立刻被误判为带假设（161 处 / 5 个 exact 字段）；精确化后回到 159 处 / 3 个，但机制从「恰好答对」变成「按理答对」。

`_covers` 的信任标记要**按侧**判定而非按决策：`guard_clause` 恒为取反侧，两侧的 kind 可以不同，传错侧就判错。

结果 `implicit_zero` **213 → 159**，`CLOSED 14/19`、`INPUT_DERIVABLE 12/19`、`free_vars=6` 逐项不变。（未收紧时是 137，那 22 处差额里含前述两类误判，不可取。）

#### 剩下的出路：读声明初值（P1.3 后半，已做）

159 条记录落在 60 个不同写点、8 个维度上（`.probe_cache/diag_zero_rest.py`）：

| 数量 | 形态 |
|---:|---|
| 41 | 该函数内只有这一条有 guard 的写，别处不赋值 |
| 14 | 同伴写确实留了第一个决策的一侧没写 |
| 5 | 同伴写在单函数内穷尽，但别的函数也写同一路径（被上面第 2 条收紧拒掉） |

隔离调查（不预设结论）给出的分解比上表更有用 —— 60 个站点里 **37 个本身就是带初始化器的局部声明**（初始化器早已在 IR 里，就是站点自己的 RHS，无物可读）、**3 个是 `__return__` 合成槽**（不存在声明）、真正需要读声明的只有 **20 个结构体成员写**，其中 13 个成员有类内初始化器、7 个完全没有。

**关键不是计数，是其中 3 个假设是错的。** `FuzzyBaseInfoParamsRegbase` 的声明（`..._tiling_common_regbase.h`）：

| 成员 | 声明初值 | 工具此前当作 |
|---|---|---|
| `s1TemplateType` | `ConstAxisTemplateNum::NUM128` = 128 | 0 |
| `s2TemplateType` | `ConstAxisTemplateNum::NUM128` = 128 | 0 |
| `dTemplateType` | `ConstAxisTemplateNum::NUM64` = 64 | 0 |

而这 3 个成员正好是 `S1TemplateNum` / `S2TemplateNum` / `DTemplateNum` 的来源 —— 也就是当时**唯一剩下的 3 个「exact 却带假设」的字段**。核对源码确认假设是真的：`GetS1S2TemplateType`（`:810-843`）的写止于第 4 个 `else if`，`GetDTemplateType`（`:845-868`）止于 `d<=NUM768`，收尾 `return` 都**不写**这些成员，所以条件全不成立时它们保持声明初值。求解器此前会放行 `S1TemplateNum == 0` 的 key，而算子产不出这个值。

实现：`FIELD_DECL` 分支除 `class_fields.add` 外读初始化器，存 `WalkResult.field_decls` / `HostIR.field_decls`，`_chain_sites` 的兜底改查 `_declared_default`。三处刻意保留假设：查不到声明、成员**声明就没有初始化器**（值真的不确定，比"没去读"更强的结论）、初始化器不是常量。

**索引键必须是 (结构体, 成员名)，且查询要求成员名唯一。** 调查抓到的陷阱：若按裸名索引（像 `class_fields` 那样），7 个"无初始化器"成员里有 6 个会撞上生成的 tiling-data 同名成员（那些是 `= 0`），把「无法证明」伪造成「已证明为 0」。今天 `_host_field_allowed` 恰好把它们滤掉了，但扩到 arch22 宿主侧就会真撞上。名字撞了就放弃 —— 保守降级。

结果 **`implicit_zero` 159 → 133**，且「压在 exact 字段下的假设」这一行**整行消失**：`exact` 判据现在不再背着任何未证明假设。三个字段的 `value_leaves` 都不再含 `0`（`_probe_derive.py --show S1TemplateNum` 可见最内层兜底是 `ConstAxisTemplateNum::NUM128`）。关掉 26 个而非预期的 13 个，因为一个成员的声明会被多个读取点复用。

尚未做的两项（调查已给设计，收益已量化）：37 个局部声明站点可用 `kind="decl"` 让兜底取声明自身值（`Ite(g, init, init)` 坍缩），但要先处理 6 个循环体内声明与 `_loop_scoped_only` 的先后、以及 `rm3` 那处同作用域遮蔽；7 个无初始化器成员**永远关不掉**（对象经 `new T(context)` default-init、构造体为空、全树无 memset，读之前的值确实不确定），它们该被重新分类为比"假设为 0"更严重的问题。

### 循环与分支现在是结构化的（P2 前置，2026-07-31）

原先记为「循环检测靠 `for(` 字符串前缀匹配」。核实后这个说法要修正一半：`PathCond.text` 对循环**本来就是**这份代码自己合成的 `f"{kind}({cond_text})"`（`clang_walk.py:1038`），producer 与 consumer 同仓，所以 `_NON_GUARD_RE` 不是从源码猜格式的脆弱启发式。

真正的问题是 `kind` 被编码进了 `text`：想知道「这条 guard 是不是二分决策」只能把文本剥回来，而**循环的归纳变量和 trip count 根本没地方放** —— `CtrlNode` 有 `induction_vars`，但 `WriteRecord` 只带 `PathCond`，且 `build_host_ir` 把 `res.controls` 整个丢了。

两步都做了，`text` 格式一字未动（产物不变）：

1. **`PathCond.kind`**（`if` / `ternary` / `switch` / `for` / `while` / `do` / `cxx_for_range`）+ `is_decision` property。`is_decision` 只对 `if` / `ternary` 为真：三元的两侧确实穷尽，而 `switch` 的各 case 全是 `negated=False` 且**没有 `default` 的保证**，循环则是「某次迭代」。上面的覆盖判定改读它，不再剥文本。
   - 留了一条文本回退（`_decides`）：缓存 bundle 与文本后端的 `PathCond` 没有 `kind`，若直接走 `is_decision` 会退化成「一律算决策」，把循环 guard 也算进穷尽性 —— 那是不安全方向。判据是 `"kind" in pc.__dict__` 而非 `getattr`，因为 property 抛 `AttributeError` 会被 `getattr` 的默认值吞掉。
2. **`HostIR.controls` + `loop_at(file, line)`**。循环内的写在 guard 里带着循环头的 file/line，这就是把写对回到归纳变量的钥匙。去重按 `(file, line, column, kind)` 而非 `CtrlNode.id`：id 的 ordinal 是 walk 序分配的，而 TU 是并行 walk 的。

验证走真实 clang walk（`test_host_ir_clang.py`，非缓存）：`controls` 非空且含 `if` 与循环 kind；每条循环 guard 都能 `loop_at` 到语句，且至少一条有归纳变量；位置无重复。

### 一个字段的定义池不该取决于怎么拼写它（P1.5，2026-07-31）

`_field_defs` 的匹配原先是单向的：`w.path == path or w.path.endswith("." + path)`。自由函数 `SetSplitAxis(ctx, FuzzyBaseInfoParamsRegbase& fBaseParams)` 把写记成 `fBaseParams.splitAxis` —— **跟着形参名**，于是查 `this.fBaseParams.splitAxis` 命不中，查 `fBaseParams.splitAxis` 才命中。同一个字段两种拼写拿到两套定义池（实测 6 vs 9），而**穷尽性判定吃的就是这个池子**，池子不全会让路径集不全。

没用"剥掉 `this.` 前缀再字面比较"这个拼写技巧。它在这份算子上恰好安全，但 `CalcleTNDBandDeterPrefix` / `CalcleTNDCausalDeterParamGQA` 等 4 个函数的 `deterPrefixData` 形参共 29 处写会被它误并（那 4 处调用点传的**不是**同一个对象），只是 FAG 上没有 `this.deterPrefixData.*` 这种查询路径才没暴露 —— 属于数据相关的安全，不是结构性的。

改成结构性判据 `HostIR.param_bound_member(fn, param)`：只有当该形参在**每个**调用点收到的实参都是 `this` 的同名成员时才合并，任何一个调用点传别的对象、或实参不是类成员、或压根没有调用点，都返回 `None`。实测 20 个形参解析到 `this.fBaseParams`，6 个（`deterPrefixData` ×4、`s1ValidIdx`、`tndBandDeterRoundInfo`）正确排除。

影响面 7 个路径（全在 `this.fBaseParams.*`），19 维指标逐项零变化 —— 那 7 个不在展开路径上。价值不在指标而在消除不确定性。单段路径刻意不做：`this.b` 剥前缀得裸名 `b`，而 `b` 是多个宿主的共同尾名（`this.fBaseParams.b` 是**另一个字段**），一段路径没有成员前缀可绑，形参名会被拿去和字段名比。

### `domain_violations` 比错了东西（P0.2 的设计缺陷，唯一报例已证伪）

判据原是 `value_leaves ⊆ TPL domain`。**`value_leaves` 是表达式里出现过的字面量集合，不是该维度可达的取值集合** —— `Ite` 死分支里的常量必然被计入，同一个值还会以折叠数字（`4`）和未折叠枚举拼写（`DTYPE_ENUM_INDEX_4`）各算一次。所以原先记的"报的是真实冲突的下界"要撤销：下界性依赖"叶子都可达"，而这个前提不成立。

`OutDType` 那条已证伪，证据是决定性的：**8705 个合法 key 里 `InputDType` 只取 0/1/2/3**，且 `(InputDType, OutDType)` 严格 `in == out`。`ASCENDC_TPL_UINT_DECL(InputDType, …, 0…6)` 是**声明域**，真正的合法集是 65 个 `ASCENDC_TPL_ARGS_SEL` 组的并集，没一组用 4/5/6。host 侧 `..._common_regbase.cpp:1146-1148` 一个 early return 同时拒掉 FP8_E5M2 / FP8_E4M3FN / **HIFLOAT8**（三者一起），所以 host 与模板一致。

> 别踩的推理陷阱：直觉版本会说"HIFP8 先写成 6，再被 `out_dtype` 属性改写成 BF16"。arch35 tiling 侧 `fBaseParams.outDtype` **只有一处赋值**（`:1180`），无任何重写；那段 `out_dtype == 1 → BFLOAT16` 在 `flash_attention_score_grad_infershape.cpp:141-177`，管的是输出 tensor dtype，与 tiling key 无关。

正确判据是求解器问题：**存在一组满足约束的输入，使该维度取值 `v` 且 `v` ∉ SEL 合法域吗**。K6 那条链已具备能力，改造复用它。**「声明域 ≠ SEL 合法集」这条要推广**：任何拿"某维度声明了哪些值"做判断的地方都有同样风险，一律走 `expand_legal_with_groups`。

**另一个独立缺陷，修了上面也不消失**：`clang_walk.py:1186-1187` 的 `_ERROR_EXIT_RE` 有意丢弃所有错误退出守卫的否定。该论证把两类混为一类 —— `if (shape == nullptr) return FAILED` 是**重述型**（取反无信息），`if (queryType == DT_HIFLOAT8) return FAILED` 是**排除型**（把具体输入值排除出可达域，取反是真实约束）。arch35 的 65 处 `return GRAPH_FAILED` 全按重述型处理，实测后果是 `:1180` 那个写的 `path_conditions` 为**空**。恢复前要先量化两类占比与表达式膨胀 —— 当初抑制的动机（防止一打守卫挂到后面所有代码上）是真顾虑。

### 不变式：过近似必须留痕

`free_vars(value_expr) ⊆ {g.var_id for g in undecided_guards}`。

一个没有 guard 记录的自由变量既升级不了也闭合不了，但求解时仍把那个条件当「两边都行」——账面收敛、实际放松。`FieldDerivation.unrecorded_free_vars()` 负责这个检查，`totals()` 与 `uo_key_status.py` 都会报，**必须为 0**。

### `value_expr` 的磁盘格式：DAG 信封（① 的产物）

`value_expr` 在内存里**是 DAG 不是树**：`_ValueNormalizer._lower` 按节点 identity 做 memo，同一个子表达式对象被多条路径共享。JSON / YAML 没有共享的概念，直接 dump 会**每条路径各写一遍**，也就是把 DAG 展开成树。实测最大字段展开后是 856,310 个节点，单字段 json 曾达 ~10MB，写满 `fag_derive.json` 直接 MemoryError —— 度量能力因此整段失效。

现在 `encode_expr_dag`（`derive_key_fields.py`）把共享显式化：

```json
{"$dag": 1, "nodes": 583, "tree_nodes": 856185,
 "root": {...含 {"$ref": "n7"}...}, "defs": {"n7": {...}}}
```

- **读的人必须走 `decode_expr_dag`**，它会把共享一起还原（不只是形状）。否则拿到的是展开后的树，正是这个编码要避免的代价。已接线：`FieldDerivation.to_dict` / `field_from_row` / `to_key_derivations` / `_probe_derive._field_row`。
- 小表达式**原样输出**（阈值 `DAG_ENVELOPE_MIN_NODES=4000` 树节点），保持产物可读；19 个字段里只有 5 个进信封。忘记解码时看到的是一个明显不是表达式的 dict，而不是一棵被悄悄截断的树。
- 效果：全部 `value_expr` 合计 152KB，最大字段压缩 1469 倍（856,185 → 583 节点）。

**同一个坑的另一半**：`smt_value_leaves` 当时是纯树遍历（没有 `seen`），而它和 DAG-aware 的 `_collect_vars_dag` 读的是同一个 `value_expr`。已补 memo。**在这个 DAG 上新写任何遍历，都必须按 identity 去重**，否则代价是展开后的规模。

---

## 工具

生产：`acp run-action derive_key_fields`。调试仍可用 `_probe_derive.py`（每字段独立进程 + 超时）：

```powershell
python scripts/_probe_derive.py                         # 全量，约 5–15s（有缓存）
python scripts/_probe_derive.py IsTndSwizzle --timeout 60
python scripts/_probe_derive.py --show IsTndSwizzle
python scripts/_probe_derive.py --refresh               # 重跑 clang，约 2–3 分钟；改了 clang_walk 才需要
```

全量跑（不带字段名）会自动追加一行 `docs/debug/history.jsonl`；只重算部分字段时不写，避免新旧混在一行里看着像回退。第 39 行起是新 schema（含 `closed` / `free_vars` / `unrecorded`），之前的行是旧 `derived` 口径，**不可跨口径比较**。

读结果的两个脚本（仓库根跑，吃 `.json` 或 `.yaml`）：

| 脚本 | 用途 |
| --- | --- |
| `scripts/uo_key_status.py <文件>` | 逐字段 exactness / free_vars，末尾报不变式违例 |
| `scripts/uo_key_blockers.py <文件>` | 按「卡住多少字段」排序，带 guard 原文与出处 |

缓存（gitignore）：`.probe_cache/fag_bundle.pkl`、`fag_derive.json`。

> `.probe_cache/fake_op/` 是 gap-loop 联调产物，**不能当派生基线**：它经过 `apply_gap_patch`，会少报过近似（实测 28 vs 真实 45）。看派生语义只用 `fag_derive.json` 或跑到 `derive_key_fields` 为止。

```python
import sys, pickle
sys.path.insert(0, "engines/understand-operator/src")
b = pickle.load(open(".probe_cache/fag_bundle.pkl", "rb"))
ir, resolver, model, binding = b["host_ir"], b["resolver"], b["var_model"], b["binding"]
```

诊断脚本（均可从仓库根跑）：

| 脚本 | 用途 |
| --- | --- |
| `.probe_cache/diag_blocked_on.py` | 按 `blocked_on` / `reason` 分组剩余过近似（**改派生后先跑这个**） |
| `.probe_cache/diag_dagsize.py` | 每字段 DAG 压缩比 + round-trip 自检 |
| `.probe_cache/diag_align.py` | 19 维值叶 + I1–I12 对齐（**判据已陈旧，见 open-problems.md**） |
| `.probe_cache/diag_collapse.py` | 恒真/恒假比较、值叶塌缩 |
| `.probe_cache/diag_undecided_impact.py` | undecided 主题分类 / 对后续任务影响 |
| `.probe_cache/diag_bn2s2.py` | `bn2S2RouteLimit` 是否残留不透明 Ref |
| `.probe_cache/diag_independent.py` | 表达式支持是否真正进 value_expr |

单测：从 `engines/understand-operator` 跑；仓库根会因 rootdir 误报。基线约 4 个与本工作无关的红测，勿混淆。

```powershell
cd engines/understand-operator; python -m pytest tests/unit/test_host_ir_clang.py -q
```

---

## 已完成的修复（按依赖 / 时间顺序）

### A. 基础设施（早先）

1. **复合赋值** `clang_walk.py`：`+=` 从 token 重建 RHS，避免记成覆盖。  
2. **表达式 DAG** `derive_key_fields.py`：`_pretty_dag` / `_ememo` / `_lower` / `_collect_vars_dag` —— `max_chars` 从亿级降到万级，是后续一切前提。  
3. **局部量误判 TILING_DATA** `source_resolver.py`：Params 快速路径降为兜底。  
4. **解析器** `cpp_expr.py`：若干边角。  
5. **分类器多 return 内联**：`≥2/3` 常量 return + 逆序 first-match；修 `_chase_helper_body` 首 return 假成功；`_is_constant` 不把轴名当常量；`_substitute_names` 跳过成员。  
6. **布尔字段走 `_guard`**：否则 `IsTndSwizzle` 等被一个不可约合取项整场打死。

### B. Soundness（problem.md B1–B5）

| Bug | 修法 | 结果 |
| --- | --- | --- |
| B1 SplitAxis 塌成单值 | early-return 守卫 + `_chain` 无守卫写只盖同函数；跨函数 → `__reached_Fn` | 值叶含 BN2 / BN2S2 / BN2GS1S2 |
| B2 IsTndSwizzle 恒 0 | 随 B1 | 多值 |
| B3 IsPse / IsAttenMask 恒 1 | `clang_walk` compound 传播 guard-clause 否定（含 if-return-else） | 双值 + OPTIONAL_INPUT |
| B4 IsEmptyTensor 恒 0 | `merge_literal_encode_alts` 并回 literal-only 空 tensor 站 | 含 TILING_KEY_1 |
| B5 循环 i 折成 0 | `_loop_scoped_only`：仅 for-init 的写不链式折叠 | 不再 `0==0` |

### C. 表达式支持

1. **Select / 下标** → `VAR_ELEM_*`（容器 root）；展开时 array 槽保持符号化。  
2. **back / front / size** → 与归约同类，不展开掉容器名。  
3. **具名常量数值化** `variable_model.named_constants`（enum + constexpr；含 kernel 头）。  
4. **GetData slug 撞名**：元素/归约变量用容器表面名，不用 `GetData`。

### D. 正确性 / 对齐（本轮）

1. **三元 RHS 错绑** `source_resolver.resolve_value`：赋值 RHS 的 `c ? a : b` 不收集 `c` 的 provenance。  
   - 修前：`fBaseParams.d` → `OPTIONAL_INPUT_PRESENCE`（hasRope）  
   - 修后：→ `INPUT_SHAPE`；`d <= NUM128` → 数值 128  
2. **splitAxis ↔ bn2S2RouteLimit 环** `_canonical_name`：裸名与 `fBaseParams.*` 共用栈帧。  
   - 修前：守卫残留 `Ref(bn2S2RouteLimit)`，I12 的 `!hasRope` 进不了树；`max_chars` ~148k  
   - 修后：残留 Ref = 0；`max_chars` ~40k；I12 对齐通过  

### F. 停止错误宣称（2026-07-30 本轮）

前五项都属同一类：**过近似从账面上消失，却仍在表达式里**。

1. **`derive()` 的兜底判定** `derive_key_fields.py`：只要收得到输入根就判 `derived`，无视守卫已被软化。删掉，改由 `classify_exactness` 定级、`status_of_exactness` 投影。→ 19/19 落回真实的 10/19。

2. **`apply_gap_patch` 只改账不改式** `gap_patch.py`：`input_derived` 判定把 guard 从 `undecided_guards` 删掉，却不动 `value_expr` 里的 `VAR_UNDECIDED_x`。结果是变量还在、记录没了，gap 机制从此看不见它，而 `escalating_after` 显示收敛。
   - 修法：binding 的 `{var_id, op, value}` 本就是可用条件，用 `substitute_vars` 代回表达式，再重算 `variables/exactness/status`；binding 不完整（只说「来自输入」不说测什么）则**保留** guard 并计入 `unusable`。
   - 这是「六个匿名 `VAR_UNDECIDED_*`」的真正来源，不是 `_guard_uncached` 漏记。

3. **调度叶子不留痕** `derive_key_fields._scheduling_leaf`：只写 `self.scheduling`（下游没人读），不写 `undecided`。`VAR_SCHED_COREIDX` 因此出现在 4 个字段的 `value_expr` 里却没有 guard。→ 一并写入 `undecided`。

4. **`__reached_Fn` 混在调度里**：拆为独立前缀 `VAR_REACHED_` + `PRESORT_REACHABILITY`。它是我们调用图分析的缺口，**不升级给 LLM**（让模型猜源码里写着的东西没有意义），但计入未闭合，由 3.B 的调用切片消除。

5. **软化判据是正则** `_SCHED_SOFT_RE`：按名字文本猜「像调度」。`layoutType` 这类输入约束被误软化，会让求解器放行本不可达的 key。→ 改为把守卫叶子解析到 root 再判定。

6. **local container 误记为 tiling 写入** `clang_walk._record_container_write`：`_record_write` 对无 `.` 的裸名不记 `writes`，容器变更却没有同一道守卫，于是函数内的 `std::set` `insert` 变成无 owner 的 `WriteRecord`，可能被 tail 匹配安到真字段上。FAG 里 2 条（`dqOffsetSet` / `dkDvOffsetSet`）。→ 补齐守卫，仍保留 `fr.assigns` 的 SSA 追踪。

7. **`_norm_expr` 空格失真** `source_resolver.py`：`\s*\)\s*→)` 连右侧空格一起吃，`strcmp(a, b) == 0` 变成 `)== 0`；`<`/`>` 双侧压缩把 `size() > 0` 压成 `size()>0`。这些串要跟源码原文和彼此做匹配，失真就对不上。→ 括号只贴紧自己归属的那侧；`<`/`>` 不动（条件里几乎都是比较，靠空格分不出模板）。

8. **叶子在错误的函数作用域里解析（本轮最大单点）**：展开是**跨函数**的（`_chain` 按 `site.function` 内联），归一化却固定绑在 encode 函数 `GetTilingKey` 上。于是内联进来的 `GetShapeAttrsInfo` 局部变量（`inputLayout`、`queryRope`…）在 `GetTilingKey` 里根本没有绑定，`source_resolver.py:731` 返回 UNMAPPED_SYMBOL，整条守卫被换成自由布尔量。
   - 两次独立调查（layout 一路、rope 一路）殊途同归指到这一处，不是两个孤立的映射缺失。
   - 修法：`Ref` 增加 `scope` 字段，`_expand_name` / `_expand_surface` 每次保留一个未展开的名字时打上它所在的函数；`PredicateNormalizer` 新增 `_resolver_for(expr)` 钩子（默认行为不变），`_ValueNormalizer` 按 `Ref.scope` 取对应作用域的 resolver。
   - 效果：**CLOSED 10→13，free_vars 45→32**；`IsEmptyTensor / DTemplateNum / IsRope` 闭合，`DeterType` 的自由量 10→2。同时浮出之前被埋掉的正确根 `OPTIONAL_INPUT_PRESENCE / PLATFORM_ARCH / SESSION_OPTION`（后者正是旧文档里记的 B6）。
   - 教训：**跨函数内联必须让符号带着它的作用域走**。只要展开会穿过函数边界，任何"单一 resolver"的归一化都会在别人的局部变量上失败——而失败方式是静默放宽，不是报错。

9. **守卫记录不说自己卡在哪（可观测性缺口）**：`undecided` 只存 `REASON: <整条守卫>`，而展开后的守卫动辄几百字符还会被截断。于是记录只告诉你"这条守卫失败了"，不告诉你**是里面哪个符号**失败——每次诊断都得重跑一遍派生去找。
   - 修法：`NormalizeError.detail` 本来就带着那个符号，只是被丢掉了。新增 `blocked_on`（deriver → `KeyFieldDerivation` → `UndecidedGuard` → `uo_key_blockers.py` 的 `ON:` 行）。
   - 效果：剩余 19 条 UNMAPPED/OPAQUE 守卫**只卡在 3 个符号**上，一眼可见：

     | 次数 | blocked_on | 影响字段 |
     | ---: | --- | --- |
     | 23 | `actualCalcS2Token<-actualCalcS2Token` | **全部 5 个未闭合字段** |
     | 3 | `array_subscript` | IsBn2MultiBlk, SplitAxis |
     | 1 | `prefix1Max<-deterPrefixData.prefix1<-prefix1Max` | SplitAxis |

   - 注意前后两条的 `<-` 链**都指向自己**。

10. **把顺序赋值当成了环**：调查推翻了「这些自引用是循环累加器」的猜想。`CalcleActualToken` 里就是最普通的命令式写法：

    ```cpp
    actualCalcS2Token = fBaseParams.s2Token;                            // 918
    actualCalcS2Token = actualCalcS2Token - actualS1Len + actualS2Len;  // 932
    ```

    932 行右边读的是 918 行写的**旧值**。`_expand_name` 的环检测不区分「`x = f(x)`」和真正的循环依赖，一律放弃展开，整条守卫随之被丢掉。
    - 修法：写入点本就按 `(file, line)` 排序，`_chain` 里的 `result` 恰好是「截至上一个写入点的值」——把它作为自引用应解析到的前版本（`_prev_version`）。这就是 SSA，不需要新概念。
    - **缓存是这里的难点，值得记下**：改完后耗时从 9s 涨到 300s+ 都跑不完。原因不是展开变慢，而是我先粗暴地「用过前值的结果一律不缓存」，导致同一展开每次产生**新对象**，表达式 DAG 退化成树。改用上下文作缓存键更糟（几乎全 miss）。正解是按**实际读到了谁**分槽：只读自己前值的展开是自封闭的、到处有效，进共享槽；只有读了**外层**名字前值的才按上下文存。回到 27s。
    - 效果：free_vars 32→28，`IsBn2MultiBlk` 16→5、`IsTndSwizzle` 14→11、`IsNzOut` 12→9。代价 `max_chars` 21K→175K、8.9s→27s，可接受。
    - **未完**：`actualCalcS2Token` 仍剩 19 条。因为环检测有**两处**，这里修的是展开层（`_expand_name`），resolver 层（`source_resolver` 的 `_chasing`）还没修。而且 resolver 那边 L658 本就优先选不自引用的 RHS，它没生效说明另有原因——`CalcleActualToken` 通过**引用参数**输出，调用方作用域里只有声明没有赋值。out-parameter 建模待查，勿猜。

11. **`implicit_zero` 会重复计数**：同一站点被不同调用方/不同缓存上下文多次链接时每次都记一笔，542 实际只有 202 个站点。已按 `(function, file, line)` 去重——报的是假设数量，不是访问次数。

12. **F.2 的修法只覆盖了一半形态（同类静默错误复发）**：`substitute_vars` 只匹配 `{"op": "eq", "var": X, "value": true}`。但 `PredicateNormalizer._truthy` 是**按变量类型**渲染真值探针的：bool 型出 `X == True`，int 型出 `X != 0`（C 的隐式真值测试）。而 `VAR_LOOPELEM_*` 全是 int 型。

    后果与 F.2 一字不差，只是换了个入口：LLM 对这类变量答 `input_derived`，`gap_patch.py` 把 guard 从 `kept` 删掉、`resolved` +1、`escalating_after` 下降、loop gate 通过，**而表达式原地不动**。同时它会破坏一直维护的 `unrecorded_free_vars() ≡ 0` —— 这也正是修它的抓手。

    - **两处都改**：`truth_probe_var()` 认下两种探针形态（只认这两种；`X == 5` 是源码写的比较，binding 说的是 guard，替换它是错的）。
    - **更根本的护栏**：`apply_bindings_to_derivation` 不再信任替换，而是**验证**——替换后变量若仍在 `collect_vars_dag` 里，就把该 binding 撤掉、guard 放回 `kept`、计入新的 `reverted`，只有真消掉的才计 `resolved`。回退是机械的，不关心替换为什么没生效（形态不匹配、变量还出现在值位、模型指错了 guard），因为**这几种情况的失败方式全是静默的**。
    - loop gate 补第三条：`free_vars` 总残量不得上升。只看 `derived` 与 `escalating` 时，一个 patch 可以用后者换前者 —— 划掉记录、留下变量，两个被监控的数都变好。

13. **符号折叠把两套编码混进同一个变量（K6 侧，2026-07-31）**：`key_reachability._Symbols.fold` 逐符号查 `named_constants`，查到用真值、查不到编一个负数。于是 `VAR_ATTR_GETATTRS` 上同时出现四个 layout 字符串：`"BNSD"` 折成 **2**（撞上某个不相干枚举的裸名 `BNSD`）、`"TND"` 折成 **4**（同样撞名，而 `LayoutEnum::TND` 其实是 3），`"SBH"` / `"BSH"` 拿编造的负数。字符串比较被安放到整数枚举的域里，求解器于是在判定源码从没写过的比较。

    - **修法一：按组折叠。** 组 = 该符号所比较的变量（跨全部维度聚合，因为存活下来的共享变量在每个维度里是同一个变量）。整组符号**全部读到 → 全用真值**（别名因此仍能相等），**否则整组一起编码**。绝不在一组里混真值与编造值。
    - **修法二：`ge::DataType` 抄进 `variable_model.GE_DATA_TYPE`。** 这 5 个 `ge::DT_*` 才是真正"读不到"的符号，值在 CANN metadef `graph/c_types.h`。不解析而是抄录：`graph/types.h` 写作 `DT_FLOAT = ::C_DT_FLOAT`，`parse_enums` 求不出值，而它求不出时的兜底是**继续往上数**，会在 4 之后的保留空位处发错值。算子若自己重定义同名常量，源码扫描仍然覆盖抄录值。→ `InputDType` / `OutDType` / `S1TemplateNum` 等 9 个维度的符号全部读到，**零假设**。
    - **修法三：编号计数器必须单调。** 原来用 `FIRST - len(self._invented)`，而 `_invented` 按符号名去重，于是同一名字在第二个组里不增长长度，**整组四个符号拿到同一个数** —— 本该互不相等的值全都相等。这是比错折更狠的一版：它直接伪造等式。
    - **修法四：裸符号不再当常量。** `{"op":"gt","lhs":…,"rhs":"m0Max"}` 里的 `m0Max` 不是常量，是 `CalcleTNDCausalDeterParam` 的局部归约变量（`m2Max = std::max(m2Max, …)`）；`i` / `j` / `s2Inner` / `deterTilingSplitMode` 同类，共 13 个。把变量替换成一个远低于真实范围的数会让 `x < m0Max` 恒假——**收紧**方向，正是伪造矛盾的方向。改为该维度 `omit`（`unmodelled_variable`）。
    - 效果：编译 14/19，假设只剩 4 个 layout 字符串；**`Z3Backend` 构造从 37 分钟没跑完变成 0.2s**——原先最贵的正是这 5 个含未建模变量的循环展开树，它们本就不该进求解器。8705 个 key 全量判定 127s（14.6 ms/key）。
    - 判定分布诚实地差：8704 `unknown`（"5 个维度未约束"）+ 1 `unreachable`。要往 `reachable` 走必须先做循环摘要（第 10 项），不是调参能得到的。

14. **容器摘要在不同读取点被断言相等（2026-07-31，隔离调查所得）**：`_container_element` 只给 `INDEX_FREE_KINDS`（`elem` / `first` / `second`）设 `identity_merged`，注释的理由是"`back` / `size` / 归约命名的是容器的**一个**值"。这对**静止的**容器成立，对**可变的**容器不成立。`deterPrefixData.prefix1` 在 6 个函数里被 `push_back`，而 `prefix1.back()` 在这些 `push_back` 的前后都被读到（源码 106 / 164 / 165 / 267 行与 503 行守卫），却共用 `VAR_ELEM_BACK_DETERPREFIXDATA_PREFIX1` 一个变量。**这是在断言源码不提供的等式，失败方向是凭空造出不可达 key** —— 正是设计规则明令禁止的方向。讽刺之处：过近似那条路径（`_loop_local_var`）反而设了 `identity_merged=True`，更"精确"的那条才是危险的。

    - 判据必须能把这一类和它的反例分开，而反例是真实存在的：`max(actualSeqQlen)` 跨 **5 个维度**共用一个变量，那个等式是**对的**（`actualSeqQlen` 在 `GetShapeAttrsInfo` 里填完就不再变），丢掉它只会让判决从 `unreachable` 退成 `unknown`。
    - 可用的判据只能建立在 IR 真有的东西上：**写点带行号，读点不带**（`FuncSummary.reads` 是无序名字列表）。所以"最后一次变更"无法表达，能表达的是「顺序是否**可能**被打乱」：容器被**多个函数**写，或**读取点所在函数自己也写**它 → 隔离；只有一个写入函数且不是读取者 → 保持共享。新增 `HostIR.container_writers()` + `_ValueNormalizer._summary_identity_is_merged()`。
    - 实测正好切开两类：`prefix0/1/2.back()` 三个变量转为隔离，`max(actualSeqQlen)` / `max(actualSeqKvlen)` 保持共享，19 维的 `free_vars` 一个没动（这次的收益不在数字上，在于不再伪造等式）。
    - **顺带纠正一处成本认知**：K6 **不会**因为树里有 `LOOP_ELEMENT` 就丢弃维度 —— 被 `omit` 的 5 个维度全部是 F.13 修法四的 `unmodelled_variable`。含自由变量的维度照样参与约束合取，丢的是 `_sat_caveats` 里的判决置信度（SAT 降级为 `unknown`）。所以闭合一个 `back()` 的收益是"把 unknown 变成判决"，**不是**"补回缺失的约束"。

15. **IR 补强：类型化变更记录 + 成员调用接收者（2026-07-31）**。两项都为"容器在读取点前被改过吗"服务，而这个问题此前完全不可判定。

    - `WriteRecord.kind` / `WriteEvent.kind` ∈ {`assign`, `append`, `replace`, `shrink`}。`append` 的 RHS 是**一个元素**而不是容器的新值 —— 不区分它，`size(v)` 就会被求成最后一次 `push_back` 的元素。`_CONTAINER_MUTATORS` 同时扩到 `clear` / `pop_back` / `pop_front` / `erase` / `resize`（`shrink`）与 `assign` / `swap`（`replace`）；改端操作没有可写的新值，以**空 RHS** 记录，只为让"这里变过"可见 —— 一个不留痕的 `clear()` 与"没有写"无法区分，而任何关于 `back(v)` 的推理都会在一个看不见的写序列上进行。FAG 实测：1795 条字段写里 35 条 `append`，3126 条局部写里 11 条 `append` + 3 条 `replace`（三处真实的 `.assign(...)`），**零条 `shrink` —— 因为这棵算子树里根本没有 `clear` / `pop_back` / `erase` / `resize` 调用**（已全文搜索确认，不是漏提）。
    - **`CallSite.receiver`，以及我自己造的一个坑。** 第一版把它门闩在 `cursor.kind.name == "CXX_MEMBER_CALL_EXPR"` 上，结果 3461 个 call site **一条都没填上**。根因：**本机 libclang 的 `CursorKind` 里没有 `CXX_MEMBER_CALL_EXPR` 这个成员**，`v.clear()` 一律以 `CALL_EXPR` 到达，门闩恒假。`walk()` 里那句 `kind_name in ("CALL_EXPR", "CXX_MEMBER_CALL_EXPR")` 长期靠前者兜住，看上去像是在分派成员调用 —— 我正是被它误导的，已就地加注释。
    - **去掉门闩不能照抄，`_receiver_path` 必须同时收紧。** 它原本只在 `_record_container_write` 里用（那里已知调用是容器 mutator，第一个孩子必是 `MEMBER_REF_EXPR`），所以有一条"第一个孩子的点分路径就算接收者"的宽松兜底。用到全部 call site 上，这条兜底会把 `std::max(a.b, c)` 报成"在 `a.b` 上的调用"——命名空间引用被跳过后，下一个孩子是**实参**。改为只接受两种形态：`MEMBER_REF_EXPR` 且 spelling 等于方法名，或路径文本已被压平成以 `.方法名` 结尾。
    - 效果：**969/3461** 个 call site 有接收者，自由函数误判 **0**，`append + replace` 仍是 **49** 条（收紧没丢任何写记录），两次全量 `--refresh` 后 `CLOSED 14/19` / `free_vars 6` / `implicit_zero 211` / `unrecorded 0` 逐项不变。
    - **意外收获：读取点的程序序到手了。** 原以为要给 `FuncSummary.reads` 附行号，但 `back()` / `size()` / `begin()` 本身就是成员调用，`receiver` + `line` 直接构成有序事件流。`deterPrefixData.prefix1` 现在能看到 29 个成员调用，`push_back` 与 `back()` 的交错一目了然（`:96` 读+写、`:106` 读、`:116` 写、`:164`/`:165` 读、`:167` 写…）；`slicePrefix1` 是干净的 `:168` 写 → `:171` 读 → `:177` `begin`/`end`。这让 F.14 那条粗判据（"多个函数写就隔离"）有了升级为真正读写交错判定的可能 —— 当前方向保守，不急着改。

16. **写记录的两个静默缺口（2026-07-31）**。都是"IR 说的比源码少"，而下游把残缺的写序列当完整的用。

    - **成员路径上的整容器 `operator=`**：`_record_operator_assign` 的 `path.count(".") < 1` 限制放开，记为 `kind="replace"`。全集实测 **14 条**，全部是 `deterPrefixData.{prefix0,prefix1,prefix2,deterPrefix,deterPrefixAlign} = SliceVector(自身, step)`。
    - **`push_back` 的元素冒充容器定义式**：元素移入新槽 `FuncRecord.appends` / `FuncSummary.appends`，`assigns` 不再被污染。实测"容器的 `assigns` 条目是元素"降为 **0**，46 个元素一条不少地进新槽。
    - 效果：`prefix0` 的写序列由 7 条（全 append）补全为 **11 条**（4 `replace` + 7 `append`），`prefix1` 同样补到 11 条。全量单测 **301 passed**，`--refresh` 后 `CLOSED 14/19` / `INPUT_DERIVABLE 10/19` / `free_vars 6` / `implicit_zero 211` 逐项不变。
    - **为什么此前没出错答案，以及它锁定了 P1.4 的顺序。** 这 5 个路径全部被 `source_resolver.py:722-729` 的名字白名单短路成 `TILING_DATA` 根，`_chase_field` 从不追它们的写序列 —— 白名单**掩盖**了两个缺陷；去掉白名单（P1.4）会立刻激活它们。所以必须先让写记录诚实再动白名单，这是这两条插到 P1.4 之前的原因。
    - **`appends` 新槽顺手暴露了 P2 要处理的形态**：`deterPrefixData.prefix1 <- ['deterPrefixData.prefix1.back() + actualS1Outer * actualS2Outer', 'fBaseParams.deterMaxRound']` —— 自引用 `back()` 的前缀和递推，正是 `PrefixSumLast`。
    - **P1.1c（局部引用别名）经核实在 FAG 上无实例，不做**：host 侧的引用别名全部是 `auto &qShape = ...GetStorageShape()`，绑 `gert::Shape` 且纯读，没有一个绑到可变容器，也没有任何经别名的写。原调查把它列为"阻塞项"是按代码可能性而非本算子事实。

17. **按名字认 tiling 聚合体 → 按写记录认（2026-07-31）**。`_PARAMS_DERIVED_RE`（字面写着 `deterPrefixData`）与 `_AGGREGATE_FIELD_RE`（后缀 `Params|TilingData|PrefixData|SplitCore|compileInfo`）决定"这个符号是 host tiling 状态"，换一个算子改了命名就静默误分类。

    - 结构性判据：`HostIR.aggregate_heads()` = **字段被 host 写过的符号**。输入访问器天然不满足 —— 没有代码给 `context->GetInputShape(0)->GetStorageShape().dim` 赋值。新增 `SourceResolver.tiling_derived()`，4 个使用点（`resolve_symbol` 的 accessor 分支、局部 RHS 兜底、参数实参、`controllability._close_params_as_derived`）全部改用它；`_AGGREGATE_FIELD_RE` 随之成为死代码，已删；`_PARAMS_DERIVED_RE` 仅在**没有 IR 可问**时兜底。
    - **先修 H2/H3 才敢动这里**：白名单短路让 `_chase_field` 从不追 `deterPrefixData.*` 的写序列，正是它掩盖了那两个缺口。
    - 判据很紧：152 个 `class_fields` 里只有 **7** 个符号入选，名字正则能抓的**一条不漏**（missed = 0），另外多抓 5 个名字不像但确实是 host 填充的聚合体（`compileInfoPtr`、`tndBaseInfo`、`tndBandDeterRoundInfo`、`emptyTensorTilingDataRegbase`、`s1ValidIdx` —— 后者是 `vector<pair<>>`，`s1ValidIdx[i].first` 剥下标后成 `s1ValidIdx.first`）。输入访问器与只读别名全部排除（`queryShape.GetDim(0)`、`qShape.GetDimNum()`、`std::max(a, b)` 均为 False）。
    - 全量单测 **301 passed**（两条按名字断言的旧测试重写为按写记录断言，并补了"名字像 Params 但无写记录不得假设为 tiling 根"与"改名为 `cfg` 仍能闭合"两条）；重跑派生 `CLOSED 14/19` / `INPUT_DERIVABLE 10/19` / `free_vars 6` / `implicit_zero 211` 逐字段一致。
    - **诚实的边界**：零回归说明新旧判据在本算子上**结论等价**，不说明跨算子通用性被验证过 —— 多抓的那 5 个符号没有改变任何字段的结论，所以收益目前是设计上的，未经数据考验。同时判据现在**依赖写记录存在**：若某聚合体的字段写全在被 `_in_scope` 过滤掉的 TU 里，它会降级为 `TILING_DATA_NO_WRITER` 而不是被假设成 tiling 根 —— 方向是保守的（变成 gap 上报，不是假 closed）。

18. **exact 却不可驱动：分类字段展开到输入条件（2026-07-31）**。`IsPse` / `IsAttenMask` / `IsTnd` 被标 `exact` 但根是 `TILING_DATA` —— 知道它等于什么，却无法用测试输入驱动它。

    - **根因不在 `_chase_writes`**（那条"多常量写 → host 根"是合理的保守，且 `Atom` 本就没有承载分段值的槽），而在 `derive_key_fields._expand_named_const_cmp`：字段 vs 具名常量的比较，字段侧只做 `_expand_surface`，于是 `_chain_sites` 那套现成的 `Ite(guard, value, …)` 机制从未被调用，字段停在表面叶子、被 resolver 归为 host 状态。
    - 改为**尝试展开 + 两道关**。质量关（`_reduces_to_inputs`）决定是否采用：展开只有在把该字段完全化归为可控/平台锁定根时才是进步，若仍留下 host 状态、自由变量或 `Unknown`，就丢弃并回到与改动前完全相同的浅展开。预算关（`CLASSIFIER_PROBE_NODES = 4000`，配合新增的 `_node_ceiling`）只限制**试探的代价**，不参与判定。
    - 结果：`IsPse` / `IsAttenMask` 从 `TILING_DATA` 变为 **`INPUT_SHAPE` + `OPTIONAL_INPUT_PRESENCE`**（243 / 266 字符），**`INPUT_DERIVABLE` 10/19 → 12/19**；其余 17 维 exactness / free_vars / 根集合逐项不变，`CLOSED` 仍 14/19，`free_vars` 仍 6，耗时 27.7s → 29.2s。全量单测 **303 passed**，另补 4 条钉住两道关的用例。
    - **IsTnd 明确不做**。调查建议"只链 `GetShapeAttrsInfo` 的 5 条 layout cascade"（约 532 字符、根变 `ATTRIBUTE`），但后续 `SupportTrans2BS2N2GD` / `SetSplitAxis` / `DoSparse` 会改写 `layoutType`；忽略那 3 条写会报出一个"由 `inputLayout` 唯一决定"的值，而真实 host 在部分路由下已是 `BS2N2GD` —— 失败方向是**替换成无根据的确定值**，正是最该避免的那个。全链则是 8 写 / 18 guard / ~43k 字符 / normalize MemoryError。现状 `exact + TILING_DATA + input_derivable=false` 能力受限但诚实，`layoutType` 的阻塞归入 P2 一类。判据用**无自指**（`_writes_are_self_routing`：任一写点的 RHS 或 guard 提及该字段本身）而非"写条数"这种武断门槛 —— 自指既是爆炸的根源，也是"先设值再路由改写"的标志。
    - **踩过的坑**：第一版判据只有"无自指"这一关，结果 `IsBn2MultiBlk` 变 `unresolved`（185s）、`IsNEqual` 从 exact 退化、耗时 372s。加上质量关后仍有 `SplitAxis` → `unresolved`，根因是**被拒绝的试探仍在消耗全局 `MAX_NODES`**，累积把它推到了预算上限；`_snapshot`/`_restore` 补上 `_nodes` 后恢复。另外回滚缓存会让同一字段被反复试探（耗时的另一半），加 `_rejected` 记忆后解决。
    - `implicit_zero` 211 → 213：`IsPse` / `IsAttenMask` 展开后多了 2 个 if/else 链的零默认假设点，是诚实的新增而非回归。`IsNzOut` / `IsTndSwizzle` 表达式变大（15877→25542、16278→16613）但根与 free_vars 不变 —— 单个 operand 化归成功，维度整体仍被其他因素阻塞。

19. **`push_back(x)` 之后的 `back()` 就是 `x`（2026-07-31）**。`back(slicePrefix1)` 不是聚合、不需要量词、也不需要展开切片循环：`varlen_regbase.cpp:168` 无条件追加 `R1`，`:171` 读 `back()`，中间只隔一句读 `prefix0` 的语句。把它当未知数是在丢弃源码明写的值。

    - 规则 `LAST_PUSH_DOMINATES_BACK`（`derive_key_fields._last_push_dominates_back`），按形态匹配而非变量名：最后一次早于读点的容器变更是 `append` 且其守卫蕴含于读点守卫时，`back(v) := ` 该元素，随后继续正常展开（`R1` 因此被展开成完整输入表达式，而不是换一个名字的自由变量）。
    - **读点位置这一关是靠"唯一性"绕过去的，不是靠给 Expr 加位置。** Expr IR 刻意不带 file/line，补它要动所有构造 Expr 的路径。但 `back()` 本身是成员调用，已记为 `CallSite`（带 receiver / line / column）。于是新增 `HostIR.sole_member_read`：该函数内该容器**只有一个** `back()` 读点时位置无歧义，有多个就返回 None —— 表达式树无法告知自己是哪一个，此时把某次 push 的值钉到错误的读点会伪造一个源码没有的等式。
    - **必须绕开既有的写索引。** `writes_by_tail()` 与 `_local_defs` 都过滤空 RHS，而 `clear()` / `pop_back()` 正是空 RHS —— 用它们判"中间无破坏性操作"会在最需要看见的地方瞎掉。新增 `HostIR.container_events` 直接读 `writes + local_writes`，含空 RHS 事件，按 `(file, line, column)` 排序。
    - **第一版判据是错的，记下来**：要求 push 无条件（`not any(pc.is_decision …)`），结果 `free_vars` 一动不动 —— push 和 read 同在 `deterSparseType == DETER_BAND` 块内，两者都带这个守卫。正确的判据是 push 的守卫集合 ⊆ read 的守卫集合（read 可达 ⟹ push 已执行），这也正好拒掉"push 在内层 if、read 在外层"。另要求 push 的守卫都不是 `guard_clause`：那种记录弱于真实，集合比较看不到它真实的额外条件。
    - 只对**局部**容器生效。`deterPrefixData.prefix1` 在 6 个函数里被 push，任何被调函数都能经 `this` 改它，"中间没发生别的事"无法由单函数事件序列判定。另外三道关：push / read 都不在循环内（回边让文本序不等于程序序）、窗口内没有把容器交给别的函数（by-ref 可改末元素而不留写事件）、窗口内该容器上没有非只读方法调用（含我们没有规则的方法）。
    - 顺带补齐：`WriteRecord` / `WriteEvent` 加 `column`（4 个构造点），`_assign_ssa` 排序键由 `(file, line)` 改为 `(file, line, column)` —— 同行两次写此前拿到的是任意相对版本号。
    - 效果：**`free_vars` 6 → 5**，`SplitAxis` 表达式 56556 → 56968 字符（`R1` 展开后的完整式子比一个变量长），`CLOSED 14/19` / `INPUT_DERIVABLE 12/19` / 各维根集合不变。`implicit_zero` 133 → 136：`R1` 链条更深，多走到 3 个 fallthrough 无声明初值的点，是诚实新增。单测 **+17 条**（每个拒绝条件一条），全量通过。

20. **有界基数摘要：`size(a) + size(b) > 36` 恒假（2026-07-31）**。这一步消掉 `size(syncRounds)` 与 `size(syncRoundRanges)`，`free_vars` **5 → 3**。它要证的不是任一容器有多大，而是**两者之和**有多大 —— 各自定界给出 36+36=72，settle 不了这条守卫；对和定界才行，而这需要把两个 `push_back` 看作在争夺同一批循环迭代。

    证明链（每一环都从 IR 结构读出，没有按名字特判）：容器在 `CalcleTNDDenseBns2DeterParam` 局部声明且默认构造 → 两次 `push_back` 落在同一个 `for (coreId = 0; coreId < CORE_LIST_NUM; ...)` 内 → 该循环 trip = 36 → 两次 push 的守卫互为 `if/else` 两侧，一次迭代最多产出一个元素 → 和 ≤ 36 → `> CORE_LIST_NUM` 在 Z3 下 UNSAT → 早退分支不可达，守卫连同它提到的两个 `size()` 一起消失。

    - **原以为需要「枚举语义互斥」，取证后发现不需要。** 事前判断是 Dense/Band 两个生产者共享容器、要靠 `deterSparseType == DETER_DENSE` 与 `== DETER_BAND` 互斥来防止相加。实际上这两个函数**各自持有自己的局部 vector**，根本不是同一个对象；跨调用点取 max 而非求和就够了。这也是为什么下面 C3 做的是「容器身份归一」而不是「守卫归一」。
    - **C1 `CtrlNode.init_value` / `step`**：trip count 在 IR 里此前无诚实来源（`condition` 不含初值和步长，`snippet` 被截断）。只在 `for` 三个头子句齐全时从 AST 读，其余一律 `None`。顺带修掉一个既有 bug：`for (i = 0; ...)` 的赋值式初值是 `BINARY_OPERATOR`，被 `_loop_header` 当成了循环条件。
    - **C3 容器身份跨函数归一**（`loop_summary.resolve_param_container`）：从消费者的形参反查调用点实参，再正向追出该对象的全部 mutation（含被调函数内的 append）。追不完就拒绝 —— 逃逸进未知函数、我们没有规则的方法、`std::move`，任一出现即无上界。**多调用点分列不合并**：两个调用方各自的 vector 是两个对象，合并会把一方的 mutation 记到另一方头上。
    - **按值形参这一点故意不区分。** `CalculateSyncRound(std::vector<...> syncRounds)` 是按值传的，callee 内对形参的改动回不到调用方。当前一律追踪，方向是**高估**（上界只会更大），安全；要精确需要给 `FuncSummary` 加形参类型，是另一件事。
    - **C4 互斥判定改成一次 SAT 查询**（`guards_exclusive`）：`if/else` 与 `x == A` / `x == B` 都只是「合取不可满足」，不必两套规则。解析不了的守卫**兜底成不透明原子而不是丢弃** —— 丢弃会削弱合取、让「判不出」静默变成「不互斥」；留成原子则 `c ∧ !c` 照样 UNSAT。局部变量按函数限定作用域，成员不限定：两个函数各自的 `i` 是两个变量，`fBaseParams.deterSparseType` 在两个函数里是一个。
    - **修掉一个既有 bug：无初值声明被记成自指初值。** libclang 给 `std::vector<T> v;` 挂了一个隐式默认构造 `CALL_EXPR`，它零子节点、extent 只盖住声明符，读 token 得到变量名本身 —— 于是 `fr.locals` 里长期存着 `syncRounds -> "syncRounds"`。`local_writes` 因为 `rhs == name` 的过滤没被污染，但 `locals` / `assign_lists` 没有这层保护。判据：最后一个非类型引用子节点若是**无参** `CALL_EXPR` 则视为无初值（`std::vector<int> v(n)` 有子节点，仍算有初值）。
    - **新增 `LocalDecl` 表，与 `local_writes` 分开。** 「声明了但没初始化」是事实，而不是赋值；喂给定义链会在期待值的位置放一个空 RHS。而「容器开局为空」正是整条上界的第一个前提，没有它就无从谈起。
    - 效果：`free_vars` **5 → 3**，`implicit_zero` 136 → 135，其余 18 维的字符数与自由变量数**逐项不变**（19531 / 80462 / 25562 / 16637 全部对齐）。单测 **+62 条**（`test_loop_bounds` / `test_container_flow` / `test_event_exclusion` / `test_cardinality`），全量 **450 passed**。
    - **K6 判决没有变化，原因见上文「这条验收标准当前测不出来」** —— 瓶颈在剩下 3 个自由变量，不在 `size()`。

**剩余 67 条过近似的分布**（口径：`undecided_guards` 条数，非变量数）：

| presort | 条数 | 归属 |
| --- | ---: | --- |
| reachability（`__reached_*`） | 29 | 3.B 调用切片，方案已明确 |
| unmapped（主要 `actualCalcS2Token`） | 20 | out-param 建模 + resolver 层环 |
| scheduling（coreIdx 系） | 11 | 见下 |
| unknown（`array_subscript` 等） | 7 | 数组元素建模 |

### E. 对齐验收口径

```powershell
python .probe_cache/diag_align.py
# 期望: fields_fail=0 | inv_fail=0
```

I2/I3 仍是**过近似**（未建模 `GRAPH_FAILED` 收窄），结构性「能支撑蕴含」即可，不算假成功。

### G. 五维回归求解器，判决从 1 条推到 6113 条（2026-08-01）

| | 2026-07-31 16:00 | 2026-08-01 05:26 |
| --- | ---: | ---: |
| `dimensions_compiled` | 14/19 | **19/19** |
| `unreachable` / `unknown` | 1 / 8704 | **6113 / 2592** |
| `free_vars` | 3（其中一批是假的，见 G.5） | **9** |
| `implicit_defaults` | 135 | **22** |
| K6 全量一轮耗时 | 跑不完（>6h 未返回） | **约 19 分钟** |

`CLOSED 14/19` 与 `INPUT_DERIVABLE 12/19` 两个数**一格没动**，这是符合预期的：本轮动的是「判决」而不是「闭合」，两者由不同的东西卡住。

**G.1 测试此前是静默 skip 的。** `conftest.py` 把路径写死在 `PR-review/...`，实际布局在 `d:\TEST\`，于是所有依赖 FAG / CANN 的用例一律 skip 而计入 passed。新增 `uo_init/paths.py` 统一解析（显式参数 → 环境变量 → 候选探测 → 报错说明怎么设），并把 skip 改成显式失败。在此之前的任何「全量通过」都不构成证据。配套把 CANN 从 `.run` 剥到 `_cann/pkg`，再由 `scripts/cann_slim.py` 按 include 根裁到 `slim`（裁的是整个 include 根而不是当前算子读到的闭包，换算子不会缺头）。

**G.2 未知裸符号不再牺牲整维**（批次 B1/B3）。`_Rewrite` 读到 `m0Max` 这类读不出的符号就 `raise _Unadaptable`，整个维度退出求解 —— 五维缺席的直接原因。改为交给 `_Isolator` mint 一个维度隔离的自由变量，**绝不跨维共享**（共享等于凭空建立等式，会造出假 UNSAT）。同时凡 mint 过 local free var 的维度强制 `exact=False`，保证 SAT 侧只会给 `unknown`，不会误报 `reachable`。`dimensions_compiled` 由此 14/19 → 19/19，`omitted` 清空。

**G.3 求解器从跑不完到 19 分钟。** 三处，缺一不可：

- **DAG 被展开成了树。** `_compile_bool` / `_compile_value` / `normalize_expr` 都没有 memoization，磁盘上共享良好的 DAG 一进 Z3 就按引用次数指数展开。加 memo 后最大表达式的编译从「不返回」变成秒级。
- **超时形同虚设。** `timeout_ms` 只在 Z3 自己愿意检查时生效，落进 QF_NIA 的死循环里它不看。改为 `rlimit`（确定性步数上限）+ 线程看门狗（超 `hard_timeout_ms` 直接中断 context），并在中断后**重建 context** —— 被中断的 context 会留在 wedged 状态，复用它后面每一次 `check()` 都立即返回 unknown。
- **问题本来就不必整体解。** 按自由变量不相交把 19 维切成独立分量，各自求解并按分量的维度取值做投影缓存。同一个分量在 8705 个 key 里反复出现，缓存命中后整轮只剩 430 次真实查询。

**G.4 字符串字面量此前和标识符没法区分。** IR 里 `"TND"` 和 `TND` 长得一样，于是 `layout == "TND"` 与 `layout == "BSH"` 无法判互斥。给字面量加标记后，两个不同字面量天然不等，`unknown` 8704 → 5952，`unreachable` 1 → 2753。

**G.5 局部量常量折叠有一个会缩小可行域的 bug（本轮最重要的正确性修复）。** `source_resolver` 遇到「所有 RHS 都是常量」的局部量就折成单个 `CONSTANT` 原子，但**三元表达式的多个分支也满足这个条件** —— `deterTilingSplitMode` 有三个可能取值，被折成了其中一个。更糟的是 `predicate._leaf` 拿的是 `const.text`（标识符的**名字**）而不是 `const.symbol`（折出来的**值**），所以比较的是变量名。两个 bug 叠加，把「可能是 0/1/2」写成了「恒等于某个名字」，这是**缩小**可行域，直接违反 UNSAT 可信的前提。修法是新增 `_picks_between_constants`：全常量但存在 `Ite`/`Select` 选择的，不许折叠。`unknown` 5952 → 2592，`unreachable` 2753 → 6113，`free_vars` 49 → 55（那 6 个本来就在，只是被假常量盖住了）。

**G.6 隐式初值的四连修，55 → 9。** A2 把 `fallthrough = Const(0)` 换成 mint `VAR_INIT_*` 之后，`free_vars` 3 → 49、一批字段降级为 `overapproximated`。这不是退步而是把「假的确定」换成「诚实的不确定」，随后四处修复是真的把不确定消掉：

- **转发状态码的早退认不出来**。`_ERROR_EXIT_RE` 只认 `return GRAPH_FAILED` 这种字面常量，而 `if (ret != ge::GRAPH_SUCCESS) { return ret; }` 是转发，被当成正常路径，于是后续写入都挂上了一个本不该存在的守卫。加 `_STATUS_FAILURE_RE` 识别失败检测式。`free_vars` 55 → 49，`implicit_defaults` 135 → 115。
- **带初始化器的块作用域声明**。`int64_t seqQShapeSize = ...;` 写在 `if (TND)` 里，链式分析问「不是 TND 时它等于几」并 mint 自由变量。但这个问题不成立：C++ 作用域保证这个局部只能在声明它的块内、声明之后被读，守卫说的是「进入哪个块」而不是「有没有值」。`_is_declaration_site` 要求是局部、有初始化器、且行号就是声明行（成员/形参/出参一律排除，它们活得比这些写点长）。`free_vars` 49 → 10，`implicit_defaults` 115 → 27。
- **穷尽性判定不该按全局判**。`_paths_are_covered` 要求所有写点在同一函数才认穷尽，于是一个成员在 A 函数里四个 layout 分支写全、又在 B 函数里被写一次，就判不出穷尽。改为**按函数分别判**。
- **但对成员这样判是不健全的**（这一步先把 `free_vars` 从 9 顶回 15，暴露了此前藏着的不健全假设，然后才修对）。函数内部写全，不代表这个函数一定会被调用；一个只在条件里调用的 helper，跳过它的那条路径读到的还是旧值。所以成员额外要求 `_always_runs`，而局部量不需要 —— 跳过这个函数的路径根本没地方读它。`_is_local_of` 做这个区分，最终落在 9。

**G.7 序列化往返丢证据，K6 把 `exact` 高报成 14。** `to_dict()` 写出的 `root_vars` / `undecided_guards` 与 `_to_field()` 读回的键名和格式对不上，读回来是空的，于是 K6 看到的每一维都「没有未决守卫」。实际 `exact` 是 12。补 `_roots_of` / `_guards_of` 两个还原器，并加了一条往返测试钉死。

**G.8 当前卡在哪：143 次求解超时。** 全量一轮共 430 次分组查询，287 次**在 0 秒内**判为 UNSAT，143 次烧满超时预算（合计 493 秒）后 `canceled` —— 2592 个 `unknown` 全部来自这里。值得注意的是超时不只发生在那个 13 维的大分量上，`InputDType`、`OutDType`、`IsDrop` 这些**单维分量也解不出来**，所以瓶颈不是组合爆炸，而是单维表达式本身的算术形态：tiling 算式里变量乘变量再除以第三个变量，编译出来是 QF_NIA，理论上不可判定。

**G.9 松弛实验的结论是否定的，但把真凶指出来了。** 思路是：把非线性算子换成全新的无约束变量使系统线性化，这是**松弛**（可行域只会变大），所以松弛后的 UNSAT 对原系统仍成立，据此给出的 `unreachable` 健全；松弛后的 SAT 则什么都不能说明。脚本 `scripts/_probe_nia.py`（`--collect` 采集、`--relax` 分四档重解），抽 12 个不同形状的组合：

| 档位 | 结果 | 耗时 |
| --- | --- | ---: |
| 原样 | 12 unknown | 39s |
| 只松弛 `x * y` | 12 unknown | 28s |
| 加上 `/` `%`（除数非常量） | **12 sat** | **1s** |
| 连常量除法一并松弛 | 12 sat | 0s |

**乘法不是瓶颈**——松弛掉之后一个都没变。真正卡住求解器的是**整数除法与取模**，tiling 里遍地 `CeilDivide`，一旦松弛立刻 1 秒返回。但返回的是 SAT，松弛下的 SAT 不可用，所以这条路换不到任何 `unreachable`，**不再往下走**。

这个结果顺带确立了一件更要紧的事：**即便求解器算得动，这 2592 个也还是 `unknown`**。参与的 7 个维度是 `overapproximated`，SAT 会被 `_sat_caveats` 降级，只有 UNSAT 才能定案。所以出路不在求解器性能，在于让那些维度变精确 —— 见 G.10。

**G.10 五个 `overapproximated` 维度全部卡在假环上。** `SplitAxis` / `DeterType` / `IsBn2MultiBlk` / `IsNzOut` / `IsTndSwizzle` 的 `note` 里都写着 `CYCLIC_DEFINITION`，涉及的名字只有五个：`fBaseParams.blockOuter`、`s2Inner`、`totalRound`、`fBaseParams.isDeterministic`、`s1Inner`。

其中 `s1Inner` / `s2Inner` 已确认是 **save / modify / restore**（`..._tiling_normal_regbase.cpp:897-929`）：先把成员存进同名局部，中间有条件地翻倍，末尾再从局部还原。展开局部 `s2Inner` 会读 `fBaseParams.s2Inner`，而后者的最后一个写点又读那个局部，于是绕回起点。源码里并没有环 —— 第 898 行的读发生在第 907 行的写**之前**，环完全是位置不敏感的展开造出来的。

`_expand_name` 已经有 `_prev_version` 机制处理 `x = f(x)` 这类顺序赋值，但它只在**同一个名字的写点链**内有效；这里绕环要经过另一个名字（局部量），拿不到前一版本就只能判环。

**G.11 程序点敏感的展开（批次 I1/I2 已落地）。** 核心是一句话：一个名字的值取决于**在哪里读它**。`_visible_defs` 在取定义池时滤掉「此刻还没跑到的写」，`_runs_before` 负责给出理由，缺理由就保留：

- **同函数比行号**。写在读下面就不算数。
- **共享循环是例外**。同一个循环体内，读下面的写会在下一轮先于这次读，所以照留。只有**同时包住两者**的循环才算，仅包住写的循环在读之前已经跑完。
- **跨函数靠调用点对齐**（`_read_lines`）。helper 里的读，站在调用者的角度发生在**调用那一行**，所以调用行下面的写与它无关。这一步只在整条调用链都「最多进入一次」（`_runs_once`：唯一调用点、不在循环里、调用者同样如此）时才走，否则第二次进入时上一轮的写早已生效，比行号就会漏掉真实发生过的写。
- **缓存键带上「哪些写在视野内」**。同一个名字在函数里的两处读是两个值，不能共用条目。只有真丢了写才有这个后缀，所以绝大多数查找的缓存行为不变。

踩到一个反直觉的坑：过滤会让**穷尽性判定**失真。`if (A) { n2 = 1; g = n1/n2; } else { n2 = 2; g = n1/n2; }` 里，在 A 分支读 `n2` 会把 else 分支那次写滤掉，剩下的写不再覆盖所有路径，于是给一条根本不存在的路径造了个初值变量 —— `implicit_zero` 一度从 22 涨到 37，`IsDNoEqual` 从 `exact` 掉级。修法是把两件事分开：**取值用过滤后的写，判覆盖用全集**（`_chain_sites` 的 `pool` 参数）。

效果（`scripts/_probe_derive.py`，全量单测 493 passed 无回归）：

| 指标 | 修前 | 修后 |
| --- | ---: | ---: |
| CLOSED | 14/19 | 14/19 |
| unique free_vars | 9 | **7** |
| implicit-default 站点 | 22 | **6** |
| SplitAxis 自由变量 / 表达式 | 7 / 56391 字符 | **5 / 46272** |
| IsTndSwizzle 自由变量 | 6 | **4** |

`deterTilingSplitMode == 1` / `== 2` 这两个卡住 5 维的自由变量**消失了**，`fBaseParams.isDeterministic` 的假环也解开了。诊断脚本 `scripts/_probe_cycle.py`：它把「环在哪一层被判定」和「哪些查找因位置丢了写」分开报，是这轮定位的主要工具。

**G.12 读点也是条件（批次 H2）。** 写点看起来不穷尽，未必真有「没赋值就被读」的路径 —— 因为**在哪里读**同样是个条件。`fBaseParams.bandIdx` 只在 attenMask 存在时被写（`ProcessSparseModeInfo` 开头有 attenMask 为空就 return 的提前返回），也只在同一前提下被读，两者合起来不留任何「未写先读」的运行。

`loop_summary.guards_cover(read_conds, write_conds)` 把这件事交给求解器：查询 `read ∧ ¬(∨ write)`，`unsat` 才算数。方向上处处保守 —— 读不懂的守卫，从写这边丢会缩小析取，从读这边丢会削弱前提，两者都让蕴含**更难**证明；`sat` / `unknown` / 超时一律当作没证明，假设原样留着。

效果：`implicit_zero` 22 → 19，`fBaseParams.blockOuter` 从卡住 5 维降到 2 维，SplitAxis 自由变量 5 → 4，IsBn2MultiBlk 5 → 4，DeterType 7 → 6。K6 全量从 19 分钟降到 **5.5 分钟**（表达式小了一大截），判决数不变（6113 / 2592）—— 与 G.9 的结论一致：`unknown` 卡在求解器超时，跟自由变量多少无关。

`bandIdx` 仍未被证下来（还卡 5 维）。它的写守卫是 `!(attenMaskShape == nullptr || attenMaskShape->GetStorageShape().GetDimNum() == 0)`，读点那侧的条件多半拼写不同，原子对不上 —— 待查。

**还剩一个环**：`s1Inner` @ `FuzzyForBestSplit`。它的读点是 `('?', 0, ...)` —— 来自函数摘要的局部量表，只有右值没有行号，位置过滤无从下手。而那个函数本身只有四行直线代码（`auto s1s2TemplateSize = GetS1S2TemplateType(...)` → `s1Inner = s1s2TemplateSize.first / 2` → `return std::tie(s1Inner, s2Inner, dInner)`），源码里没有环，怀疑是 pair/tuple 取分量时绕回了同名的返回槽，属于另一类问题。

**G.13 6113 个 `unreachable` 里的绝大多数是假的 —— 变量身份坍缩（批次 C 的真答案）。**

起因是一句质疑：这些 key 看着都该可达。查下去发现判决数虽多，**独立判断却极少**：K6 把维度按「不共享自由变量」拆成 10 个分量（一个 10 维的大分量 + 9 个单维），8705 个 key 只落成 430 次分组查询。逐条抽出来看，287 条 unsat 的 `unsat_core` 里往往只有**一个**维度的定义加上它自己的取值断言 —— 那不是「多维互斥」，而是「这一维产不出这个值」。

再逐维单独问一遍（`scripts/_probe_dimvals.py`，把一维钉住、其余全放开），整张表只剩 **12 个取值**被判死，其中 6 个在合法 key 里只出现 1 次（SEL 几乎不选），真正的杀伤全来自 6 条：

| 判定 | 杀掉的 key | 该不该死 |
| --- | ---: | --- |
| `IsTndSwizzle=1` | 1984 | 不该 |
| `DeterType=4` | 1984 | 不该 |
| `DeterType=3` | 1824 | 不该 |
| `SplitAxis=5` | 800 | 不该 |
| `IsNzOut=1` | 640 | 不该 |
| `DeterType=1` | 544 | 不该 |
| `IsRegbase=0` | 0 | **该**：该维恒为 1 |
| `OutDType=0` 等 5 个 `=0` | 各 1 | **该**：穷尽 if-else 链末端够不着的 fallthrough |

矛盾点在于：这 6 条全出自 **overapproximated** 维度。带自由变量意味着可行域只会被放大，**放大之后反而无解**，只能是有什么东西在收缩它。

收缩的东西是变量名。`IsNzOut` 的写点是 `splitAxis == BN2GS1S2 && d > 64 && d < 128 && d % 16 != 0 && … && s1 >= NZ_OUT_MIN_S_SIZE && s2 >= …`，而 `d`、`s1`、`s2` 在 IR 里**全叫 `VAR_SHAPE_GETSTORAGESHAPE`**：一个变量同时背着 `gt64 / lt128 / ge2048 / le512 / le640`，Z3 当然判 UNSAT。`VAR_ATTR_GETATTRS` 更狠，layout 的四个字符串和 sparse_mode 的整数挤在一个符号里。

这个风险 `VarSpec.identity_merged` 的注释里写着，但结论错了半句：

> Within one expression the merge is a harmless over-approximation — the variable is free, so it can take whichever value that occurrence needs.

只有当变量在表达式里**只出现一次**时这句才成立。出现 44 次时，Z3 强制这 44 处取同一个值。所以 `_Isolator` 那套「按维度隔离」防住了跨维度的假等式，却防不住维度**内部**的 —— 而后者才是这 6113 条的来源。

**修法是把身份解析准，不是把冲突绕开。** `var_id_for` 早就支持 `VAR_SHAPE_QUERY_D2` 这样的命名，`VAR_DTYPE_QUERY` / `VAR_ATTR_SPARSE_MODE` 也早从 opdef 声明好了，`DIM_2=2` / `QUERY_INPUT_INDEX=0` 也都在 `named_constants` 里躺着 —— 缺的只是把它们接上：

1. `_const_int` 让序号和轴号既认字面量也认命名常量。源码里 `GetDim(DIM_2)` / `GetInputShape(QUERY_INPUT_INDEX)` 远多于裸数字，只认字面量等于全丢。
2. `_operand_symbol` 用 opdef 的声明顺序把位置翻译成操作数名（`GetInputShape(1)` → `key`），`VariableModel.operand_names()` 提供这张表。
3. `_inherit_operand` 让操作数沿调用链传下去，且**不要求 root 相同** —— 外层访问器决定读什么（shape / dtype / format），接收者决定读谁，所以 `GetInputDesc(0)->GetDataType()` 是 query 的 dtype。局部别名（`auto &queryShape = …`）走 bindings 追一层。
4. 轴号在 Atom 逐层转发时会掉，9 处转发点补 `index=`（字段写点回溯、局部 RHS 追踪、helper 返回值等）。

`SourceResolver` 构造时模型还不存在，所以加了 `adopt(var_model)`，在 `assemble_kb` 里模型就绪后交接。

效果：`VAR_SHAPE_GETSTORAGESHAPE` → `VAR_SHAPE_QUERY_D0` / `VAR_SHAPE_QUERY_D2` / `VAR_SHAPE_KEY_D0`，`VAR_ATTR_GETATTRS` → `VAR_ATTR_INPUT_LAYOUT` + `VAR_ATTR_SPARSE_MODE`，`VAR_DTYPE_GETDATATYPE` → `VAR_DTYPE_QUERY`。派生侧指标一个没动（CLOSED 14/19、`free_vars` 7、`implicit_zero` 19），502 单测全绿 —— 这一轮只改变量身份，不改派生。

> **改完必须 `_probe_derive.py --refresh`。** `fag_bundle.pkl` 里 pickle 了 resolver 实例，旧对象没有新字段，直接跑会让 19 维全部 `unresolved`。

新增探针：`_probe_unreach.py`（抽出分组查询里的矛盾组合，按杀伤量排序）、`_probe_dimvals.py`（逐维逐取值单独问，最小证据表）、`_probe_branch.py`（拆 if-else 链逐分支验守卫；对 DAG 展开达 46 亿节点的维度不适用）。

---

### H. 输入合法性前提：拒绝语句是唯一的合法性定义（2026-08-01）

起因是 `OutDType` 报「host 编出 4/5/6，模板只声明 0–3」。查下去不是模板漏声明，是**推导把失败路径上的值当成了可达**。

| 指标 | 修前 | 守卫挂在写点上（中间态，回归） | 提为前提（现在） |
| --- | ---: | ---: | ---: |
| CLOSED | 9/19 | 9/19 | **12/19** |
| INPUT_DERIVABLE | 6/19 | 6/19 | **10/19** |
| `free_vars` | 47 | 47 | **9** |
| `implicit_zero` | 68 | 68 | **21** |
| 最大表达式 | 151629 | 151629 | **56494** |

#### H.1 为什么原来会把 4/5/6 当可达

`_guard_clause_negation` 原先对 `if (c) { return GRAPH_FAILED; }` 直接返回 None，理由写在注释里：「拒绝非法输入的守卫，取反只是重述『输入合法』，而这已经假设过了」。

**这个前提不成立。** 系统里没有任何地方编码「输入合法」——`queryType` 就是个自由变量，值域是整个 dtype 枚举。算子说明自己接受什么的**唯一**方式就是拒绝其余：

```cpp
if (queryType == DT_FLOAT8_E5M2 || … || queryType == DT_HIFLOAT8) return ge::GRAPH_FAILED;
fBaseParams.outDtype = fBaseParams.inputDtype;      // 只有合法 dtype 能走到
```

跳过它，HIFLOAT8 就成了可用输入，`OutDType = 6` 自然「可达」。

#### H.2 挂成守卫是错的，必须提为前提

第一次修法是让它照常传播，结果 `free_vars` 7 → 47：写点有了守卫就不再是无条件写，fallthrough 需要初值，于是 mint 了一堆 `VAR_INIT`，值域反而更宽。

根子在于**这个条件不属于任何单个变量**。它描述的是「这次调用的输入是否合法」，而失败的调用根本不产生 key。所以它是整个推导的前提：

- `PathCond.kind = "bailout"`，`is_bailout` 为真、`is_decision` 为假（它不二分路径，另一侧到不了这里）；
- `WriteEvent.guards()` 排除 bailout，写点回到无条件；`premises()` 单独取出；
- `HostIR.legality_premises()` 汇总去重，`_derive_premises()` 用与维度相同的展开器把每条展开成 IR，写进 `HostDerivation.premises`。

#### H.3 前提必须带自己的上下文

嵌套在判断里的拒绝表达的是**条件性**要求：

```cpp
if (dropMask != nullptr && …) {          // 只有传了 dropMask
    if (!hasDrop) return ge::GRAPH_FAILED;   // 才要求 keepProb < 1
}
```

按无条件读会把所有不带 dropout 的输入全拒掉（`IsDrop` 的 0 就是这么丢的）。所以每条前提是蕴含式 `到达该检查的条件 ⇒ ¬拒绝条件`；上下文里有 opaque 守卫时整条丢弃，不弱化成无条件。

#### H.4 两道健全性闸门

前提是**收窄**操作，错一条就会漏掉真可达的 key，比误报不可达更危险。所以只有干净的才用：

1. 展开后含自由变量（`VAR_LOCAL_` / `VAR_INIT_` / `VAR_UNMODELLED_`）→ 弃。「某个未知的东西为假」不构成对输入的约束。
2. 展开后**不含任何变量** → 弃。`if (!IsSameShape(dy, attentionIn))` 在调用读不出来时会折叠成裸常量，一条恒假的前提会拒绝所有输入（实测正是它把全部格子清空的）。

FAG 现状：26 条里 21 条可用。

> `_ERROR_EXIT_RE` 折叠成常量这件事说明**未知调用被当成 0** 而不是 Unknown，这个更深的问题会不会影响维度表达式本身，尚未查。

#### H.5 结果（全部经源码复核）

| 维度 | 前提前 | 前提后 | 源码依据 |
| --- | --- | --- | --- |
| `InputDType` | 1–6 | **1,2,3** | `ProcessQuantInfo:1148` 拒 FP8/HIFP8/INT8 系 |
| `OutDType` | 1–6 | **1,2,3** | 同上；`outDtype = inputDtype` 在拒绝之后 |
| `S1TemplateNum` | 64,128,512 | **64,128** | `GetS1S2TemplateType` 里 512 只在 HIFLOAT8 分支 |
| `S2TemplateNum` | 128,256,512 | **128** | 256 只在 FP8、512 只在 HIFLOAT8 分支 |
| `IsDrop` | 0,1 | 0,1 | H.3 修好之前一度错成只有 1 |

即：模板为 FP8/HIFP8 预留的档位还在，但当前 arch35 的 host 入口已经关闭。`OutDType` 的「契约冲突」是**假冲突**——`domain_violations` 目前仍按静态值域判定，没有用上前提，这处告警待改。

---

### I. 同名局部量跨函数串味：一处**收缩型**缺陷（2026-08-01）

前面所有近似都只往「放宽」一个方向偏，这条不是。它写出的是**错误等式**，会把本来可满足的 key 判成 `unreachable`——即假的不可达。发现自一次专门的收缩型假设审计（按「近似只允许扩大可行域」逐环节复核）。

#### I.1 现象

`_expand_name` 里有两处只按名字索引、不按函数限定：

1. **跨作用域缓存复用**——注释写的是「Same host state under another caller scope」；
2. **`_active` / `_prev_version`**——环检测与「上一版本」台账。

对**成员**（`fBaseParams.*`）这是对的：成员是全程序一个变量，写点也确实由 `_field_defs` 全局收集。对**局部量**则不成立：`DoSplit` 的 `s1Inner` 和 `FuzzyForBestSplit` 的 `s1Inner` 是两个变量。FAG 里有 **183 个局部名在多个函数中重名**，`s1Inner` / `s2Inner` / `blockOuter` / `s1Outer` 都在其中——正是卡住 5 个过近似维度和那个假环的名字。

写点本身其实是隔离的（`_all_defs_for` 对无点号名走 `_local_defs(name, fn)`），所以泄漏口只有上面那两处台账，它们绕过写点直接交换结果。

#### I.2 为什么这是收缩而不是放宽

拿到别的函数的表达式，不是「多一些可能取值」，而是**断言了一个不成立的相等**。合取里混进一条错误等式，Z3 会因为它与其它约束冲突而报 UNSAT，于是一个真实可达的 key 被判死。且结果**取决于展开顺序**——谁先进缓存谁说了算，这也解释了为什么假环的表现一直不稳定。

#### I.3 修法

新增 `_ident(name, fn)`：成员用裸名，局部量用 `fn::name`。`_active`、`_prev_version`、`_prev_read`、`_earlier_frames` 全部改用它；跨作用域缓存复用加 `"." in canon` 闸门，只对成员开放。

回归测试用两个各有一个 `s1Inner=7` / `s1Inner=9` 的函数。把 `_ident` 和缓存闸门临时退回原状后，两个测试都如实失败——`G` 的 `s1Inner` 拿到 `7`，另一场景下它被当成递归退化成裸名——确认测试确实抓得住这个 bug，而不是恰好通过。

#### I.4 代价与结果

| | 修复前 | 修复后 |
| --- | --- | --- |
| `CLOSED` | 12/19 | 12/19 |
| `free_vars` | 9 | 10 |
| `implicit_zero` | 21 | 21 |
| `max_chars` | 56494 | **380290** |

表达式规模涨 6.7 倍是**修复的必然代价**：先前 DAG 看着小，是因为它把不该合并的节点合并了。多出的 1 个自由变量同理——先前被错误复用掩盖。

> K6 重跑的判决变化（`unreachable` 6113 / `unknown` 2592 的去向）待补。

#### I.5 被它连带暴露的两个下游缺陷

表达式一变大、局部量一分家，两个一直存在但被掩盖的问题当场浮出来，都不是新引入的。

**（a）`decode_expr_dag` 是递归的，编码侧却早就是迭代的。**

`_dag_postorder` 的注释写着「Iterative because a derived expression nests deeper than the default recursion limit」，解码侧却漏了。只有**又共享又够大**的节点才配得到定义，剩下的内联成一条长脊，深度轻松上万。改成显式栈后，新测试在 `recursionlimit=100` 下解 5000 层——递归实现无论把上限调到多少都过不去。

> 这多半就是待办里那条**间歇性 native crash（约 10s 无输出、退出 -1、没有 traceback）**：Python 的递归上限能抬，C 栈抬不了，踩爆就是进程直接消失。仓库里还有 4 处 `setrecursionlimit(20000~200000)`（`_worker`、`z3_backend._deep_recursion`、两个 probe 脚本），都是同一个隐患，待逐个改成迭代。

**（b）软变量的类型是靠名字猜的，`VAR_SCHED_` 下面躺着两类东西。**

软化发生在子进程，父进程的 `var_model` 看不到那些 `VarSpec`，于是 `_reregister_soft_vars` 按 presort 桶重新声明。但 `VAR_SCHED_` 前缀有两个来源：

| 铸造点 | 形如 | 真实类型 | 含义 |
| --- | --- | --- | --- |
| `_soft_var` | `VAR_SCHED_<12位哈希>` | `bool` | 被软化的守卫 |
| `_scheduling_leaf` | `VAR_SCHED_COREIDX` | `int` | 遍历位置本身 |

桶只看得见前缀，一律声明成 `bool`。于是 `coreIdx == 36` 编译失败，**19 个维度全军覆没，8705 个 key 全部 `solver unavailable`**。这与注释里记载的 loop-element 类型被改写是同一个 bug 的第二次发作，说明「按名字猜类型」这个做法本身就该退役。

改法是让类型跟着记录回来：`Normalizer.var_types` → `FieldResult.var_types` → `UndecidedGuard.var_type`，父进程优先采信 worker 的声明，桶只作为缺省。顺带给 `Z3Backend._value` 的报错加上变量名——原来的消息只说「某个字面量不是布尔」，不说是谁，定位全靠猜。

---

### J. 同一个矛盾被反复求解：unsat core 问错了问题（2026-08-01）

K6 里有一层冲突学习：一组维度取值判成 `unsat` 之后，从 Z3 的 unsat core 里取出「真正相
撞的那几维」，记成一条最小冲突；后面任何包含这几维同样取值的 key 直接判死，不再进求解
器。UNSAT 单调，这个复用在原理上是对的。

问题在于「取出相撞的那几维」这一步。`_solve_group` 把整组维度的取值压成**一条** `and`
断言，标签就叫 `key`。core 里因此只可能出现两种东西：这一条 `key`，和各维的**定义式**
`derived:VAR_KEYDIM_X`。于是只能从「证明用到了谁的定义」反推「谁的取值相撞」——而这两
件事并不等价：一个维度的定义式可能因为证明路径经过它而进 core，它的取值却与矛盾无关。

后果是学到的冲突偏大。三维一组、真实矛盾只在 A、B 之间时，学成 `(A,B,C)=(1,1,0)`，换
一个 C 就不命中，同一个矛盾重新证一遍。**这是用户抱怨「求解太慢」的一个真实来源。**

它还带来一处测试脆弱性：core 具体包含谁取决于 Z3 内部状态，而 Z3 的全局 context 会被同
一进程里跑过的其它查询影响。`test_a_contradiction_is_proved_once_and_reused_on_the_rest`
因此**跑全量单测通过、去掉 `test_key_exactness.py` 就失败**——不是这个测试的问题，是被
测的契约本来就建立在运气上。

改法是让 core 回答被问的那个问题：每维取值**各自**带标签断言，标签 `asked:<dim>`。

| | 之前 | 之后 |
| --- | --- | --- |
| 查询形状 | 一条 `and`，标签 `key` | 每维一条，标签 `asked:<dim>` |
| core 能说什么 | 证明用到了哪些定义 | 哪些取值是矛盾必需的 |
| 学到的冲突 | 偏大，命中率低 | 就是相撞的那几维 |

`Z3Backend` 新增 `solve_terms(terms)`，`solve_expr` 委托给它；`_assert_tracked` 顺带补了
标签去重（两条断言共用一个 marker 时，后一条会顶掉前一条，查询会**静默少一项**）。

`_core_dims` 优先读 `asked:`，读不到才回退 `derived:`。但 `_assumed_in` 必须取**并集**：
它判断的是「矛盾有没有踩在被铸造的符号上」，少算一维就是少发现一批自由变量，把
`unknown` 说成 `unreachable`——这个方向的错误下游看不见。

### K. 让弱模型能答对：问题、证据、词汇表三处都在漏（2026-08-01）

准备用 `composer-2.5-fast` 实跑一轮 LLM 补洞时，先看了一眼 batch 里模型到底会读到什么，
三处都不成立。

**（a）问题文本是 IR，不是源码。** `UNMAPPED_SYMBOL` 类 blocker 的 `text` 取的是归一化
后的守卫，也就是整棵折叠表达式——`let $1 = (__reached_DoOpTiling && (!(((splitAxis(...`，
上千字符的内部记法，裁到 160 字还是个断句。它连聚类也聚错：FAG 里 35 条 escalating 守卫
分布在三个文件，共享的是「最后被折进了哪个表达式」而不是「要读哪段代码」。改成用证据的
源码原文（`evidence.snippet`）之后，三条 blocker 的文本变成 `inputLayout[0] == 'B'`、
`fBaseParams.n2 == 1`、`fBaseParams.splitAxis == SplitAxisEnum::BN2S2 && ...`——聚类结
果不变（确实只有三个问题），但现在是人和模型都读得懂的三个问题。

**（b）证据窗口是三行。** 问「这个循环算什么」却只给循环里的一行，等于要求猜。新增
`uo_init/source_window.py`：按大括号配平切出**包含该行的最内层块，能装下就扩到整个函
数**（含签名），注释和字符串里的括号先抹掉再数。`materialize_blocker_batches` 为需要读
代码的 blocker 附上这个窗口。FAG 当前一个 shard、20 条 blocker，19 条带源码共 473 行、
74 KiB——一次能读完。

`_snippet_matches` 相应放宽到「引用落在这个块里」并忽略空白差异。原来的三行窗口会把模
型**引用刚发给它的代码**判成证据不符。放宽不等于放开：跨函数引用仍然拒。

**（c）词汇表里没有变量。** `closed_vocabulary` 只列了 classification 和 binding_ops，
可 `validate_patch` 的 `invented_var` 检查是拿 `var_id` 去 `VariableModel` 里查的。模型
无从知道有哪些名字存在，只能猜，猜出来必被拒——这条通道原本走不通。

新增 `gaps.readable_vars()`：blocker 挡住的那几个维度**已经读到**的变量，作为该 blocker
的 `readable_vars` 写进 batch。它同时就是机械闸门一 (`check_reads_what_the_code_reads`)
的判据，两边同源。占位符（`VAR_INIT_*` / `VAR_UNDECIDED_*` / …）排除在外——拿一个过近似
去定义另一个过近似不是答案。

> 实现上要用字段已有的 `variables`，不能去遍历 `value_expr`：那是展开后的树，最宽的一维
> 有几十万节点，每条 blocker 走一遍会把生成 batch 从 5 秒拖到 4 分钟以上（踩过）。

---

## 3 个过近似——按「卡住几个字段」排序

> 原为 6 个。`back(slicePrefix1)` 由 `LAST_PUSH_DOMINATES_BACK` 消元，`size(syncRounds)` /
> `size(syncRoundRanges)` 由有界基数摘要消元（第 19、20 条）。剩下 3 个是**有意保留**的
> 过近似，由动态回放兜底，不再深挖。当前数字一律以
> [current-status.md](./current-status.md) 为准。

`python scripts/uo_key_blockers.py .probe_cache/fag_derive.json`，或按阻塞点分组：`python .probe_cache/diag_blocked_on.py`。

| 卡住字段数 | 变量 | 阻塞点 | 聚合语义 | 循环上界 | 能否精确消元 |
| ---: | ---: | --- | --- | --- | --- |
| 5 | 2 | `invalidS1Array[j]` | 布尔掩码上「是否存在仍为 false 的元素」（覆盖标记 + 带 break 扫描） | `s1Outer` / `actualS1Outer`，**依赖 shape** | **不能**。闭式是「区间并 `∪[BEGIN_i,END_i)` 是否盖满 `[0,s1Outer)`」，需对 `i` 量化而 `i` 上界也依赖 shape |
| 2 | 1 | `parseInfo[(s2Outer-1)][LENGTH_IDX]` | 前缀和取末项 = `Σ tmpSize[i]` | `s2Outer = (s2+cvS2Inner-1)/cvS2Inner`，**依赖 shape** | **不能**（展开项数不定）；闭式求和已知但无有限上界 |
| 1 | 2 | `size(syncRounds)` / `size(syncRoundRanges)` | 条件 `push_back` 的次数 | `CORE_LIST_NUM = 36`，**静态常量** | **能**，O(36) 指示函数之和 |
| ~~1~~ | ~~1~~ | ~~`back(slicePrefix1)`~~ | 切片后追加再取 `back()` | 切片循环依赖 `prefix1.size()/step` | **已消元**，见下节 |

**这张表推翻了一个原先的预期。** 原先记的处理是「要的是循环出口摘要」，隐含着做完摘要这 5 个维度就能闭合。实际不成立：`invalidS1Array`（卡住全部 5 个字段）与 `parseInfo` 的循环上界都是 shape 派生的，**不是有界的**。有界量词需要界；要表达它们只能用无界量词，而 `acp_common` 侧唯一的资源保护是 `SolveConfig.timeout_ms = 5000`（无 `rlimit` / `max_memory`），无界量词的结果会是 `unknown` 而不是答案。扩 `acp_common` 也救不了这两类，且那层的消费者不止 UO —— **整个 TG 求解栈**都建在它上面（`testcase_agent/constraint_ir.py` 再导出、`z3_backend.py` 子类化 `_CommonZ3Backend`），改 IR 语义两边都吃。

所以 P2 的定位要改写：**它不会让这 5 个维度变成 `input_derivable`**（一个维度要 exact 得把自由变量全消掉，而 `SplitAxis` 的 6 个里有 2 个属于上面「不能」那两行）。它能买到的是另一样东西 —— 这 6 个自由变量现在**完全无约束**，Z3 可以赋任意整数，过近似极松以致 SAT 无意义（只有 UNSAT 可信）。把能闭式的消掉、剩下的加上可靠约束（如 `size(syncRounds) + size(syncRoundRanges) <= 36`），过近似收紧，K6 就能多砍掉真不可达的 key，也就是**减少生成出来会失败的 case**。

一处措辞更正：`slicePrefix1` / `syncRounds*` / 其中一个 `invalidS1Array` 的源码在 **`..._tiling_varlen_regbase.cpp`**，不在长期作为重点的 normal / common 里（该文件在 bundle 解析范围内，分析没漏，但此前描述问题时的措辞偏窄）。

**这 6 个已不再派给 LLM**：`PRESORT_LOOP_ELEMENT` 归入 `NON_ESCALATING`。此前文档里"这是唯一真正该出判断题的桶"的判断被源码调查证否 —— 见下方说明与 [open-problems.md](./open-problems.md)。`gaps.py` 那道二层过滤同时从「看 reason 文本」改为「看 presort」：一个 loop element 若归一化失败在 `UNMAPPED_SYMBOL` 上，它带的 reason 是可升级的，旧的 `SCHED_SOFT` 检查照样放它过去。

`.second`（原 `UNMAPPED_CALL`）随④归零，`slicePrefix1` / `syncRounds`（原 `UNMAPPED_SYMBOL`）随⑥归零。`calculatedBlockInfo` 随⑤消失 —— 它原本是被下标的定义链拉进来的，而下标的定义链不属于字段值的决定因素（各字段 `input_roots` / `value_leaves` 前后不变，可确认不是丢约束）。

**这 6 个的取值全部由算子输入决定**（源码调查已核实：填充与读取路径里没有 `coreIdx` 之类 host 侧贪心装箱状态）。所以缺的不是信息，是**量化推理能力** —— 详见 [open-problems.md](./open-problems.md)，那里也记了此前"唯一正当的 LLM 面"这一判断的修正。

> 每桩掉一层都要重新量分布，不要照着旧清单干：整条守卫塌缩会把它后面的阻塞点一起吞掉。`.second` 在下标 cut point 之前只有 2 个可见，之后才涨到 5（guard 记录口径）。
>
> **也不要只看 free_vars 一个数。** ⑤ 曾出现"只改 surface 导致 6→21"的假退步（伪区分），⑥ 出现"5→6 的假退步"（实为救回 4 个真实约束）。同时看 `max_chars`、字段 `vars` 总数、`input_roots`、`value_leaves` 才能分清是真进展、伪区分还是丢约束。

对 **K6 逐 key Z3**：过近似 → 自由 bool → 约束变弱 → **可能多放行非法 key**，很少误杀合法 key。可以先开 K6 但结果偏松；要收紧按上表从头做。

注意 K6 **不会**因为树里有 `LOOP_ELEMENT` 而丢弃该维度（那是 `unmodelled_variable` 才触发的 `omit`）：维度照样参与约束合取，丢的只是 `_sat_caveats` 里的判决置信度。所以消掉上表任一项的收益是"把 `unknown` 变成判决"，不是"补回缺失的约束"。

---

## 剩余问题（按优先级）

### 0. 把 CLOSED 从 14/19 推到 19/19（**不是当前主线**）

判据已经从「CLOSED 几个」换成「任何标成 `input_derivable` / `reachable` 的关系是否确实由测试输入控制」。在标签修好之前把 CLOSED 从 14 推到 19，只会重演 `derived 19/19` 那次假成功。所以顺序是**先让标签诚实（已完成）→ 让产物可安全消费（K6 接主链）→ 再追闭合**。

layout 与 rope 两类已随 F.8 的作用域修复一并消失（它们本就是同一个根因）；顺序赋值假环见 F.10。`array_subscript` 已归零。

~~**静态解析缺陷已见底**~~ —— **这个判断是错的，勿再引用**。`back(slicePrefix1)` 就是反例：`slicePrefix1` 全仓库仅 4 处出现，`push_back(R1)` 在 `varlen_regbase.cpp:166`、`.back()` 在 171 行，中间只隔一句读 `prefix0` 的语句，**无循环回边、无分支** —— 这是容器 SSA 能确定性闭合的形态，不需要量词。另有两处同类：`_chase_writes` 遇到多个 guarded 常量写入就判 `TILING_DATA`（这正是 `IsTnd` 丢掉输入根的原因），以及 211 处隐式零默认里多数来自穷尽的 layout cascade、真实路径走不到默认 0。

据此修正后的分工：确定性静态闭合还有三项可做（容器 SSA、多写点 enum 折叠、默认值穷尽性证明），**之后**才是循环摘要。注意 `back()` 闭合大概率**不降** `free_vars`：`R1` 依赖 `deterPrefixData.prefix1.back()` 与 `mnMax`，两者都由 `CalcleTNDBandDeterPrefix` 的 `for (i < b)` 循环累加/取 max 得出。收益是让 blocker 形态诚实，不是消元 —— 别拿数字当判据。

**容器 SSA 的前提在当前 IR 下不成立（隔离调查，2026-07-31）。** 上面那段说的"无循环回边、无分支"是**读源码**得到的，不是从 IR 判定出来的，而替换本身必须由机器验证 —— 判断错的失败方向是"用一个不成立的确定值替换自由变量"。四个容器实例里只有 `back(slicePrefix1)` 属于"缺一个局部数据流查询"，另外三个性质完全不同，任何以它为样本的通用规则套上去都会给出错误的确定值：

| 实例 | 现状 | 判定 |
| --- | --- | --- |
| `back(slicePrefix1)` | `LOOP_ELEMENT`（无输入根的函数局部 vector） | 可闭合，但需先机器验证 5 项前置条件 |
| `back(deterPrefixData.prefix0)` | **不是** `LOOP_ELEMENT`，是 `TILING_DATA` 根的 `VAR_ELEM_BACK_*` | 不可闭合：7 条写分布在 5 个函数，2 条在循环内 |
| `back(deterPrefixData.prefix1)` | 同上 | 结构性不可闭合：**前缀和**，末项取决于 trip count 与每轮 `actualSeqQlen[i]` |
| `size(syncRounds)` | `LOOP_ELEMENT` | 不可闭合：带过滤的计数，等价于对循环体的存在量化 |

真正的阻碍是根因不在"信息没被记录"—— `push_back` 连守卫一起被完整记录在 `local_writes` / `assigns` 里。是三层叠加：(1) resolver 给不了纯函数局部容器一个输入根，而 `_container_element` 把输入根同时当作命名锚点和溯源凭证，两者绑死；(2) `derive_key_fields.py:1465` **有意**不展开任何容器操作，理由写在注释里且成立（展开会把 vector 换成某一次 `push_back` 的元素并丢掉容器名，`size(v)` 会被求成某个元素的值），于是已记录的写历史无人查询；(3) 管线里**不存在**"按程序点求容器最后一次变更"的机制 —— 写点带行号，读点不带。

5 项前置条件里有 2 项当时 IR 无法判定。补齐进度：

1. ~~**成员调用的接收者**~~ —— **已补（F.15）**，并且顺带把第 4 项也解决了。
2. **局部引用的别名标记**（仍阻塞）。`auto &v = deterPrefixData.prefix1;` 被当普通局部记录，经它做的 `push_back` 记在路径 `v` 上，与原容器毫无关联。类型判定所需的 `LVALUEREFERENCE` 检查在 `_is_out_param` 里已有现成实现。
3. ~~类型化的变更记录~~ —— **已补（F.15）**：`WriteRecord.kind` / `WriteEvent.kind`。
4. ~~读取点的程序序~~ —— **已补（F.15）**，方式与预想的不同：不必给 `FuncSummary.reads` 附行号，因为 `back()` / `size()` 本身就是成员调用，`CallSite` 的 `receiver` + `line` 直接给出有序的读写事件流。
5. 把 `WalkResult.controls` 带进 `HostIR`：`CtrlNode.kind` / `induction_vars` 已经算好却被丢掉，白让循环检测退化成 `for(` 字符串前缀匹配。

残余 6 个全是具名 `LOOP_ELEMENT`（3 个元素 + 3 个容器摘要），且**全部由输入决定**。

要消掉这 6 个需要**循环出口摘要 / 量化推理**。三种形态各需要的东西不同：

1. `invalidS1Array[j]` —— 区间覆盖判定（`∃j` 不被任何 `[begin_i, end_i)` 覆盖），需要存在量词。卡住全部 5 个字段，收益最大。注意**两个 scope 语义不同**：Normal 路径是整数区间，Varlen 路径用 **float** 边界且每 batch `assign` 重建，所以按 scope 分成两个变量是对的，不能共用一套摘要。
2. `parseInfo[(s2Outer-1)][LENGTH_IDX]` —— 前缀和的**末项**，即"有效基本块总数"，`Σ max(end_i - begin_i, 0)` 可闭式求和。顺带一个算子缺陷线索：`s2Outer == 0` 时 `parseInfo[-1]` 下溢，arch35 无保护而 arch22 有。
3. `size(syncRounds)` / `size(syncRoundRanges)` —— 受限 count-if，**不是全 coreId 的计数**：迭代域被 `continue` 过滤，且 Dense 用 `coreId > aicNum - 1`、Band 用 `coreId >= aicNum - 1`（两者不同），只有 `coreId != 0` 才 push。
4. `back(slicePrefix1)` —— 见上，走容器 SSA 而非量化。

`CLOSED` 只会在**真正消元**时才涨；把过近似收窄或改名都不算。

**关于 coreIdx（调查已澄清，我原先的判断是错的）**：它**不是**运行时核号，而是 host 侧模拟负载均衡时的**分块槽计数器**（`CaclePerCoreBlockInfo*` 里的贪心装箱）。所以「TilingKey 不该随核号变」这个直觉没有被违反。

- 循环出口 `blockOuter = coreIdx + 1` 确实进入 key 推导链：`enableSwizzle = (...) && blockOuter == aicNum` → `IsNzOut` / `IsTndSwizzle`。所以要的是**循环出口摘要**（`partition_count(input, maxBlockNumPerCore)`），不是继续软化。
- `coreIdx >= CORE_LIST_NUM` / `>= aicNum` 是**容量失败谓词**（分块数超上界则函数返回 false），不是按核号分支。
- `IsBn2MultiBlk` **不由 coreIdx 循环直接写入**——它只在 `SetSplitAxis` 和 `DoSparse:682` 被赋值。它身上的 coreIdx 依赖是 DFA 牵连过宽。
- guard#4（`syncRounds.size()+... > CORE_LIST_NUM`）**与 coreIdx 无关**，被归进 SCHED_SOFT 是误分类：叶子只剩 `CONSTANT` 和未解析的 `size()`，于是被 `_UNCONSTRAINING_ROOTS` 判成「不含输入约束」。容器大小应建模为 summary 变量。

**由此暴露的独立缺陷**：

- **evidence 匹配是错的问题**（已修）。原先用 Jaccard 相似度 + 阈值 0.12，于是 `platformInfoPtr == nullptr` 以 0.25 分被认定为一条 `coreIdx` 守卫的出处，把调查引向了完全无关的函数。
  - 根子在提错了问题：展开后的守卫是**多条源码守卫的合取**，对称相似度对它必然低分，短的无关条件和真正的来源得分一样高。该问的是「哪些源码守卫**出现在**展开式里」，即**覆盖率** `|交集| / |源码守卫|`，阈值 0.75（留余量给 `nullptr`→`None` 这类归一化改写）。
  - 一条展开守卫没有单一出处，所以额外给 `also` 说明同时命中了几条。现在 34 条有证据、33 条诚实地不给——**错的行号比没有行号更糟**。

- ~~常量混淆 `CORE_LIST_NUM`(36) 被折成 `aicNum`(32)~~ —— **经核实不成立**，勿再追。`named_constants` 里两者分别采集且取值都对（36 / 32）。调查报告把 `varlen:1279`（用 `CORE_LIST_NUM`）与 `varlen:928`（用 `aicNum`）两处混为一谈了，probe 折成 32 的那条对应后者，折叠是正确的。报告自己标注了这是「推断」——**推断要验证过才能写进缺陷清单**。

### 1. 开 K6 前建议先确认

- 再跑一遍 `diag_align.py` + `diag_collapse.py`（只剩 IsRegbase 恒 1 合法、IsRope 检测器误报可接受）。  
- 接受当前过近似（结果偏松），或先做 layout 归一（高杠杆、非必须）。

### 2. K6 — 逐 key Z3（**已完成，本节留作设计依据**）

依据是软化的单向性：软化只放大可行域，所以 **UNSAT 可判 unreachable，SAT 只能判 unknown**。这条让 5 个过近似字段仍有价值（能砍掉真不可达组合），同时杜绝误报 —— 也是为什么可以先接 K6 再追闭合。

> **8705 是什么**：不是 19 维值域的笛卡尔积（那是天文数字）。TPL 声明了 65 个 `ASCENDC_TPL_ARGS_SEL` 组，合法集是**各组内部笛卡尔积的并集**，由 `expand_legal_with_groups` 展开，共 8705 个。写探针枚举 key 一律走这个函数，不要自己对 `domain` 做 product。

- 新建 `uo_init/key_reachability.py`：用 `acp_common.z3_backend` 把 `var_model` + 19 棵 `value_expr` 组装成一份 IR，逐 KEY `push/pop`。`predicate.py` 产出的 SMT-lite 本来就照着 `SUPPORTED_EXPR_OPS` 写的，不用另写编译器。
- 四分类：任一字段 `partial/unresolved` 或 `input_closure == host_state` → `underivable`；UNSAT → `unreachable` + unsat_core；SAT 且全 `exact/constant` → `reachable` + witness；SAT 含过近似 → `unknown`。
- `materialize_tiling.py` 要删的：`_hard_invariants` 那三条硬编码规则（其中 `OutDType == InputDType` 虽然语义上碰巧对，但必须由派生给出而非硬写）、`z3_check_key_dims` 的维度白名单、`classify_key_reachability` 的全局 `input_controllable_fraction` gate；要修的：「有 blocker 仍返回 reachable」与 `use_z3=False` 直接 reachable。
- 接线：`export_kb_action` 补传 `tpl_schema` / `var_model` / `host_derivation`。无 derivation 时全部标 `underivable`，**不得回退到 `invariants_ok → reachable`**。
- 产物：`legal_key_index.jsonl` 每行加 `layer` / `witness` / `exactness_summary`；`template_admissible`（8705）与 `host_reachable` 是两个独立计数。

### 3. K5 — platform_context

- 读 CANN platform_config；读不到 → 带值域自由变量。  
- `GetDeterministic` → SESSION_OPTION（与 resolver 的 CONSTANT False 不一致问题一并收）。

### 4. K1 / K2 收尾

- 导出 `ir/host_derivation.yaml`。  
- `select_encode_site` 仍单站；空 tensor 已靠 `merge_literal_encode_alts` 补上，真多站 select 仍缺。

### 5. G0 fixture + K7 gate

- `tests/fixtures/flash_attention_score_grad/{key_field_truth,key_invariants}.yaml`。  
- 把 `diag_align` / collapse 升成正式回归。  
- gate：19/19、relations 非空、8705 判定无 UNKNOWN、不变式自洽。

### 6. 已知过近似（不排除合法用例）

- **B6** `isDeterministic` 仍偏自由（I8 的 DeterType=0 支推不紧）。  
- **VAR_SHAPE_GETSTORAGESHAPE** 过粗（`d`/`d1`/`b` 可能撞 id）—— 影响 Z3 可信度，对齐检查看不出来。  
- I2/I3 值域未按 GRAPH_FAILED 收窄。

### 7. 勿再踩的坑

- **阻塞点 ≠ 根因**：先桩掉第一个 OPAQUE，看后面还有多少致命点。  
- **假成功比 unresolved 更危险**：`derived` 但值域塌成单常量。  
- **消除过近似 ≠ 删掉它的记录**：只要 `value_expr` 里那个自由变量还在，条件就仍然是松的。改账不改式会让计数收敛而语义不变——本轮 F.1/F.2/F.3 都是这个形状。跑 `uo_key_status.py` 看不变式。  
- **不要按名字文本猜语义**：`_SCHED_SOFT_RE` 靠正则认「像调度」，把 `layoutType` 这种输入约束也软化了。把叶子解析到 root 再判。  
- **测试红了先分清是谁错**：本轮 4 条红测里 2 条是实现 bug、2 条是测试自身写错，方向相反，不看清就会把 bug「修」进期望值里。  
- **文本要能跟源码对得上**：guard 文本会拿去和源文件做子串匹配，规范化时别动运算符两侧的空格。  
- 改 `clang_walk` 才 `--refresh`；只改 deriver / resolver 用现成 bundle 即可。  
- `_pretty` 会把 DAG 打爆；调试用 `_pretty_dag` 或截断后的 `expanded` 缓存（注意缓存可能截断到 20k，对齐检查要用 live tree）。  
- 环检测不要用「裸名 ↔ 字段路径」误伤首次解析；用 `_canonical_name` 共用栈帧。

---

## 关键文件地图

| 路径 | 角色 |
| --- | --- |
| `uo_init/derive_key_fields.py` | 守卫化赋值 DAG、分类器内联、元素/归约、规范名 |
| `uo_init/clang_walk.py` | 写点 + early-return 守卫、复合赋值、RETURN_SLOT |
| `uo_init/source_resolver.py` | 根归约；`resolve_value` 三元值位置 |
| `uo_init/variable_model.py` | 变量域；`named_constants` |
| `uo_init/predicate.py` | SMT-lite 归一化 |
| `uo_init/tpl_bind.py` | encode 绑定；`merge_literal_encode_alts` |
| `uo_init/assemble_kb.py` | bundle；灌 enum/constexpr |
| `uo_init/host_derivation.py` | 聚合 19 维；presort、`unrecorded_free_vars` 不变式 |
| `uo_init/gap_patch.py` | 判定回灌；`binding_condition` + 表达式代入 |
| `engines/common/acp_common/` | TG / UO 共用的 constraint IR 与 Z3 后端（含 `prove_implies` / `prove_equivalent`） |
| `docs/debug/problem.md` | 假成功审计快照（B1–B5 部分已过时，以本文为准） |
| `docs/debug/history.jsonl` | 每次全量探针指标（第 39 行起为新口径） |

---

## 建议的下一步顺序

1. ~~layout / rope / F.8~~；~~3.B 调用切片 + 框架入口~~（`REACHED=0`）。  
2. ~~SCHED_SOFT 误分类~~ —— 调查 [Trace SCHED soft root loss](e6bb1a12-cef8-4f8a-b0e2-0a95dd59c786)：`unresolved`/非调度 root 禁止 SOFT + `Ref.scope`；**SCHED=0**，IsDNoEqual 闭合。勿再对所有 string lit 一律拒绝。  
3. ~~数组下标（`array_subscript`）~~ —— 已归零：`value_expr` 改 DAG 序列化恢复度量 → 下标处 cut point → `_expand_container_surface` 补 scope。`free_vars 19 → 9`。
4. ~~`.second`（`UNMAPPED_CALL`）~~ —— 已归零：元素的 tuple slot 纳入同一个 cut（④）。`free_vars 9 → 6`。
5. ~~多维下标 identity 过粗~~ —— 已修（⑤）：下标改浅展开 + 完整下标链，同时消除假等式与伪区分；附带 `max_chars` 减半、耗时减半。
6. ~~reduction / accessor 的 cut fallback~~ —— 已修（⑥）：`UNMAPPED_SYMBOL` 归零。
7. ~~标签诚实化（P0）~~ —— 已完成：`input_closure` 收紧三处 `input_derivable`（13→10）、`domain_violations` 抓出 `OutDType` 契约冲突、`LOOP_ELEMENT` 移出 LLM 队列、`substitute_vars` 支持 int 探针 + 消元后强制校验回退、loop gate 加 `free_vars` 不得上升。派生数字（CLOSED 14 / free_vars 6 / implicit_zero 211）不变 —— 这一轮只动标签，不动派生。
8. ~~K6 逐 key Z3~~ —— 已完成（F.13）：14/19 维进求解器，8705 key 全量判定 127s。产物可交下游，只是可用维度较少 —— 这比一个 19/19 但语义不可信的产物有用得多。**当前 8704/8705 是 `unknown`，卡点已明确是第 10 项（循环摘要）**：5 个被 `omit` 的维度全部因为未建模的循环归约变量（`m0Max` / `s2Inner` / `deterTilingSplitMode` …）。
9. **确定性静态闭合**：容器 SSA（`back(slicePrefix1)`）→ 多写点 enum 折叠（`IsTnd` / `IsPse` / `IsAttenMask` 的输入根，**风险最高，会影响所有字段的 root，必须逐字段对比前后**）→ 隐式零默认穷尽性证明。
   - **容器 SSA 已降级，不要直接开工。** 隔离调查（见「剩余问题 0」内的表）表明它只对 4 个容器实例中的 1 个成立，且 5 项前置条件里有 2 项当前 IR 无法判定（成员调用接收者、局部引用别名）。补齐这些 IR 缺口同时也修掉「写记录里两个静默缺口」（见 [open-problems.md](./open-problems.md)），那两条本身就是正确性缺陷，方向是"替换成无根据的确定值"；而容器 SSA 自身的收益按 F.14 的更正只是把某个维度的 `unknown` 变成判决，不补回缺失约束。**先修 IR 缺口，再谈替换。**
10. **6 个 `LOOP_ELEMENT`**：循环出口摘要 / 区间覆盖闭式，最后做。它们输入可定，**不该出判断题**。IR 层有两条路，做到那时再定：(a) 在 UO 内把摘要消元成现有 `SUPPORTED_EXPR_OPS`（不动共享层，但表达力受限）；(b) 给 `acp_common/constraint_ir.py` 加有界聚合节点。当前 IR 的 `variables` 是 flat 列表、类型只有 `bool|int|enum`，没有索引变量概念，所以 (b) 要引入绑定范围结构。
11. K5 / G0 / K7。

当前阻塞分布（`python .probe_cache/diag_blocked_on.py`）：

| reason | 变量数 | 卡住的字段 |
| --- | ---: | --- |
| LOOP_ELEMENT（元素 3 + 摘要 3） | 6 | 全部 5 个未闭合字段 |
| UNMAPPED_SYMBOL | **0** | — |
| UNMAPPED_CALL（`.second`） | **0** | — |
| OPAQUE（`array_subscript`） | **0** | — |
| SCHED / REACHED | **0** | — |

每步对比 `history.jsonl`：**`unrecorded` 恒为 0**；`closed` 要涨、`free_vars` 要降。但这两个数单看会骗人，本轮两次都遇到了：

- `closed` 不涨可能是对的 —— 收窄过近似 ≠ 消元。
- `free_vars` **涨**也可能是对的 —— ⑥ 用 +1 个自由变量换回 4 个真实约束。判据是字段 `vars` 总数同时上升。
- `free_vars` 涨也可能是错的 —— ⑤ 的第一版把一个元素拆成 11 个伪变量。判据是 surface 是否还是源码形态（`python .probe_cache/diag_surfaces.py`）。

所以每步至少同时看：`free_vars`、字段 `vars` 总数、`max_chars`、`input_roots` / `value_leaves` 是否守住、`unrecorded_free_vars` 恒为 0。**另外记住 CLOSED 与 INPUT_DERIVABLE 是两个数**：把过近似消掉会涨前者，把根追到输入才涨后者。

---

## 单测

**必须从 `engines/understand-operator` 跑。** 从仓库根跑会有 7 个 `ModuleNotFoundError: No module named 'tests.conftest'` 的 ERROR——那是 rootdir 问题，不是代码问题，别去追。

```powershell
cd engines/understand-operator; python -m pytest tests/ -q
```

当前 **277 passed / 0 failed**（`tests/unit`，7m52s）。上一版交接里那 4 条「基线红测」已全部修完，**UO 不再有已知红测**；再出红就是真回归：

| 测试 | 结论 |
| --- | --- |
| `test_lineage_records_enclosing_guards` | 实现错：`_norm_expr` 吃掉了 `)` 右侧空格（F.7） |
| `test_writes_keep_the_nested_field_path` | 实现错：局部 `std::set` 的 `insert` 误记为字段写入（F.6） |
| `test_coverage_baseline_row` | 测试错：漏传 `op_name` |
| `test_uint_index_encoding` | 测试错：把 `ASCENDC_TPL_UI_LIST` 标记也数进下标了 |

新增：`test_key_exactness.py`（**45 条**：分级 + 哪些守卫可软化 + 叶子必须在它来源的函数作用域里解析 + 下标 cut point + 容器 surface 打 scope + 元素 tuple slot + **下标浅展开与下标链的 5 条** + **容器摘要 cut 的 4 条**）、`test_key_contract.py`（**20 条**，产物契约：`input_closure` 分级 + `domain_violations` + 哪些守卫可以成为 LLM 问题 + 消元必须真落地）、`test_expr_dag.py`（DAG 序列化，10 条）、`test_gap_patch_consistency.py`（解析必须改表达式而非只改账）、`engines/common/tests/test_shared_solver.py`（10 passed）。

`test_isnzout_derivation_chain` 通过，是直接测派生链的用例。

其中几条钉的是 soundness 而非行为，改动时别当冗余删掉：`test_two_slots_of_one_element_are_different_variables`、`test_different_outer_subscripts_are_different_variables`、`test_two_summaries_of_one_container_are_different_variables`（三处"不同未知量不得共用变量"），以及反向的 `test_a_slot_on_something_other_than_a_subscript_is_left_alone`、`test_an_input_backed_summary_keeps_its_input_root`（cut 不得抢已能精确解析的路径）。`test_a_subscript_is_not_expanded_through_its_definitions` 钉的是"下标不深展开"这条不变量。

`test_key_contract.py` 里同样有几条是 soundness：`test_a_field_closing_onto_host_state_is_not_input_derivable`（`exact` 不等于可控）、`test_an_unclassified_root_counts_as_host_state`（未知根必须保守）、`test_a_verdict_that_does_not_land_is_rolled_back`（改账不改式必须被拒），以及反向的 `test_platform_facts_do_not_make_a_field_undrivable`、`test_the_same_values_under_a_wider_declaration_are_clean`、`test_an_unmapped_guard_is_still_escalated`（收紧不得过度，否则会把本可用的维度和本该问的问题一起丢掉）。

> **Windows 上 pytest 的退出码不可用作判据。** 收尾清理 `%TEMP%\pytest-of-*\pytest-current` 会抛 `PermissionError: [WinError 5]`，于是 exit code 恒为 1，并且**连 `N passed` 摘要行一起吞掉**。判绿要看进度行是否走到 `[100%]` 且没有 `F` / `E`。也不要给 pytest 输出接 `Select-Object -Last N`：摘要行在异常栈之前，会被截掉。
>
> **跑测试期间不要改 `src/` 下的文件。** 派生用 `mp spawn` 起子进程，子进程会重新 import，读到写了一半的模块就会整批异常退出（表现为跑到一半没有摘要）。

> **TG 当前 21 red，暂不处理。** 结论是先把 UO 做正确，再据此重构 TG——在 UO 的口径稳定之前修 TG 只会把错误的假设固化下来。别把它当回归追。
