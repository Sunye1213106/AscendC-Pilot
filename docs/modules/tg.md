# TG：Testcase Generation

TG（Testcase Generation）负责把 UO 建立的 Operator CodeMap 转换为**可以通过真实运行证据验证的测试覆盖结果**。

UO 能够说明 TilingKey 如何定义、Host 中哪些状态参与构造、TilingData 如何传递，以及 Kernel 中有哪些结构关系，但这些静态信息不能直接回答：

- 一个合法 TilingKey 是否真的能够被某组输入触发；
- 怎样构造输入才能命中指定 TilingKey；
- Host 是否会拒绝或改写候选输入；
- 同一个 TilingKey 下，TilingData 和 runtime branch 是否还有不同结果；
- 长时间搜索不到某个目标，是候选构造能力不足，还是源码上确实不可达。

因此 TG 不把“静态可行”或“模型认为可达”当作覆盖结果，而是把 CodeMap 目标空间变成可运行 testcase，再经 Host Replay 验证。

整体过程为**构造—回放—分析**的轮次循环：

```text
Operator CodeMap
    → Coverage Domain D
    → Candidate → Host Replay → Round Analysis → Closure（Open = ∅）
```

Round Analysis 的具体路由见第 5 节；产品路径不含 CBM / 全局 Z3，权威证据只有 Host Replay（R）与经审查的源码引理（E）。

TG 的核心目标不是生成尽可能多的 testcase，而是回答：

> 对约定的覆盖范围，每一个目标最终由什么证据处理掉。

---



## 1. 从 CodeMap 建立覆盖范围

TG 不重新解析算子源码来定义 TilingKey 空间，而是消费 UO 已经生成的 CodeMap。

对于 TilingKey 覆盖，主要使用 UO 提供的：


| 信息                           | TG 中的用途                   |
| ---------------------------- | ------------------------- |
| TilingKey schema             | 确定维度和编码方式                 |
| legal key index              | 确定完整目标集合                  |
| packing relation             | 知道各维如何进入最终 TilingKey      |
| Host view                    | 知道 key field 与 Host 状态的关系 |
| graph fingerprint            | 判断 UO 是否仍与当前源码匹配          |
| TilingData / Kernel relation | 建立后续 runtime coverage     |


首先得到声明域：

```text
D = 当前算子和架构下声明的合法 TilingKey 集合
```

D 来自 UO 对 TilingKey 定义的展开，而不是 TG 自己从已有 testcase 中反推。

例如一个 TilingKey 由多个离散维度组成：

```text
InputDType × Layout × Template × SparseMode × ...
```

UO 负责确定每个维度的合法值和 packing，TG 将这些合法组合展开成具体的 TilingKey 集合。

固定 D 非常重要。

如果没有一个事先确定的目标域，就无法区分：

```text
尚未覆盖的合法 key
```

和：

```text
测试过程中偶然出现的新 key
```

因此真实 Replay 如果产生一个不属于 D 的 TilingKey，TG 不会自动把它加入目标集合，而是单独记录为：

```text
R - D
```

它代表 UO 声明域和真实 Host 行为之间可能存在不一致，需要作为独立问题调查。

---



## 2. 用证据账本表示覆盖

TG 将 TilingKey 覆盖表示为三个集合：

```text
D = declared keys
R = replay-confirmed reachable keys
E = proven unreachable keys
```

尚未处理的部分为：

```text
Open = D - (R ∩ D) - E
```

最终需要满足：

```text
D = (R ∩ D) ∪ E
R ∩ E = ∅
```

其中最重要的是 `R` 和 `E` 的来源不同。

### R：真实可达

一个 TilingKey 只有在真实 Host Replay 中被实际返回，才能进入 `R`。

下面这些都不能直接进入 R：

- Candidate 目标是这个 key；
- 模型预测会得到这个 key；
- 任何离线求解器/近似排序的候选；
- CodeMap 推导认为这个 key 可能可达；
- testcase 文件中手工写了这个 key。

真正的关系必须是：

```text
Case → Host Replay → actual TilingKey → R
```



### E：有证据的不可达

如果某个 D 中的 key 无法通过 testcase 命中，也不能因为搜索失败就认为它不可达。

只有能够建立可靠的源码证明，才允许进入 E：

```text
Source Constraint → Reviewed Proof → E
```

因此：

```text
搜索不到 ≠ 不可达
构造/排序失败 ≠ 不可达
Replay reject ≠ 不可达
```

这种划分使 testcase generation 和 reachability proof 不会混在一起。

---



