# Clang 解析问题记录

> 从 KeyField 派生调试中抽出的 **clang / Host IR 解析** 问题。  
> 按问题归类，不按开发流程。数字与验收口径见 `current-status.md`。

相关代码：`uo_init/clang_walk.py`、`source_resolver.py`、`derive_key_fields.py`、`cpp_expr.py`。

---

## 1. AST 写点记录不完整

### 1.1 复合赋值被记成覆盖

`+=` 等若不当心，会记成整段覆盖而非「读旧值再写」。  
**修法**：从 token 重建 RHS。

### 1.2 局部容器变更漏守卫

`_record_write` 对无 `.` 的裸名不记 `writes`，但 `insert` / `push_back` 走另一路径时可能不带同一套守卫。局部 `std::set` 等会被记成无 owner 的字段写，可能被 tail 匹配安到真字段上。  
**修法**：容器写补齐守卫；元素进 `appends`，勿污染 `assigns`。

### 1.3 成员路径上的整容器 `operator=`

`path.count(".") < 1` 时整容器赋值被丢掉。FAG 上 `deterPrefixData.prefix* = SliceVector(...)` 共 14 条。  
**修法**：放开限制，记为 `kind="replace"`。

### 1.4 `push_back` 元素冒充容器定义

`assigns` 里出现的是元素表达式，不是容器新值。  
**修法**：元素进 `FuncRecord.appends` / `FuncSummary.appends`。

### 1.5 变更种类未区分

`append` 的 RHS 是一个元素；`clear` / `pop_back` / `erase` 等是空 RHS。不区分则 `size(v)` 会被求成最后一次 `push_back` 的元素；看不见的 `clear()` 与「没有写」无法区分。  
**修法**：`WriteRecord.kind` ∈ `{assign, append, replace, shrink}`。

### 1.6 无初值声明被记成自指

libclang 给 `std::vector<T> v;` 挂隐式默认构造 `CALL_EXPR`，读 token 得到变量名本身 → `locals` 里 `syncRounds -> "syncRounds"`。  
**修法**：无参 `CALL_EXPR` 视为无初值；「声明未初始化」用 `LocalDecl`，与 `local_writes` 分开。

---

## 2. 控制流 / 守卫语义丢信息

### 2.1 early-return 否定不完整

`if (c) { …; return; }` 之后只补最外层 `!c`；带 else-if 链时，后续路径的 guard **弱于真实**，穷尽性会误判。  
**修法**：`kind="guard_clause"` + `records_what_follows`；有 else 链时不要当完整否定。

### 2.2 错误退出守卫被一律丢弃

`_ERROR_EXIT_RE` 把所有 `return GRAPH_FAILED` 的否定丢掉。混了两类：

| 类型 | 例子 | 取反有无信息 |
| --- | --- | --- |
| 重述型 | `if (shape == nullptr) return FAILED` | 无 |
| 排除型 | `if (queryType == DT_HIFLOAT8) return FAILED` | 有（收窄合法输入） |

一律当重述型 → 合法 dtype 变宽，`OutDType=4/5/6` 假可达。  
**修法**：bailout 提为 `HostIR.legality_premises()`，不当单变量守卫；嵌套拒绝做成蕴含式。

### 2.3 转发状态码早退认不出

只认字面 `return GRAPH_FAILED`，认不出 `if (ret != SUCCESS) return ret;`，后续写挂上假守卫。  
**修法**：`_STATUS_FAILURE_RE`。

### 2.4 循环信息进不了写点

`CtrlNode` 有 `induction_vars`，但 `WriteRecord` 只带 `PathCond`，且 `build_host_ir` 曾丢掉 `controls`。`kind` 被编码进 `text`，判断「是不是二分决策」只能剥字符串。  
**修法**：`PathCond.kind` + `is_decision`；`HostIR.controls` / `loop_at`；`for` 头读 `init_value` / `step`（赋值式初值勿当成条件）。

### 2.5 穷尽性判错

- 顶层无 guard 写 ≠ 覆盖其余（取决于是否被调用）。
- 跨函数两侧合起来像穷尽，实际可能单独调用。
- 按全局判穷尽：A 写全、B 再写一次就判不出；按函数判时，成员还需 `_always_runs`（函数未必执行）。
- 读点也有条件：写看起来不穷尽，但读与写同一前提（如 attenMask 存在）时，未必有「未写先读」。

---

## 3. 成员调用 / 接收者

### 3.1 libclang 没有 `CXX_MEMBER_CALL_EXPR`

