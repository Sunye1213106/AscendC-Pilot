# TilingKey 全覆盖闭环：方法论与 Agent 化

这份文档记录 FlashAttentionScoreGrad arch35 把 8705 个声明 TilingKey 全部判定完毕的完整过程，以及如何把它变成一个可以对任意算子跑的 agent。结果报告见 [`tilingkey-closure-report.md`](../fag/tilingkey-closure-report.md)。

**起点是 `R = 0、E = 0`**。仓库里此前留有一份账本（R=2738、E=3632），本流程不采信它的任何结论：R 从 driver 的原始输出重算，E 的每一条引理都重新推导、重新过反例检验。既有的历史运行记录只作为**输入数据**复用，省去重新采样的机器时间。

这个口径不是形式主义。第一步重算就发现旧账本少算了 150 个早已命中的 Key（见阶段 1），而继承来的三组引理里有一条如果照字面理解会错误排除 261 个真实可达 Key（见 6.5）。

---

## 1. 问题形式化

设：

- **D** = 内核声明的 TilingKey 集合（从 `*_template_tiling_key.h` 解析，本例 8705 个）
- **R** = 真实 Host 运行产生过的 Key 集合（witness set）
- **E** = 有源码证明不可达的 Key 集合（certificate set）

**闭合目标**：

```
D = (R ∩ D) ∪ E     且     R ∩ E = ∅
```

一个 Key 只有两种合法归宿：跑出来过，或者证明跑不出来。"跑了很多次没出现"不是归宿。

这里有一条贯穿全程的**单边原则**：

> 近似模型（学出来的、拟合的、统计的）**只能用于生成和排序候选，永远不能用于排除 Key**。排除只能由源码证明给出。

违反这条原则会制造"假 100%"——模型拟合错了一个节点，就会把一批真实可达的 Key 判成不可达，而且没有任何机制能发现。

---

## 2. 为什么纯静态和纯黑盒都做不到

### 纯静态符号执行的墙

对 FAG 做完整语义提取的产物 `fag_derive.json` 显示：19 个 Key 维度里 14 个 `derived/exact`，5 个 `partial/overapproximated`。卡住的原因有三类：

| 原因 | 例子 | 表现 |
| --- | --- | --- |
| 循环定义 | `DeterType` | `note: CYCLIC_DEFINITION: blockOuter, deterSparseType, isDeterministic`，三者互相依赖成环，符号执行无法定点展开，只能过近似 |
| 叶子塌缩 | `DeterType` | `LEAF_COLLAPSE: 1,3,4`——5 个取值里有 3 个被压成不可区分的叶子 |
| 自由变量 | `SplitAxis` | 表达式含 `invalidS1Array[j]`、`bandIdx` 等循环元素，无法闭式化；`value_expr` 已膨胀到 3348 节点、12 万字符 |

同时 `SplitAxis` 的 `input_closure` 是 `host_state` 而非 `controllable`——它读的是 `fBaseParams` 中间状态，不是输入的直接函数。

### 纯黑盒学习的墙

反过来只跑随机 fuzz 也不行。本例的历史语料有 93,479 行真实运行、40,182 个不同输入，但只产出 2888 个不同 Key——**平均 14 次运行才换一个新 Key**，而且曲线早已平坦。原因是输入空间里绝大部分组合是非法的或高度重复的，随机采样打不到稀有角落。

更根本的问题是：黑盒学习**无法证明不可达**。8705 个声明 Key 里有 4536 个（52%）根本就不该存在 witness，光靠跑永远收敛不了。

### 结合点

静态分析给的不是公式，是**依赖骨架**——哪个维度读哪些输入。这个骨架即使在表达式解不出来时也是对的。实测印证了这一点：