## 3. 从 TilingKey 反向构造 testcase

一个 TilingKey 只是编译后的离散结果，而 testcase 需要的是完整输入：

```text
shape
dtype
layout
optional input
sparse mode
sequence
attribute
...
```

因此 TG 需要解决一个反向问题：

```text
target TilingKey → 什么输入可能让 Host 产生它？
```

直接对所有输入做笛卡尔积通常效率很低，因为 AscendC 算子输入之间存在大量耦合：

```text
shape ↔ layout
shape ↔ sequence
mask ↔ sparse mode
dtype ↔ template
optional input ↔ Host predicate
```

独立随机采样很容易生成大量 Host 直接拒绝的输入。

TG 使用两类方式生成 candidate。

### 从已有 witness 附近搜索

已经进入 R 的 testcase 是 Host 明确接受过的输入。

TG 优先从这些 testcase 出发，只改变少量可控参数：

```text
accepted Case
    → mutate 1~3 knobs
    → repair
    → new Candidate
```

这样可以尽量保留原 testcase 中已经满足的 shape、layout、mask 等约束。

同时保留一部分新的探索样本，避免搜索永远局限在已有 witness 周围。

这里的 `knob` 是 testcase 中可以调节的输入特征，例如：

```text
dtype
layout
B / S1 / S2 / D
mask
rope
optional input
...
```

具体 knob schema 由算子侧实现的 `InputSemantics` 协议提供（定义见 `scripts/replay/semantics.py`）；TG 通用引擎不维护某个算子的硬编码参数表。

### 根据 CodeMap 定向构造

当目标 TilingKey 已经明确时，TG 可以沿 UO 建立的关系反向寻找 testcase 参数：

```text
Target Key Dimension
        ↓
TilingKey Packing
        ↓
Host field / producer
        ↓
Host read / guard
        ↓
Input knob
        ↓
Case
```

例如目标 key 某一维要求：

```text
IsSparse = 1
```

TG 可以利用 CodeMap 查找：

```text
IsSparse
  → Host packing expression
  → Host field
  → producer / guard
  → 与输入相关的 knob
```

然后优先修改这些 knob，而不是随机修改所有输入。

这使 UO 和 TG 在这里真正接起来：

```text
UO：建立 Host → TilingKey 的正向关系
TG：沿这条关系反向寻找 testcase
```

对于算子特有、暂时无法由 CodeMap 通用表达的构造方式，可通过算子包中的 `construction_hints.yaml`（adapter 表）以及 `.ascendc-pilot/<arch>/local/` 下的本地扩展补充（见 [产物与权威](../architecture/artifacts-and-authority.md)）。

这些扩展负责“怎样生成候选”，但不负责判断候选是否正确。

最终是否命中仍然由 Host Replay 决定。

---



## 4. Host Replay 是可达性的判断依据

所有 Candidate 最终都必须进入 Host Replay。

```text
Candidate
   ↓
Host Tiling
   ↓
actual TilingKey
   ↓
Replay Evidence
```

TG 的 Oracle 实际上是 Host，而不是 LLM 或 surrogate model。

每个 replay case 会记录：

- case id；
- 是否成功执行；
- 实际 TilingKey；
- decoded key dimensions；
- reject reason；
- 必要的诊断信息。

TG 会区分几类不同结果：


| 结果           | 含义                 |
| ------------ | ------------------ |
| accepted     | Host 成功执行并得到实际 key |
| rejected     | Host 正常运行但拒绝输入     |
| crashed      | Host / driver 执行异常 |
| not run      | testcase 没有真正执行    |
| parse failed | replay 结果无法可靠解析    |


只有正常完成的 Host 结果才具有语义意义。

`crashed`、`not run` 和 `parse failed` 属于运行环境问题，不能被解释成“输入不可达”。

### Target 与 Actual 分开记录

Candidate 可以针对某个目标 key 构造：

```text
target = K1
```

但实际运行可能得到：

```text
actual = K2
```

这种情况不能算作 K1 已覆盖。

TG 会同时保留：

```text
target key
predicted key
actual key
mismatch dimensions
```

实际 K2 可以作为新的 replay witness 进入 R，但 K1 仍然保持 open。mismatch / rewrite 会作为下一轮 Round Analysis 的输入（见第 5 节）。

### R 从真实运行记录重建

TG 不只相信某个内存变量中的“已覆盖数量”。

R 会从实际 replay 产物重新汇总，包括：

```text
driver logs
replay result files
accumulated testcase tables
previous validated ledger
```

因此：