本机 CursorKind 无该成员，`v.clear()` 以 `CALL_EXPR` 到达。门闩写在 `CXX_MEMBER_CALL_EXPR` 上 → 接收者全空。  
**修法**：不要靠该 kind；`_receiver_path` 只认「`MEMBER_REF_EXPR` 且 spelling=方法名」或路径以 `.方法名` 结尾。宽松「第一个孩子」会把 `std::max(a.b, c)` 误报成在 `a.b` 上调用。

### 3.2 读点程序序

`back()` / `size()` 本身是成员调用，有 `receiver` + `line` 即可构成有序事件流，不必给 `reads` 另附行号。

---

## 4. 跨函数展开与作用域

### 4.1 叶子在错误函数里解析

展开跨函数，归一化却绑在 encode 函数上 → 内联进来的局部名变成 `UNMAPPED_SYMBOL`，整条守卫变自由布尔。  
**修法**：`Ref.scope`；按 scope 取 resolver。

### 4.2 容器 surface 漏打 scope

`Select.array` 走 `_expand_container_surface`，只给 `_expand_surface` 补了 scope 时，跨函数容器丢输入根。  
**教训**：测「下游用 scope」≠ 测「上游打 scope」。

### 4.3 同名局部量跨函数串味（收缩型）

`_active` / `_prev_version` / 跨作用域缓存按裸名索引。成员对、局部错：`DoSplit::s1Inner` ≠ `FuzzyForBestSplit::s1Inner`。拿到别函数表达式 = **错误等式** → 假 UNSAT。  
**修法**：局部用 `fn::name`；跨作用域复用只对成员开放。

### 4.4 字段定义池随拼写分裂

自由函数形参写记成 `fBaseParams.splitAxis`，查 `this.fBaseParams.splitAxis` 命不中 → 两套定义池、穷尽性吃不全。  
**修法**：`param_bound_member`——仅当每个调用点实参都是 `this` 同名成员才合并。勿裸剥 `this.`（会误并不同对象）。

---

## 5. 下标 / 容器 / 循环元素

### 5.1 一个下标毁掉整条守卫

无法解析的 `Select` → `NormalizeError` → 整条合取守卫换成自由布尔，旁边 layout/platform 约束全丢。  
**修法**：下标处 cut → `VAR_ELEM_*`。

### 5.2 元素 tuple slot 绕过 cut

`s1ValidIdx[i].second` 是 `Call("field:second", (Select(...),))`，不是裸 `Select` → `UNMAPPED_CALL`。  
**修法**：slot 走同一 cut；identity = `(scope, container, index, slot)`。

### 5.3 多维下标 identity 过粗 / 过细

剥掉所有下标 + 只取最内层 index → 前缀和相邻项共用变量（**假等式，收紧**）。只改 surface 完整链又会因深展开把 `i` 内联成巨型式（**伪区分**）。  
**修法**：下标不跨函数深展开 + 完整下标链做 identity。

### 5.4 容器摘要无 cut

局部 `size()` / `back()` 无输入根 → 整条守卫塌缩。  
**修法**：`_loop_reduction_var`，identity `(scope, container, kind)`。

### 5.5 可变容器上 `back`/`size` 跨读点共享（收缩型）

静止容器共享摘要合法；多函数 `push_back` 后多处 `back()` 共用一个变量 = 伪造等式。  
**修法**：多函数写或读方自己也写 → 隔离；单写函数且非读取者 → 可共享。

### 5.6 `push_back` 后的 `back()` 就是元素

无回边、无破坏性操作时，`back(v) :=` 最后一次 append 的元素。  
**注意**：读点用「该函数唯一 `back()`」绕过 Expr 无位置；判据是 push 守卫 ⊆ read 守卫，不是「push 无条件」。

### 5.7 顺序赋值被当成环

`x = a; x = x - b;` 中第二次 RHS 读的是前版本。环检测不区分「`x=f(x)`」与真环。  
**修法**：`_prev_version`（同名写点链内 SSA）。跨名字的 save/modify/restore（局部与成员互指）还需程序点敏感过滤。

### 5.8 程序点不敏感造假环

`s1Inner`/`s2Inner`：先存成员到局部、条件翻倍、再还原。位置不敏感展开会绕环。  
**修法**：`_visible_defs` 滤掉「此刻还没跑到的写」；同函数比行号；共享循环例外；跨函数靠调用点且 `_runs_once`。取值用过滤后的写，穷尽性用全集。

---

## 6. 符号归约 / 变量身份

### 6.1 局部量误判 `TILING_DATA`