| 节点 | 多数类基线 | 只用静态父节点 | 用全部旋钮 |
| --- | ---: | ---: | ---: |
| SplitAxis | 0.862 | **0.971** | 0.971 |
| DeterType | 0.450 | 0.668 | **0.984** |
| IsBn2MultiBlk | 0.974 | 0.987 | 0.988 |
| IsNzOut | 0.966 | 0.972 | 0.985 |
| IsTndSwizzle | 0.954 | 0.984 | 0.982 |
| IsTnd | 0.670 | 0.981 | 0.986 |

`SplitAxis` 静态父节点已经等于全旋钮——骨架完全正确，缺的只是闭式。`DeterType` 差 32 个点——静态因为环丢掉了 `sparse_mode`、`band` 这些父节点，数据能补回来。按 layout 分组外推（拿四种 layout 训练、预测第五种）准确率仍有 0.94~1.00，说明学到的是规则不是记忆。

---

## 3. 端到端流程

假设手上只有算子源码和一台能跑 Host tiling 的机器，从零开始。

```
阶段 0  建立 oracle          真实 Host replay 可跑、可读中间状态
阶段 1  建立账本             从原始记录算出 R，不采信任何既有结论
阶段 2  静态骨架             提取依赖图，标注每个节点的可解程度
阶段 3  代理模型             用真实语料拟合难节点，测留出与外推
阶段 4  定向生成             模型选目标 → Host 裁决 → 反例回流
阶段 5  构造式收尾           按目标维度反推输入，用反例定位卡点
阶段 6  引理封口             对剩余 Key 找源码证明，逐条验反例
```

阶段 4 和 5 提升 R，阶段 6 提升 E，两边同时挤压 gap 直到为零。

---

### 阶段 0：建立 oracle

**目标**：能把一个输入喂给真实 Host tiling，拿回 TilingKey、19 维取值、中间状态和拒绝原因。

三样东西缺一不可：

1. **driver**：加载算子 host so，按 CSV 喂输入，打印 `###CASE` / `###DONE ok= key=` 标记
2. **日志协议**：把算子自己的 `OP_LOGD` 行 scrape 成结构化字段
3. **输入语义**：把旋钮（layout/dtype/b/s1/s2/...）展开成 Host 要的 shape + dtype + attr

第 2 点是最容易被忽略、也最关键的。如果只能拿到最终 packed Key，你只知道"IsNzOut 没翻过来"，不知道是 `enableSwizzle` 没开、还是 `splitAxis` 不对、还是 d 不在窗口里。本例的 `log_protocol.yaml` scrape 了：

```yaml
- into: dim                       # 19 维在打包前的原始值
  when: ['GetTilingKey', 'splitAxis[']
- into: state                     # isExceedL2Cache / enableSwizzle / sparseType
  when: ['isExceedL2Cache']
- into: state                     # GetSparseType 的五个条件
  when: ['OpName:[GetSparseType]']
reject:                           # 拒绝原因
  when: ['[ERROR]']
```

**判据**：随便造 10 个用例送进去，能拿到 Key、19 维、至少一个中间状态、以及非法用例的拒绝原因。

**这一步的坑**：oracle 本身的可信度必须先立住。本例发现了三个 oracle 层面的缺陷，任何一个都会让后续结论失真：

- driver 崩溃后批次静默截断，未跑的用例被记成"被拒绝"（1500 送进去只跑了 249）
- 宽表 CSV 的 `tag` 字段含逗号导致 16% 的行列错位
- `compileInfo.npuArch` 漏填，导致一整条 tiling 分支从未被触达

所以阶段 0 的真正终点不是"能跑"，而是"跑的结果可信"。

---

### 阶段 1：建立账本

**目标**：从 `R = 0` 出发，用最原始的证据把 R 算出来。

**做法**：最权威的口径是 driver 自己打印的 `###DONE ... ok=1 key=N`。若已有历史运行记录，把它们当数据复用；若从零开始，这一步就是先跑一批种子用例。任何形式的"上游给的覆盖率数字"都不作为 R 的来源。