```text
R = all confirmed Host observations
```

如果新的 replay 与已有 exclusion 冲突，真实 Host 结果优先，原 exclusion 必须被撤销或重新验证。

---



## 5. 每轮 Replay 后立刻分析（Round Analysis）

**Round Analysis** 是概念名，由 workflow 的 `search → residual` 阶段完成，不是独立的 action 或 state。

主循环：

```text
构造 Candidate
    → Host Replay
    → Round Analysis（本轮立刻做；search → residual）
    → 更新 R / E / Open
    → 决定下一轮：lemma / construct / search / blocked
```

每轮 Replay 后重新计算：

```text
Open = D - (R ∩ D) - E
ΔR   = 本轮新进入 R 的 key
```

并对照本轮构造意图，看增长、target hit、rewrite/refuse 与 residual 分布。路由原则（不暴露内部 heuristic 阈值）：

```text
每轮 Replay 后：
  有源码证明线索（reject / source leads）→ lemma
  增长偏离且需定向 → construct（以已发现 R + 源码为锚）
  其余 → 继续 search / construct，或 blocked
```

例如：增长与意图一致且本轮有稳定 reject 时，趁热对 reject 做源码引理；增长落到无关 key 或系统性 rewrite 时，用 actual witness 解码差异维再定向构造。仍然遵守：

```text
Replay reject ≠ 不可达
```

只有完整源码证明通过后才能进 E。引理的 Producer / Referee / Finalizer 边界见 [Agent Runtime](../architecture/agent-runtime.md)；产物目录见 [产物与权威](../architecture/artifacts-and-authority.md)。

### Residual 服务本轮决策

residual 统计用于**决定下一轮怎么走**，不是攒到闭环前才用一次：open key 到最近 R 的距离、差异维 / rewrite 维、集中出现的组合模式。例如只差一维时，下一轮应直接改相关 knob 再 replay。

```text
某个组合从未出现在 R
```

只是线索，不是不可达证明。Residual 选择求解路径，不能自己关闭 coverage。

---



## 6. 基于已发现 key 的定向构造

当剩余 key 接近已有 witness，或本轮增长不符合预期时，TG 进入定向 construct，而不是大范围盲搜。

例如：

```text
reachable:
A=0 B=1 C=0 D=1

target:
A=0 B=1 C=1 D=1
```

针对变化的 `C`：

```text
C
→ TilingKey packing
→ Host producer / guard
→ input knob cone
→ mutate known witness
→ replay
→ Round Analysis
```

增长不符合预期时，同样以本轮实际落到的 key 为锚：

```text
target = K1, actual = K2
    → 记录 mismatch dimensions
    → 用 K2 witness + 源码解释 rewrite
    → 下一轮只改相关 knobs 再打 K1
```

Construct 的输出仍然只是 candidate。

如果构造器：

- 生成不了 testcase；
- Host reject；
- Host 返回其他 key；

目标都仍然保持 open；结果进入当轮 Round Analysis（第 5 节），而不是留到最后统一处理。

因此：

```text
construct failure ≠ unreachable
```

---



## 7. 轮内源码引理：proof contract

当 Round Analysis（第 5 节）路由到 lemma 时，目标不是“这轮没找到”，而是：

> 对所有合法 Host 执行路径，该模式不可能产生目标 key。

**可进 E 的证据**：经 Referee 审查的源码证明，且先与已有 R 反证（`Real Replay > Static Proof`）。Reject / residual 线索本身不能关闭 coverage。

**分工**：

```text
Producer → Staging lemma proposal
Referee → 资格审查
Deterministic Finalizer → 更新 E / Open
```

权限边界见 [Agent Runtime](../architecture/agent-runtime.md)。

```text
本轮 Reject / Residual Pattern
    → Source Evidence → Lemma Proposal
    → Check against R → Review → Deterministic Apply → E
```


### 先从真实 witness 反证

任何源码引理在进入 E 前，都先与已有 R 比较。

如果一个规则声称：

```text
A=1 && B=0 不可达
```

但 R 中已经存在一个这样的真实 Host witness，那么这个规则立即被反驳。

```text
Real Replay > Static Proof
```

这一步可以挡住很多由于漏读赋值路径、early return、alias 或宏条件产生的错误结论。

### 源码证明需要完整范围

一个 exclusion 不能只引用一行 `if` 就结束。

证明需要说明所检查的范围，例如：

- 目标维度；
- 相关函数；
- 所有相关赋值位置；
- guard；
- entry branch；
- early return；
- alias / writer；
- 执行顺序；
- 可能改变结论的异常路径。