Params 快速路径过宽。  
**修法**：降为兜底；按写记录认聚合体（`aggregate_heads`），不靠名字正则。

### 6.2 三元 RHS 错绑 provenance

赋值 RHS 的 `c ? a : b` 不应收集 `c` 的 provenance。

### 6.3 操作数身份坍缩（收缩型）

`d`/`s1`/`s2` 全叫 `VAR_SHAPE_GETSTORAGESHAPE`，一维内多处约束互相矛盾 → 假 UNSAT。  
**修法**：接上 opdef 操作数名 + 轴号（`GetDim(DIM_2)` 也要认命名常量）；轴号在 Atom 转发时勿丢。

### 6.4 全常量局部量折叠收缩可行域

多分支全是常量时折成单个 `CONSTANT`；再拿标识符名字而非值比较 → 缩小域。  
**修法**：存在 `Ite`/`Select` 选择则不许折。

### 6.5 字符串字面量与标识符不分

IR 里 `"TND"` 与 `TND` 同形 → 互斥判不出。需字面量标记。

### 6.6 符号折叠混真值与编造值

组内有的进 `named_constants`、有的编负数 → 字符串比较落到错误整数域。编号计数器非单调还会让互异符号同值。  
**修法**：按比较变量分组，全读到或全编码；裸符号局部归约变量勿当常量。

### 6.7 按名字猜软变量类型

`VAR_SCHED_<hash>`（bool）与 `VAR_SCHED_COREIDX`（int）同前缀，一律声明 bool → 整求解器挂掉。  
**修法**：类型随 worker 记录回传。

---

## 7. 隐式默认与声明初值

### 7.1 if/else 链 fallthrough 填 `Const(0)`

未读声明就断言字段默认为 0；穷尽 cascade 上该路不可达。  
**修法**：语法穷尽性（`PathCond` 决策树）+ 读结构体成员声明初值。索引键必须是 `(结构体, 成员名)`，裸名会撞 tiling-data 同名 `=0`。

### 7.2 块作用域带初始化器的局部

`if (TND) { int64_t x = …; }` 链式分析问「非 TND 时 x=?」并 mint 自由变量——C++ 作用域下该读不存在。  
**修法**：声明站点有初始化器则不 mint fallthrough。

---

## 8. 文本与可观测性

### 8.1 `_norm_expr` 空格失真

`strcmp(a,b)==0` 变 `)== 0`；`size()>0` 压掉空格 → 与源码匹配失败。  
**修法**：括号只贴紧归属侧；比较符两侧空格不动。

### 8.2 守卫失败不报 blocked_on

只记整条守卫截断文本，不知道卡在哪个符号。  
**修法**：保留 `NormalizeError.detail` → `blocked_on`。

### 8.3 evidence 用相似度找出处

合取守卫用 Jaccard 会命中无关短条件。  
**修法**：覆盖率 `|交集|/|源码守卫|`，阈值宜高。

---

## 9. 仍开放 / 有意保留

| 问题 | 说明 |
| --- | --- |
| 局部引用别名 | `auto &v = container;` 上的 `push_back` 记在 `v` 上，与原容器未关联 |
| out-param | 引用参数输出时，调用方作用域只有声明无赋值；resolver 层环未修完 |
| shape 依赖循环元素 | `invalidS1Array[j]`、`parseInfo[last]` 上界依赖 shape，静态精确消元投入过大，有意过近似 |
| 未知调用当 0 | 未知调用折叠成常量而非 Unknown，可能污染前提/表达式 |
| 递归解码 DAG | `decode_expr_dag` 曾递归；大表达式可 native crash。编码侧已迭代，相关 `setrecursionlimit` 隐患仍在 |

---

## 10. 勿再踩

1. **一个下标 / 一个 UNMAPPED → 整条守卫放宽**：静默放宽比报错更危险。  
2. **阻塞点 ≠ 根因**：先桩掉第一个 OPAQUE，再看后面还有多少。  
3. **假等式（收紧）比过近似更糟**：变量身份错、跨函数串味、多读点共享 `back()`。  
4. **改账不改式**：删 `undecided` 却留 `VAR_*` 在表达式里。  
5. **按名字猜语义 / 类型 / tiling 根**。  
6. **断言上游会打 scope / 会记接收者**：两端都要测。  
7. **改 `clang_walk` 才需 `--refresh`**；旧 pickle 的 resolver 缺新字段会让全维 `unresolved`。  
8. **推断要核实再进缺陷清单**（如常量混淆曾被误报）。