```python
# vg_ledger.py：三个来源取并集
#   logs  —— driver 的原话，但同名批次会互相覆盖
#   csvs  —— 累积的宽表，但历史上有引号 bug
#   carry —— 上一轮账本
```

本例的历史记录算出 R=2888，比旧账本的 2738 多出 **150 个早已命中但没被计入的 Key**，零机器时间。

**判据**：三个来源的并集稳定，且能解释每个来源单独缺失的原因（本例：日志因同名批次被覆盖而缺 629 个，宽表因引号 bug 而缺 9 个）。

---

### 阶段 2：静态骨架

**目标**：拿到每个 Key 维度的依赖父节点集合，以及"这个节点解到了什么程度"的标注。

从 `fag_derive.json` 每个字段读：

| 字段 | 用途 |
| --- | --- |
| `status` / `exactness` | 节点分级：exact / partial / overapproximated |
| `variables` + `var_roots` | 父节点集合，及每个父节点的来源类别（ATTRIBUTE / INPUT_SHAPE / TILING_DATA / ...） |
| `state_targets` | 依赖的 Host 中间状态（这些要靠日志观测，不能靠输入直接算） |
| `free_vars` / `undecided` | 解不出来的自由变量，说明卡点在哪 |
| `note` | `CYCLIC_DEFINITION` / `LEAF_COLLAPSE` 等失败原因 |
| `def_sites` | 赋值点的文件行号——阶段 6 找证明时的起点 |

把节点按可解程度分成四级，后续处理方式不同：

| 级别 | 含义 | 处理 |
| --- | --- | --- |
| `exact_static` | 静态可精确计算 | 直接用规则反推输入 |
| `observed_exact` | 静态算不出，但 Host 日志直接打印 | 用观测值，保留为中间节点 |
| `empirical` | 都不行，靠真实样本拟合 | 只用于生成候选 |
| `set_valued` | 拟合也不确定 | 输出候选集合而非单值，宁可多生成不可错排除 |

`set_valued` 这一级很重要：它保证近似图出错时只是多生成候选，而不会错误地排除真实 Key。

**判据**：每个 Key 维度都有父节点列表和级别标注；`def_sites` 能定位到源码。

---

### 阶段 3：代理模型

**目标**：为难节点建立"输入 → 该维度取值"的可用近似，并**如实测出它有多可用**。

```python
# vg_feat.py  特征构造
# vg_fit.py   拟合与评估
```

三个设计要点：

**特征要包含源码里比较的那些量。** 决策树只能做轴对齐切分，造不出乘积。源码里比的是 `b*n1*s1*s2*dtype_bytes` 和 `s1 % 128`，就得把它们显式加进特征：

```python
f["n1"]       = f["n2"] * f["g"]
f["bn1s1s2"]  = f["b"] * f["n1"] * f["s1"] * f["s2"]
f["qkv_bytes"]= (f["bn1s1"] * f["d"] + 2 * f["bn2s2"] * f["d"]) * f["bytes"]
f["s1_mod128"]= f["s1"] % 128
f["band"]     = (f["pre_tokens"] < f["s1"]) + (f["next_tokens"] < f["s2"])
```

这些量应当**从源码的比较式里提取**，而不是让模型无限猜。

**按输入去重再切分。** Host 是确定性的，同一个输入重复出现不带任何新信息。在训练过的输入上评分等于没评。

**同时报三个数**：多数类基线、只用静态父节点、用全部旋钮。三者的关系直接告诉你下一步该做什么：

- 静态 ≈ 全旋钮，且都远高于基线 → 骨架正确，可以直接用来反推
- 静态 << 全旋钮 → 静态丢了父节点，去 `note` 里看是不是环导致的
- 两者都 ≈ 基线 → 这个粒度下它就不是输入的函数，别再拟合了，去阶段 6 找证明

**判据**：留出准确率、按 layout 分组的外推准确率都有数；知道每个难节点属于上面三种情况的哪一种。

---

### 阶段 4：定向生成与反例回流

