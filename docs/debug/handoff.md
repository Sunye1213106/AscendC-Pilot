# KeyField 派生修复 — 交接

> **调试产物，不是工作流契约 / 验收依据。**  
> 生产入口：uo-init Action `derive_key_fields` → `uo_init.host_derivation` / `derive_key_fields.py`。  
> 探针：`scripts/_probe_derive.py`（薄封装，勿当唯一入口）。

面向「接手这项工作的下一个人」。目标是让 KB 侧把算子的 TilingKey 各维派生到输入根，再驱动 TG 做逐 key Z3。**不要为 FAG 做特化**，机制要能迁移。

---

## 当前状态（2026-07-30）

| 项 | 状态 |
| --- | --- |
| **19 维精确闭合** | **CLOSED 14/19**，unique free_vars=6；array_subscript / `.second` / UNMAPPED **全 0**，残余 6 个全部具名 |
| 隐式零默认 | **211 处**，压在 6 个已判 exact 的字段下——`exact` 判据尚不充分 |
| 派生进主链 Action | **已到**（`derive_key_fields` + `host_derivation.yaml`） |
| 共享求解器 | **已到**：`engines/common`（`acp_common`），TG / UO 同一套 IR 与 Z3 语义 |
| 19 维结构对齐 | **FAIL=0 / WARN=1**（OutDType 叶含 4/5/6 vs TPL 0..3） |
| LLM 封闭回环 | 已联调，但 `apply_gap_patch` 曾只改账不改式，见 F.2 |
| key 判定 8705 / K6 真 Z3 | **未做** |
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

**验收数 = `CLOSED`（exact + constant）= 14/19；目标 19/19 且 `free_vars = 0`。**

同口径最新（下标浅展开 + 完整下标链 + 容器摘要 cut 后）：

```
CLOSED 14/19   unique free_vars=6   implicit_zero=211   ~12s
exact=13  constant=1  overapproximated=5   max_chars=80326
SCHED=0  REACHED=0  array_subscript=0  UNMAPPED_CALL=0  UNMAPPED_SYMBOL=0
```

残余 6 个**全部具名可解释**（不再有 `VAR_UNDECIDED_*` 匿名布尔量）：

| 变量 surface | 源码 |
| --- | --- |
| `invalidS1Array[j]` ×2（两个 scope） | `normal_regbase.cpp:1546`、`varlen_regbase.cpp:897` |
| `parseInfo[(s2Outer(fBaseParams) - 1)][LENGTH_IDX]` | `normal_regbase.cpp:1558` |
| `size(syncRounds)`、`size(syncRoundRanges)` | `varlen_regbase.cpp:716` |
| `back(slicePrefix1)` | `varlen_regbase.cpp:171` |

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

### 隐式零默认（211 处）

`_chain` 构建 if/else-if 链时，最内层那个 `Ite` 的 else 没有来源，就填 `Const(0)`（「字段默认为零」）。这**不是**自由变量，不计入 `free_vars`，但它是一个我们从没读过声明就下的断言，所以现在逐处记录到 `implicit_defaults`。

实测 211 处，**且压在 6 个已判 `exact` 的字段下**（InputDType、S1TemplateNum、S2TemplateNum、OutDType、DTemplateNum、IsDNoEqual）。即当前的 `exact` 判据尚不足以保证正确 —— 口径以 `python scripts/uo_key_status.py .probe_cache/fag_derive.json` 末尾两行为准。

多数其实**语义上不可达**。以 layout cascade 为例（`..._tiling_normal_regbase.cpp:99-320`）：

```cpp
if (strcmp(inputLayout, "SBH") == 0)      { fBaseParams.b = …; }
else if (strcmp(inputLayout, "BSH")  == 0) { … }
else if (strcmp(inputLayout, "BNSD") == 0) { … }
else if (strcmp(inputLayout, "TND")  == 0) { … }
else /* BSND */                            { fBaseParams.b = …; }
```

分支是穷尽的，`Const(0)` 那条路走不到。但**求解器不知道**——它会认为字段可以取 0，于是放行本不存在的 key。方向是过近似（多放行），不是漏判。