同时需要源码位置或 evidence entry，使后续能够重新检查。

如果证据不完整，结果保持 open，下一轮继续构造或换锚点，而不是为了完成 coverage 把它加入 E。

### 规则需要随源码重新验证

源码变化或者 UO fingerprint 变化后，已有 exclusion 不能永久有效。

TG 会重新检查 active rule 的来源和 freshness。

如果新一轮 Replay 产生了与旧规则冲突的 witness：

```text
new R ∩ old E ≠ ∅
```

则冲突规则会被撤销，并重新计算 E，再继续轮次循环。

---



## 8. L2：TilingKey 覆盖

TG 的第一层主要目标是 TilingKey closure。闭合不是“先搜完再证明”，而是由第 5–7 节的轮次循环逐步完成：每轮扩大 R，并在适当时机把可证明不可达的目标推进 E。

对于每个：

```text
key ∈ D
```

最终必须得到以下两种结果之一：

```text
Host Replay Witness → R
```

或者：

```text
Verified Unreachable Proof → E
```

最终满足：

```text
D = (R ∩ D) ∪ E
```

L2 解决的是：

> 哪些 TilingKey 真正能够被 Host 产生？

但一个 TilingKey 被命中，并不代表这个 key 下所有 runtime 行为都已经覆盖。

因此在 L2 闭合之后还可以继续进入 L3。

---



## 9. L3：TilingData 与 runtime branch 覆盖

同一个 TilingKey 下仍然可能存在不同的运行时状态。

例如：

```text
same TilingKey
   ├→ TilingData.x = 0 → branch A
   └→ TilingData.x > 0 → branch B
```

所以 L3 不再重新枚举 TilingKey，而是在**已经确认可达的 key 内部**建立 runtime obligations。

L3 只有在 TilingKey closure 完成后才开始：

```text
L2 gap = 0
    ↓
reachable key ∈ R
    ↓
TilingData / runtime branch obligations
```



### TilingData obligation

TG 根据 UO 中的 TilingData 信息关注会影响行为的字段，例如：

- control field；
- boundary field；
- 带风险标记的 payload field。

纯派生且不形成独立行为区间的字段不会机械地扩展成大量 testcase。

对于重要字段，可以建立类似：

```text
field == 0
field != 0
field in boundary class
```

这样的 value-class obligation。

### Kernel runtime branch obligation

首先将已知 TilingKey dimensions 代入 Kernel branch。

如果 branch 在 key 确定后已经是编译期固定结果，就不需要作为 runtime 搜索目标。

仍依赖 TilingData 或运行时状态的 branch 会转化为：

```text
(key, branch, true)
(key, branch, false)
```

这样的 outcome obligation。

### L3 testcase 构造

L3 从一个已经可以命中目标 key 的 testcase 开始：

```text
known same-key witness
    ↓
找到目标 TilingData / branch 的 producer cone
    ↓
修改相关 input knobs
    ↓
Host Replay
```

最重要的限制是：

> 修改输入后，actual TilingKey 必须仍然等于目标 TilingKey。

如果 candidate 原本想覆盖：

```text
K1 / branch=true
```

但 Host Replay 返回了 K2，那么不能给 K1 的 runtime branch 记覆盖。

### 从 Replay 中读取 TilingData

Host Replay 可以输出原始 TilingData 数据。

TG 优先使用 UO 提取的 TilingData layout 和通用 decoder：

```text
raw TilingData
   → UO layout
   → generic decoder
   → field values
```

如果某个算子的 layout 无法被通用 decoder 完整表示，可以使用 operator-local `tilingdata_decoder` 扩展。

解码失败时，对应 obligation 保持 open。

不会因为 candidate “理论上应该让字段等于某个值”就直接计入 coverage。

### 实际观察 branch outcome

解码 TilingData 后，TG 构建当前 replay 的 runtime environment，再判断对应 Kernel predicate 的实际 outcome。

只有真实观察到：

```text
same target key
+
required TilingData state
+
required branch outcome
```

才将该 runtime obligation 标记为 `COVERED`。

因此 L2 和 L3 的区别是：


|              | L2                         | L3                          |
| ------------ | -------------------------- | --------------------------- |
| 覆盖对象         | TilingKey                  | 同一 key 下的 runtime behavior  |
| 基础集合         | declared key D             | reachable keys R            |
| 主要观察         | actual TilingKey           | TilingData + branch outcome |
| Candidate 要求 | 尝试命中目标 key                 | 必须保持 target key 不变          |
| 完成条件         | 每个 D key 有 witness 或 proof | runtime obligations 全部有有效结果 |