**目标**：用模型把 R 推高。

核心循环：

```
拟合 19 个维度模型（含一个"Host 会不会接受"的模型）
    ↓
生成候选池 → 预测 19 维 → 打包成预测 Key
    ↓
筛出预测 Key ∈ 未覆盖目标集 的候选
    ↓
真实 Host 裁决
    ↓
所有被裁决的结果（命中、未命中、被拒绝）回流训练集
    ↓ 重复
```

**A/B 对照是必须的**，否则无法区分"模型有用"和"多跑了几批"。同池、同规模、两条臂：

| 臂 | 真跑用例 | 新增声明 Key | 单位用例产出 |
| --- | ---: | ---: | ---: |
| 模型定向 | 248 | 84 | 0.34 |
| 同池随机 | 405 | 12 | 0.03 |

**11 倍**，且两臂找到的 Key 零重叠。

**候选生成要从 witness 变异，不能纯随机。** 这是本流程提效最大的一处改动：

```python
# vg_direct.py  pool()
#   65% 从已被 Host 接受的输入出发，随机改 1~3 个旋钮
#   35% 全新随机采样，保留探索性
```

原因是 shape / mask / sparse / 序列这些旋钮之间有一致性约束，独立采样几乎必然冲突。从 witness 出发改两个旋钮，大部分一致性得以保留。实测接受率从 **10% 提升到 80~88%**，单位用例产出从 0.10 提到 0.38。

**只把真正被裁决的结果回流。** driver 崩溃或没跑到的用例不是关于算子的证据，把它们当负样本会教模型躲开完全正常的输入。这需要 runner 能区分三种状态：

```python
CRASHED = "HOST_CRASHED"   # driver 死在这个用例上
NOT_RUN = "NOT_RUN"        # 重试预算耗尽都没跑到

@property
def verdict(self) -> bool:
    """Host 是否真的给出了裁决"""
    return not self.reject.startswith((CRASHED, NOT_RUN))
```

**判据**：逐轮新增 Key 数不衰减到 0；接受率稳定在高位；R 持续增长。

本例 6 轮从 2986 涨到 3502，逐轮新增 75 → 107 → 110 → 140（目标越来越难反而增产，因为反例在改进模型）。

---

### 阶段 5：构造式收尾

当定向生成饱和（连续几轮零产出），说明剩下的 Key 采样打不到。此时切换策略。

**第一步：看剩余 Key 离最近 witness 有多远。**

```python
# vg_residual.py
#   对每个 open Key，找汉明距离最近的 witness，记录差异维度
```

本例某个时点：645 个 open，其中 **643 个距离某 witness 只差 1 维**。这说明它们大概率可达，只是采样命中概率太低。

**第二步：定点补齐。** 取最近 witness 的**真实输入**，只扫该差异维度对应的旋钮：

```python
KNOBS = {
    "DTemplateNum":  [("d", [64, 128, 192, 256, 512])],
    "IsDrop":        [("keep_prob", [1.0, 0.5])],
    "IsAttenMask":   [("atten_mask", ["none", "ss", "bnss", "b1ss", "11ss"])],
    "DeterType":     [("deterministic", [0, 1]), ("sparse_mode", [0,1,2,3,4,5,6])],
    ...
}
```

这一步会很快饱和（本例 16 → 3 → 0）。饱和本身是信号：**改 D 却改不出目标 DTemplateNum，说明存在稳定耦合，而稳定耦合就是引理。**

**第三步：构造式生成。** 到这个阶段每个维度的来源都已清楚，可以把目标 Key 当规格书直接反推输入：

```
InputDType=1     → dtype = FLOAT
DTemplateNum=768 → d > 256
IsDrop=1         → keep_prob < 1
DeterType=3      → deterministic=1, sparse_mode=2
IsNEqual=1       → g == 1
IsTnd=1          → layout=TND 且序列长度不全相等
                   （全相等会被 SupportTrans2BS2N2GD 转成 BS2N2GD）
```