正确解法不是逐个去查默认值，而是证明守卫析取为真：`acp_common.z3_backend.prove_implies` 已经具备这个能力，缺的是 constraint IR 组装（阶段 2）与 `GRAPH_FAILED` 校验前提（3.D）。证不出来的才需要真去读构造函数（3.E）。

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

---

## 6 个过近似——按「卡住几个字段」排序

`python scripts/uo_key_blockers.py .probe_cache/fag_derive.json`，或按阻塞点分组：`python .probe_cache/diag_blocked_on.py`。

| 卡住字段数 | 变量 | 阻塞点 | 性质 | 处理 |
| ---: | ---: | --- | --- | --- |
| 5 | 2 | `invalidS1Array[j]` | LOOP_ELEMENT | 区间覆盖判定，**输入可定**；要的是循环出口摘要，不是判断题 |
| 2 | 1 | `parseInfo[(s2Outer-1)][LENGTH_IDX]` | LOOP_ELEMENT | 前缀和末项；同上 |
| 1 | 2 | `size(syncRounds)` / `size(syncRoundRanges)` | LOOP_ELEMENT | 相邻核列切分需同步的轮次对数；见问题 6 |
| 1 | 1 | `back(slicePrefix1)` | LOOP_ELEMENT | band deter 前缀和的最大轮次 |

`.second`（原 `UNMAPPED_CALL`）随④归零，`slicePrefix1` / `syncRounds`（原 `UNMAPPED_SYMBOL`）随⑥归零。`calculatedBlockInfo` 随⑤消失 —— 它原本是被下标的定义链拉进来的，而下标的定义链不属于字段值的决定因素（各字段 `input_roots` / `value_leaves` 前后不变，可确认不是丢约束）。

**这 6 个的取值全部由算子输入决定**（源码调查已核实：填充与读取路径里没有 `coreIdx` 之类 host 侧贪心装箱状态）。所以缺的不是信息，是**量化推理能力** —— 详见 [open-problems.md](./open-problems.md)，那里也记了此前"唯一正当的 LLM 面"这一判断的修正。

> 每桩掉一层都要重新量分布，不要照着旧清单干：整条守卫塌缩会把它后面的阻塞点一起吞掉。`.second` 在下标 cut point 之前只有 2 个可见，之后才涨到 5（guard 记录口径）。
>
> **也不要只看 free_vars 一个数。** ⑤ 曾出现"只改 surface 导致 6→21"的假退步（伪区分），⑥ 出现"5→6 的假退步"（实为救回 4 个真实约束）。同时看 `max_chars`、字段 `vars` 总数、`input_roots`、`value_leaves` 才能分清是真进展、伪区分还是丢约束。

对 **K6 逐 key Z3**：过近似 → 自由 bool → 约束变弱 → **可能多放行非法 key**，很少误杀合法 key。可以先开 K6 但结果偏松；要收紧按上表从头做。

---

## 剩余问题（按优先级）

### 0. 把 CLOSED 从 14/19 推到 19/19（当前主线）

layout 与 rope 两类已随 F.8 的作用域修复一并消失（它们本就是同一个根因）；顺序赋值假环见 F.10。`array_subscript` 已归零。

**静态解析缺陷已见底**：`array_subscript` / `UNMAPPED_CALL` / `UNMAPPED_SYMBOL` 全部归零，残余 6 个全是具名 `LOOP_ELEMENT`（3 个元素 + 3 个容器摘要），且**全部由输入决定**。

要再涨 CLOSED 只剩一条路：**实现循环出口摘要 / 量化推理**。三种形态各需要的东西不同：

1. `invalidS1Array[j]` —— 区间覆盖判定（`∃j` 不被任何 `[begin_i, end_i)` 覆盖），可推闭式或用量词编码给 Z3。卡住全部 5 个字段，收益最大。
2. `parseInfo[(s2Outer-1)][LENGTH_IDX]` —— 前缀和的**末项**，即"有效基本块总数"。这类"前缀和末项"其实是一个可闭式求和的量。
3. `size(syncRounds)` / `back(slicePrefix1)` —— 循环出口的计数 / 末元素，需要循环出口摘要（`partition_count` 一类）。

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