---



## 10. 闭环检查

TG 不以“已经跑了很多 testcase”作为完成条件。

L2 至少需要检查：

```text
D = (R ∩ D) ∪ E
R ∩ E = ∅
```

同时保证：

- R 中每个 key 都有真实 Replay 来源；
- E 中每个 key 都有经过验证的 exclusion evidence；
- exclusion rule 与当前 UO fingerprint 一致；
- 规则包含可追踪的源码证据；
- candidate、heuristic、LLM 结论不能直接缩小 open set；
- `R - D` 被单独报告，而不是偷偷扩充 D。

L3 还要求对应 runtime obligation 已经闭合，不能只因为 L2 的 key gap 为 0 就声明 runtime coverage 完成。

最终每个目标都应能够追溯到：

```text
Target
  → Witness Case / Exclusion Rule
  → Replay / Source Evidence
```

这样 testcase 集本身和“为什么认为已经覆盖”是可以分开审计的。

---



## 11. TG 的三个阶段

对外使用仍然保持三个入口：


| 阶段          | 主要工作                                                          |
| ----------- | ------------------------------------------------------------- |
| `/tg-init`  | 读取 UO，固定算子、架构、TilingKey domain 和 fingerprint；`human_confirm` 经 AskQuestion 后 finalize 写出 `tg/init/confirmation.yaml` |
| `/tg-plan`  | 将覆盖目标转成明确 obligation；`plan_approve` 经 AskQuestion 后写出 `human_supplement.yaml` |
| `/tg-solve` | 轮次循环：构造 → Replay → Round Analysis（search→residual；lemma / construct / search）→ 直至闭环 |


可以简化理解为：

```text
/tg-init
   ↓
What must be covered?
AskQuestion → human_confirm --finalize

/tg-plan
   ↓
What are the obligations?
AskQuestion → plan_approve --finalize (owns human_supplement.yaml)

/tg-solve
   ↓
Each round: construct → replay → analyze
What evidence closes each obligation?
```

`/tg-solve` 内部按轮自动分支：

```text
增长符合预期 → 消化本轮 reject（源码引理 → E）并继续有效方向
增长不符合预期 → 基于已发现 key + 源码定向构造下一轮
```

不要求用户手工选择每一轮策略，也**不把引理证明留到最后统一做**。

---



## 12. TG 产物

TG 的主要产物位于：

```text
.ascendc-pilot/<arch>/tg/
```

主要包括：


| 目录          | 内容                                    |
| ----------- | ------------------------------------- |
| `init/`     | UO identity、fingerprint 和初始化结果        |
| `contract/` | TilingKey coverage contract           |
| `plan/`     | coverage obligations 和目标范围            |
| `replay/`   | Host Replay 相关产物                      |
| `closure/`  | R、E、open、residual、proof 和 certificate |


其中最重要的不是某个 testcase CSV，而是最终能够回答：

```text
哪些 key 被真实运行证明可达？
哪些 key 被源码证明不可达？
还有哪些目标没有处理？
每个结论对应的证据是什么？
```

可以概括为：

```text
UO .uo
  ↓
Declared Domain D
  ↓
┌──────────────────────────────────────┐
│ Round:                               │
│   Candidate Generation               │
│       → Host Replay                  │
│       → Round Analysis               │
│         (search → residual)          │
│            → lemma / construct /     │
│              search / blocked        │
└──────────────────────────────────────┘
  ↓（重复直到）
Open = D - (R ∩ D) - E = ∅
  ↓
Coverage Certificate
```

TG 对 UO 是只读消费者。源码或 BuildVariant 变化后，应先更新 UO，再重新检查 TG 中依赖旧 CodeMap fingerprint 的计划、规则和覆盖结果。

---

TG 的核心实现位于 `engines/testcase-generation/testcase_agent/`。其中 `product_uo.py` 负责读取 UO 产品，`closure/ledger.py` 管理 D/R/E，`closure/generate.py` 与 `closure/construct.py` 负责 testcase 搜索和定向构造，`closure/oracle.py` 负责 Host Replay 判断，`closure/residual.py` 负责每轮剩余目标与增长分析，`closure/lemma.py` 负责轮内不可达规则的验证与应用，`branch_runtime.py` 负责 L3 TilingData 和 runtime branch coverage。Pilot 侧负责组织 `/tg-init`、`/tg-plan` 和 `/tg-solve` 的执行与最终检查。