**第四步：用反例定位卡点。** 这是整个流程里信息密度最高的一步。构造式生成的用例被 Host 接受、却没产出目标 Key 时，逐维对比"要的"和"得到的"：

```text
# vg_why.py 的输出：Host 坚持替换掉的维度
   维度               要的        给的        次数
   S1TemplateNum      128        64          720
   IsTnd              1          0           240
```

720 个被接受的用例，Host 一律把 `S1TemplateNum` 从 128 压成 64。这不是失败，这是**算子在告诉你它的约束**。带着这个现象去查 `GetS1S2TemplateType`，第一个分支就是答案，一条引理关掉 192 个 Key。

**判据**：剩余 Key 要么被找到 witness，要么产生了明确的"Host 坚持替换某维度"的现象可供追查。

---

### 阶段 6：引理封口

**目标**：为剩余 Key 找源码级不可达证明。E 从 0 开始，每一条都要自己推出来。

如果算子仓里已经带了一份规则文件，**先把它当候选而不是当结论**：逐条重新推导、逐条过反例检验（见 6.5）。本例继承的三组规则支撑着 3632 个排除，重推之后两组原样通过，一组的边界需要修正。

#### 6.1 候选挖掘

从真实数据里挖"从未共现"的维度取值组合，但**只作为线索**，按杠杆排序：

```python
# vg_mine.py   二元组
# vg_mine3.py  三元组
```

两个防噪守卫：

- **support**：组合的每一半（或三元组的每一对）在 witness 里必须有足够支撑，否则说明只是没探索到
- **open**：这个组合能解释多少个还没判定的 Key，决定值不值得花时间读源码

三元组不能省。源码里的条件常常是析取式：

```cpp
(keepProb >= 1 || (d <= NUM128 && keepProb < 1))
```

这不禁止任何一对维度，它禁止的是一个三元组（这条路径 + 有 dropout + 大 D）。二元挖掘看不见。本例三元挖掘出的第一条候选就是从源码独立预测出来的同一条，两条路径互相印证。

#### 6.2 引理推导的三条路径

实际用到的三种，按可靠性排序：

**路径 A：从合取式直接读。** 最简单。`isBn2MultiBlk` 是个长合取，末尾是 `(d == d1) && !hasRope`，而 `dNoEqual = (d1 != d) || hasRope`，两者直接对偶。

**路径 B：追赋值点与执行顺序。** 需要小心。`IsTnd=1 + IsBn2MultiBlk=1` 这条要走三步：

1. `isBn2MultiBlk` 依赖 `bnSparseLimit`，后者要求 `layoutType != TND`
2. 但 `layoutType` 后面还有一处能改回 TND（第 1638 行）
3. 那一处被 `!isBn2` 守卫，而第 1603 行 `isBn2 = isBn2MultiBlk ? true : isBn2` 已经把 `isBn2` 强制为真

**这一步差点出错。** 只看第 1 步就下结论的话，第 1638 行会推翻整条引理。凡是涉及"某字段在后面还会被改写"的证明，都必须把该字段的**所有赋值点**列出来逐一排除。查赋值点的正则很简单：

```
fBaseParams\.(layoutType|hasRope|d1|d)\s*=[^=]
```

**路径 C：从运行时反例反查。** 前两条是"读代码找规律"，这条是"让算子告诉你规律"。阶段 5 第四步的 `S1TemplateNum: 128 → 64` 就是这么来的。当维度耦合复杂到读不出来时，这是唯一可行的路径，而且效率极高——一次反例分析直接指向一个函数的第一个分支。

#### 6.3 每条引理必须过两道关

**第一关：源码引用。** 规则必须写明文件名和行号，说清楚推理链。"我们从没找到过"不是理由。

`proof_rules.yaml` 里每条规则都要配一段 `combo_evidence`，说明它读的是哪一段源码、推理链怎么走（该文件本身用英文书写，与仓库其余配置保持一致）：