### 2. K6 — 逐 key Z3（三重覆盖第 2 项）

- 删 `IR_TPL_IDENTITY`、`input_derivable: True` 硬编码。  
- `classify_key_reachability` 逐 key 调 z3，输出 OK / Z3_UNSAT / Z3_UNKNOWN + 见证。  
- **派生假折叠未清时不要接**（当前对齐已过，可接）。

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
7. **6 个 `LOOP_ELEMENT`（当前主线）**：循环出口摘要 / 区间覆盖闭式。它们输入可定，**不该出判断题**。剩余主要工作量，见上节三种形态。
8. **K6** 逐 key Z3；K5 / G0 / K7。

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

所以每步至少同时看：`free_vars`、字段 `vars` 总数、`max_chars`、`input_roots` / `value_leaves` 是否守住。

---

## 单测

**必须从 `engines/understand-operator` 跑。** 从仓库根跑会有 7 个 `ModuleNotFoundError: No module named 'tests.conftest'` 的 ERROR——那是 rootdir 问题，不是代码问题，别去追。

```powershell
cd engines/understand-operator; python -m pytest tests/ -q
```

当前 **257 passed / 0 failed**（`tests/unit`，6m54s）。上一版交接里那 4 条「基线红测」已全部修完，**UO 不再有已知红测**；再出红就是真回归：

| 测试 | 结论 |
| --- | --- |
| `test_lineage_records_enclosing_guards` | 实现错：`_norm_expr` 吃掉了 `)` 右侧空格（F.7） |
| `test_writes_keep_the_nested_field_path` | 实现错：局部 `std::set` 的 `insert` 误记为字段写入（F.6） |
| `test_coverage_baseline_row` | 测试错：漏传 `op_name` |
| `test_uint_index_encoding` | 测试错：把 `ASCENDC_TPL_UI_LIST` 标记也数进下标了 |

新增：`test_key_exactness.py`（**45 条**：分级 + 哪些守卫可软化 + 叶子必须在它来源的函数作用域里解析 + 下标 cut point + 容器 surface 打 scope + 元素 tuple slot + **下标浅展开与下标链的 5 条** + **容器摘要 cut 的 4 条**）、`test_expr_dag.py`（DAG 序列化，10 条）、`test_gap_patch_consistency.py`（解析必须改表达式而非只改账）、`engines/common/tests/test_shared_solver.py`（10 passed）。

`test_isnzout_derivation_chain` 通过，是直接测派生链的用例。

其中几条钉的是 soundness 而非行为，改动时别当冗余删掉：`test_two_slots_of_one_element_are_different_variables`、`test_different_outer_subscripts_are_different_variables`、`test_two_summaries_of_one_container_are_different_variables`（三处"不同未知量不得共用变量"），以及反向的 `test_a_slot_on_something_other_than_a_subscript_is_left_alone`、`test_an_input_backed_summary_keeps_its_input_root`（cut 不得抢已能精确解析的路径）。`test_a_subscript_is_not_expanded_through_its_definitions` 钉的是"下标不深展开"这条不变量。

> **Windows 上 pytest 的退出码不可用作判据。** 收尾清理 `%TEMP%\pytest-of-*\pytest-current` 会抛 `PermissionError: [WinError 5]`，于是 exit code 恒为 1，并且**连 `N passed` 摘要行一起吞掉**。判绿要看进度行是否走到 `[100%]` 且没有 `F` / `E`。也不要给 pytest 输出接 `Select-Object -Last N`：摘要行在异常栈之前，会被截掉。
>
> **跑测试期间不要改 `src/` 下的文件。** 派生用 `mp spawn` 起子进程，子进程会重新 import，读到写了一半的模块就会整批异常退出（表现为跑到一半没有摘要）。

> **TG 当前 21 red，暂不处理。** 结论是先把 UO 做正确，再据此重构 TG——在 UO 的口径稳定之前修 TG 只会把错误的假设固化下来。别把它当回归追。