```yaml
combo_evidence:
  fp32_wide_d_fixes_s1: >
    GetS1S2TemplateType's first branch is
    (queryType == ge::DT_FLOAT && d > NUM256), and it returns the fixed pair
    (NUM64, NUM128) (common_regbase.cpp:812-816). DTemplateNum is 768 exactly
    when !hasRope and d > NUM256 (common_regbase.cpp:847-866) ...
```

对应的中文含义是：`GetS1S2TemplateType` 的第一个分支条件为 `queryType == DT_FLOAT && d > 256`，命中后直接返回固定的 (64, 128)；而 `DTemplateNum=768` 当且仅当 `!hasRope && d > 256`。两者条件重叠，所以 fp32 大 D 场景下 `S1TemplateNum` 只能是 64。

**第二关：全量反例检验。** 拿全部 witness 跑一遍，只要有一个满足这条规则的 `when`，规则就被推翻，不予采纳。

```python
# vg_verify_rules.py
hits = [w for w in wit if all(w.get(d) == v for d, v in when.items())]
if hits:
    print("REFUTED")   # 不写入
```

这道关是在规则**产生之前**执行的，比运行时门禁更早。

#### 6.4 生成 E_sound 时的硬门禁

```python
# vg_exclude.py
bad = {k: v for k, v in excluded.items() if k in Rset}
if bad:
    print("REFUTED RULES -- a real run produced these")
    return 1          # 拒绝写出结果
```

任何被规则判为不可达、却存在真实 witness 的 Key，都让整个流程报错退出。这是防"假 100%"的最后一道防线。

#### 6.5 继承来的引理必须重新推导

仓库里带过来的规则不能直接信。本例继承了三组（rope 强制 D=192、swizzle 与确定性互斥、无 mask 时 deter 类型受限），支撑着 3632 个排除。重新推导的过程验证了前两组、并在第三组上发现了一个**必须处理的例外分支**。

第三组的字面表述是"无 attenMask 就不是 sparse，因此 deter 类型受限"。但 `SetSparseParams` 的第一件事是分流：

```cpp
if (sparseMode == PREFIX || sparseMode == PREFIX_COMPRESS) {
    return SetPrefixSparseParams(context_, fBaseParams);   // 不看 attenMask
}
if (sparseMode == ALL_MASK || attenMaskOptional == EMPTY_TENSOR) {
    return false;
}
```

PREFIX(5) / PREFIX_COMPRESS(6) 会绕开 attenMask 判断，可能在没有 mask 的情况下 `isSparse=true`。顺着 `GetDeterSparseTilingKey` 逐分支走下去，这条路径落到最后一行返回 `DETER_OLD = 1`。

于是引理的正确边界是 **DeterType 3 和 4 不可达，但 1 可达**。这给出一个可证伪的预测，数据完全对上：

| IsAttenMask=0 时的 DeterType | witness 数 |
| --- | ---: |
| 0 | 601 |
| 1 | **261** |
| 2 | 643 |
| 3 | 0 |
| 4 | 0 |

如果照字面把引理写成"无 mask 时 DeterType 只能是 0 或 2"，就会错误排除 261 个真实可达 Key。反例检验会当场拦下（这正是它存在的意义），但更好的做法是推导时就把例外分支读进去。

**给 agent 的规则**：任何形如"A 蕴含 B"的引理，都要先找齐 A 的**所有**入口分支。有 early return 或分流的函数尤其危险——`SetSparseParams` 的分流在第一行，漏看它就会把边界画错。

---

## 4. 做成 Agent

### 4.1 状态机

Agent 的状态就是三个集合和一本规则书：

```
State = (D, R, E, RuleBook, Corpus, Models)
```

不变式（每步之后都要成立）：

```
I1.  R ∩ E = ∅                       健全性
I2.  R 只因真实 witness 增长          不接受模型推断
I3.  E 只因带源码引用的引理增长        不接受统计证据
I4.  每条引理都通过了全量反例检验
```

终止条件：`D = (R ∩ D) ∪ E`。

### 4.2 主循环

```
while gap > 0:
    gap = D - (R ∩ D) - E

    residual = analyse(gap)          # 距离分布 + 阻塞维度分布

    if residual.mostly_distance_1 and not saturated:
        # 还有近的目标，继续推 R
        R ∪= directed_search(models, corpus, gap)
        corpus ∪= judged_results
        models  = refit(corpus)
    else:
        # 采样饱和，转证明
        leads = mine_pairs(R, gap) + mine_triples(R, gap)
        for lead in rank_by_leverage(leads):
            proof = find_source_evidence(lead)      # 三条路径
            if proof and refutation_check(lead, R):
                RuleBook += Lemma(lead, proof)
        E = apply(RuleBook, D)
        assert R ∩ E == ∅

    if no_progress_this_round:
        escalate()                   # 见 4.4
```

**关键的调度决策是"什么时候从推 R 切换到证 E"**。判据不是轮数，而是：

- 定向生成连续 N 轮零产出，且
- 剩余 Key 的最近距离分布没有改善

反过来，如果引理挖掘找不到有支撑的候选，说明该回去推 R。

### 4.3 工具集

| 工具 | 输入 | 输出 | 对应脚本 |
| --- | --- | --- | --- |
| `replay(cases)` | 输入列表 | Key + 19 维 + 中间状态 + 拒绝原因 + **是否真的被裁决** | `runner.py` |
| `ledger()` | 所有产物 | R，含每个 Key 的来源 | `vg_ledger.py` |
| `fit(corpus)` | 语料 | 19 个维度模型 + 合法性模型 | `vg_direct.fit_models` |
| `generate(models, targets)` | 模型 + 目标集 | 候选输入 | `vg_direct.pool` |
| `residual(R, gap)` | 两个集合 | 距离分布 + 阻塞维度 | `vg_residual.py` |
| `mine(R, gap, arity)` | 两个集合 | 排序的候选引理 | `vg_mine.py` / `vg_mine3.py` |
| `explain(target, results)` | 目标 + 运行结果 | Host 坚持替换了哪一维 | `vg_why.py` |
| `verify(lemma, R)` | 引理 + witness | 通过 / 被推翻 | `vg_verify_rules.py` |
| `exclude(RuleBook, D)` | 规则书 | E_sound（带门禁） | `vg_exclude.py` |
| `closure(D, R, E)` | 三集合 | 逐 Key 判定报告 | `vg_closure.py` |

### 4.4 需要人（或更强推理）介入的点

Agent 能自动化阶段 0-5 的绝大部分，以及阶段 6 的候选挖掘和反例检验。**引理的源码证明这一步需要真正的代码推理**，因为它要求：

- 沿着赋值点和执行顺序做数据流分析
- 判断某个后续赋值是否被守卫排除
- 区分"算子的语义约束"和"输入生成器的表达能力不足"

最后这一条尤其关键。`IsRope=1 + IsDNoEqual=0` 从数据上看是完美的引理候选（264 个 rope witness 无一例外），但生成器恰好在 rope 时强制了 `d1=None`——如果不去查源码，就无法区分是算子如此还是工具如此。查到 `dNoEqual = (d1 != d) || hasRope` 才敢采信。

**escalate() 的触发与动作**：

| 现象 | 可能原因 | 动作 |
| --- | --- | --- |
| 构造的用例全被拒绝 | 输入语义缺一致性约束 | 读拒绝原因，补生成器（如 `slope` 形状必须配 `pse_type ∈ {2,3}`） |
| 用例被接受但某维恒被替换 | 存在未知约束 | 走引理推导路径 C |
| 某维度从未观测到某取值 | 可能是 harness 缺口 | 查该取值的产生路径是否被 driver 配置屏蔽 |
| driver 崩溃 | 算子缺陷 | delta-debug 最小化，出缺陷单 |

第三条来自本例最后一个 Key 的经历：`IsEmptyTensor=1` 一直产生不出来，查到是 driver 的 `compileInfo.npuArch` 漏填，导致空张量走了 pre-regbase 分支。这类问题在数据上表现为"某取值永不出现"，极易被误判成不可达。**判断依据是：产生该取值的代码路径存在，但被环境配置挡住了。**

### 4.5 迁移到新算子的清单

工程侧已经把算子相关的东西都收进 `operators/<op>/<arch>/`：

```
operator.yaml         算子路径、arch、driver 入口、done marker
log_protocol.yaml     日志 scrape 规则（19 维 / 中间状态 / 拒绝原因）
input_semantics.py    Case 定义、shape 展开、dtype 规则
bridge_spec.yaml      变量绑定
proof_rules.yaml      引理与源码引用
```

新算子接入需要提供：

1. **driver 能跑**——加载 host so、喂输入、打印标记
2. **日志协议**——至少要能拿到 19 维和拒绝原因；中间状态越多越好
3. **输入语义**——旋钮到 shape/dtype/attr 的展开，以及 `normalised()` 里的自洽规则
4. **静态派生结果**（可选但强烈建议）——没有它也能跑，只是阶段 3 的特征要靠猜

引擎侧（`scripts/replay/`）与算子无关，不需要改。

### 4.6 一开始就要做对的几件事

这些是本次踩过坑之后总结的，成本极低但省很多返工：

- **每一批都写宽表**。本次有 612 个 Key 找不到对应输入，只能事后从 driver 的 `_in.csv` 反解回来（`vg_unwire.py`）。虽然反解成功了 4223/4227，但这本不该发生。
- **批次 tag 不要复用**。复用会覆盖 `_in.csv` 和 `_log.txt`，是上面那 4 个反解不出来的 Key 的唯一原因。
- **CSV 所有字段统一清洗分隔符**，不要只清洗你觉得会出问题的那一个。
- **区分"没跑"和"被拒绝"**。这两件事在统计上、在训练上、在诊断上都完全不同。
- **恢复批次时关掉算子日志**。只需要 `###DONE` 的场合，开着 slog 会让 1.2 万个用例产生上百 MB 文本，并显著拖慢 Host。

---

## 5. 效果回顾

起点 `R = 0、E = 0、未判定 = 8705`：

| 阶段 | 动作 | R | E | 未判定 |
| --- | --- | ---: | ---: | ---: |
| — | 起点，不继承任何结论 | 0 | 0 | 8705 |
| 阶段 1 | 从原始日志与宽表重算 R | 2888 | 0 | 5817 |
| 阶段 6 | 重新推导继承的三组引理 | 2888 | 3632 | 2233 |
| 阶段 4 | 定向闭环 | 3502 | 3632 | 1629 |
| 阶段 6 | BN2MultiBlk / rope 引理 | 4114 | 3968 | 681 |
| 阶段 5 | 定点补齐 | 4211 | 3968 | 584 |
| 阶段 6 | 三元引理（BN2S2 / BN2 压 D） | 4215 | 4344 | 204 |
| 阶段 5+6 | 反例定位 → fp32 大 D 引理 | 4219 | 4536 | 7 |
| 阶段 5 | 逐个收尾（含修 driver 配置） | 4227 | 4536 | **0** |

作为对照：旧账本的口径是 R=2738、E=3632、未判定 2383。阶段 1 单靠修复 CSV 解析就比它多出 150 个 R，没花任何机器时间。

推 R 和证 E 是交替进行的，因为两者互相提供信息：新的 witness 会推翻错误的引理候选，新的引理会缩小需要搜索的目标集。表里 E 的三次跃升（0→3632、3968→4344、4344→4536）分别来自"重新推导继承规则"、"三元挖掘"和"运行时反例定位"——三条不同的引理推导路径，都在 6.2 里描述。
