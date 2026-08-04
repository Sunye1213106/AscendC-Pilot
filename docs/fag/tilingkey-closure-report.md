# FlashAttentionScoreGrad arch35 TilingKey 闭合报告

## 0. 本报告的口径

内核声明了 8705 个 TilingKey。本次工作**不继承任何既有结论**：

- **R（可达集）** 从原始运行记录重算——driver 自己打印的 `###DONE ok=1 key=N` 行，以及宽表 CSV，取并集
- **E（不可达集）** 的每一条引理都重新推导，落到具体源码行，并在全量 witness 上过反例检验

仓库里此前留有一份账本（R=2738、E=3632、未判定 2383），本报告不采信它的任何一个数字，只把它作为对照。事实上第一步重算就发现它少算了 150 个早已命中的 Key。

起点因此是：

```
D = 8705   R = 0   E = 0   未判定 = 8705
```

已有的 93,479 行历史运行记录被当作**输入数据**复用（省去重新采样的机器时间），但其中每一个 Key 的可达性结论都重新从原始日志确认过。

---

## 1. 结论

| 判定 | 数量 | 依据 |
| --- | ---: | --- |
| 可达（有真实 Host witness） | 4169 | 每个 Key 都有一条真实跑通的输入，见 `fag_arch35_reachable_cases.csv` |
| 不可达（有源码引理证明） | 4536 | 13 组引理，每条引用具体源码行 |
| **合计** | **8705** | 恰好等于声明数 |
| 未判定 | 0 | — |

两个集合互不相交（`R ∩ E = ∅`），在 4227 个真实 Key 上逐个校验过。

### 校验方式

`vg_verify_csv.py` 对交付物做四项检查，全部通过：

- 表中每一行的 19 维反向编码回 TilingKey，与该行 Key 一致（0 处不符）
- 表中没有任何一个 Key 被某条引理判为不可达（0 处冲突）
- 所有"声明且可达"的 Key 都在表中（0 处缺失）
- 4169 + 4536 = 8705

`vg_exclude.py` 另有一道硬门禁：任何被规则判为不可达、却存在真实 witness 的 Key，都会让它拒绝写出结果并报错退出。这是防"假 100%"的最后一道防线。

---

## 2. 不可达引理

13 组引理，展开成 40 条具体规则（7 条取值级 + 33 条组合级）。表中两个数字含义不同：

- **单独排除**：该条规则自己能排除多少个声明 Key，衡量这条规则的覆盖面
- **唯一依据**：该条规则是**唯一**依据的 Key 数，即撤掉它会重新变回未判定的数量

4536 个不可达 Key 中，3104 个只有一条规则支撑，1432 个被多条规则同时排除（互为冗余交叉验证）。

规则写在 `operators/flash_attention_score_grad/arch35/proof_rules.yaml`，由 `scripts/replay/rule_engine.py` 加载。

---

### 引理组一：FP8 / HIFLOAT8 在 tiling 之前就被拒

```
InputDType=4 (FLOAT8_E5M2)    单独排除=0
InputDType=5 (FLOAT8_E4M3FN)  单独排除=0
InputDType=6 (HIFLOAT8)       单独排除=0
S1TemplateNum=512             单独排除=0
S2TemplateNum=256             单独排除=0
S2TemplateNum=512             单独排除=0
```

**证明**：`ProcessQuantInfo` 在 tiling 主流程开始前就把这些 dtype 全部拒掉：

```cpp
// common_regbase.cpp:1143-1153
ge::graphStatus ProcessQuantInfo(gert::TilingContext *context_, FuzzyBaseInfoParamsRegbase& fBaseParams)
{
    DetermineMode(fBaseParams);
    if (fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E4M3FN ||
        fBaseParams.queryType == ge::DT_UINT8 || fBaseParams.queryType == ge::DT_INT8 ||
        fBaseParams.queryType == ge::DT_QINT8 || fBaseParams.queryType == ge::DT_HIFLOAT8) {
        ...
        return ge::GRAPH_FAILED;      // <-- 直接失败，不会走到 GetTilingKey
    }
```

`InputDType` 的 4/5/6 分别对应这三种 dtype（`DetermineMode`，`common_regbase.cpp:1650-1661`），既然输入被拒，Key 就产生不出来。

连带推出两条：`GetS1S2TemplateType` 里 `S1TemplateNum=512` 只由 HIFLOAT8 分支产生（`common_regbase.cpp:823-827`），`S2TemplateNum=256` 只由 FP8 分支产生（817-822）、`S2TemplateNum=512` 只由 HIFLOAT8 分支产生——三者的前置条件都已被拒。

这组的排除数是 0，因为内核本来就没声明这些取值。保留它有两个作用：一是说明"为什么声明集里没有 FP8 变体"，二是将来声明集扩大时能自动兜住。

> 关于 `IsRegbase=0`：`GetTilingKey` 把 `isRegbasePlatformValue` 写死为 `ENABLE`（`normal_regbase.cpp:1441`），所以 regbase 路径下它恒为 1。历史数据里确实出现过一次 `IsRegbase=0`——那是修复 driver 的 `npuArch` 配置之前，空张量走 pre-regbase 分支返回的 `FAG_EMPTY_TILING_KEY = 0`（见 3.4）。它不在声明集内，不影响闭合。

---

### 引理组二：rope 强制 D 模板为 192

```
IsRope=1 + DTemplateNum=64    单独排除=128  唯一依据=32
IsRope=1 + DTemplateNum=128   单独排除=128  唯一依据=32
IsRope=1 + DTemplateNum=256   单独排除=128  唯一依据=16
IsRope=1 + DTemplateNum=768   单独排除=128  唯一依据=16
```

**证明**：`GetDTemplateType` 的第一条语句就拦截了 rope，直接返回 192 且不再往下走：

```cpp
// common_regbase.cpp:845-850
uint32_t GetDTemplateType(FuzzyBaseInfoParamsRegbase& fBaseParams)
{
    if (fBaseParams.hasRope) {
        fBaseParams.dTemplateType = ConstAxisTemplateNum::NUM192;
        return static_cast<uint32_t>(ConstAxisTemplateNum::NUM192);
    }
    ...
```

`hasRope` 只在 `normal_regbase.cpp:95` 赋值一次（`hasQueryRope && hasKeyRope`），之后没有任何写入点，所以 `GetTilingKey` 读到的 `hasRope` 与这里判断的是同一个值。因此 rope 打开时 `DTemplateNum` 只能是 192。

**数据印证**：265 个 rope witness，`DTemplateNum` 全部为 192，无一例外。

---

### 引理组三：rope 强制 dNoEqual 置位

```
IsRope=1 + IsDNoEqual=0       单独排除=320  唯一依据=16
```

**证明**：Key 里的 `IsDNoEqual` 就是 `GetTilingKey` 现算的 `dNoEqual`：

```cpp
// normal_regbase.cpp:1438
auto dNoEqual = (fBaseParams.d1 != fBaseParams.d) || fBaseParams.hasRope;
```

是个或运算，`hasRope` 为真时整个表达式恒为真，与 d/d1 是否相等无关。

> 这条引理值得单独说明：它一度被怀疑是**输入生成器的缺陷**而非算子性质——因为 `input_semantics.py` 在 rope 时强制 `d1=None`，使得生成器根本表达不出 "rope 且 D≠Dv"。查到这一行源码才确认是算子本身的语义。把生成器缺陷写成不可达证书是这类工作最危险的错误，本报告的每一条引理都必须落到源码行才被采信。

---

### 引理组四：BN2MultiBlk 的合取式

```
IsBn2MultiBlk=1 + IsRope=1        单独排除=320  唯一依据=0
IsBn2MultiBlk=1 + IsDNoEqual=1    单独排除=320  唯一依据=80
```

**证明**：`isBn2MultiBlk` 是一个长合取式，末尾两项是 `d == d1` 和 `!hasRope`：

```cpp
// common_regbase.cpp:1592-1602
fBaseParams.isBn2MultiBlk = bnSparseLimit &&
                            (s1 > BN2_MAX_S || s2 > BN2_MAX_S) &&
                            (s1 <= BN2_MULTIBLK_SEQ && s2 <= BN2_MULTIBLK_SEQ) &&
                            (n1 == n2) &&
                            d <= BN2_MAX_D &&
                            (queryType != ge::DT_FLOAT) &&
                            (d == d1) &&                     // <-- 这里
                            !(FP8/HIFLOAT8) &&
                            !fBaseParams.hasRope;            // <-- 和这里
```

结合引理组三的 `dNoEqual = (d1 != d) || hasRope`：两个合取项分别否定了这个或表达式的两个分支，所以 `isBn2MultiBlk` 成立时 `dNoEqual` 必为假。`d` 与 `d1` 只在读 shape 阶段（`normal_regbase.cpp:107-330`）赋值，早于 `SetSplitAxis`，两处看到的是同一组值。

---

### 引理组五：BN2MultiBlk 与 TND 互斥

```
IsTnd=1 + IsBn2MultiBlk=1     单独排除=320  唯一依据=32
```

**证明**：这条的证明链最长，因为 `layoutType` 在后面还会被改写。

第一步，`isBn2MultiBlk` 依赖 `bnSparseLimit`，而后者要求非 TND：

```cpp
// common_regbase.cpp:1588-1591
bool bnSparseLimit = bnLimit &&
                    (fBaseParams.layoutType != INPUT_FORMAT_TND) &&   // <--
                    (sparseMode != PREFIX) && (sparseMode != PREFIX_COMPRESS);
```

第二步，全仓只有一处能把 `layoutType` 改回 TND，而它被 `!isBn2` 守卫：

```cpp
// common_regbase.cpp:1637-1638
if (!fBaseParams.isBn2 && bn2S2RouteLimit) {
    fBaseParams.layoutType = fBaseParams.isAllSame ? INPUT_FORMAT_TND : fBaseParams.layoutType;
```

第三步，关键的一行——`isBn2MultiBlk` 为真时 `isBn2` 被强制为真：

```cpp
// common_regbase.cpp:1603
fBaseParams.isBn2 = fBaseParams.isBn2MultiBlk ? true : fBaseParams.isBn2;
```

于是 1637 行的 `!isBn2` 为假，1638 行不执行，`layoutType` 保持 `SetSplitAxis` 时的非 TND 值。`DoSparse` 里另一处 `layoutType = INPUT_FORMAT_BS2N2GD`（`normal_regbase.cpp:670`）只会让它更远离 TND。最后 `isTnd` 在 `GetTilingKey` 直接读这个字段（`normal_regbase.cpp:1442`）。

---

### 引理组六：BN2MultiBlk 关闭确定性计算

```
IsBn2MultiBlk=1 + DeterType=1..4    单独排除=0（声明集内无此组合）
```

**证明**：

```cpp
// common_regbase.cpp:1612-1613
if (fBaseParams.isBn2MultiBlk) {
    fBaseParams.isDeterministic = false;
```

而 `GetDeterSparseTilingKey` 在 `!isDeterministic` 时第一句就返回 `NO_DETER`（见引理组十二引用的源码），`DeterType` 就是 `deterSparseType`。

排除数为 0——内核本来就没声明这些组合。保留它是因为它 sound 且零成本。

---

### 引理组七：BN2S2 路径下 dropout 压低 D

```
SplitAxis=5 + IsDrop=1 + DTemplateNum=192   单独排除=80  唯一依据=56
SplitAxis=5 + IsDrop=1 + DTemplateNum=256   单独排除=80  唯一依据=56
SplitAxis=5 + IsDrop=1 + DTemplateNum=768   单独排除=80  唯一依据=56
```

**证明**：`SplitAxisEnum::BN2S2 = 5`，且全仓只有一处把 `splitAxis` 设为 BN2S2（`common_regbase.cpp:1639`），受 `bn2S2RouteLimit` 守卫。该条件里有一个析取项：

```cpp
// common_regbase.cpp:1631-1632
(fBaseParams.keepProb >= 1 ||
 (fBaseParams.d <= static_cast<uint32_t>(ConstAxisTemplateNum::NUM128) && fBaseParams.keepProb < 1)) &&
```

`IsDrop` 就是 `keepProb < 1`（`normal_regbase.cpp:1440`）。开了 dropout 时第一个分支为假，只能走第二个，于是 `d <= 128`，`DTemplateNum ∈ {64, 128}`。

还要说明 BN2S2 能活到 `GetTilingKey`：`DoSparse` 里若 `DoBn2s2Sparse() && blockOuter >= aicNum` 成立就提前 return（`normal_regbase.cpp:665-666`），`splitAxis` 保持 5；否则会在第 691 行被改写成 BN2 或 BN2GS1S2。所以 Key 里 `SplitAxis=5` 反推出 `bn2S2RouteLimit` 一定成立过。

> 这条是**三元**约束，成对挖掘看不到它——单看 `SplitAxis=5 + DTemplateNum=768` 或 `IsDrop=1 + DTemplateNum=768` 都在真实数据里出现过。它是先从源码读出来、再由三元挖掘器独立复现的，两条路径互相印证。

---

### 引理组八：BN2S2 路径下非 TND 压低 D

```
SplitAxis=5 + IsTnd=0 + DTemplateNum=192    单独排除=32  唯一依据=16
SplitAxis=5 + IsTnd=0 + DTemplateNum=256    单独排除=32  唯一依据=16
SplitAxis=5 + IsTnd=0 + DTemplateNum=768    单独排除=32  唯一依据=16
```

**证明**：`bn2S2RouteLimit` 的 layout 析取项有三个分支：

```cpp
// common_regbase.cpp:1629-1630
(fBaseParams.layoutType == INPUT_FORMAT_TND || (fBaseParams.isAllSame && !fBaseParams.isDeterministic) ||
 bn2S2NotTndLimit) &&
```

紧接着第 1638 行会执行 `layoutType = isAllSame ? TND : layoutType`。逐分支排除：

- 走第一个分支 → `layoutType == TND` → `IsTnd=1`，与前提矛盾
- 走第二个分支 → `isAllSame` 为真 → 1638 行把 layout 置为 TND → `IsTnd=1`，同样矛盾
- 所以只能走第三个分支 `bn2S2NotTndLimit`，而它要求 `d <= BN2S2_WRITE_UB_D`：

```cpp
// common_regbase.cpp:1621-1626
bool bn2S2NotTndLimit = (s1 < s2) && (s2 <= BN2S2_MAX_S) &&
    (s2 - s1 >= BN2_MAX_S) &&
    (fBaseParams.d <= BN2S2_WRITE_UB_D) &&      // <-- 常量 = 128
    (!fBaseParams.isSparse) && (!fBaseParams.isDeterministic);
```

`BN2S2_WRITE_UB_D = 128`（`common_regbase.h:116`），所以 `DTemplateNum ∈ {64, 128}`。

---

### 引理组九：BN2 路径下 TND 压低 D

```
SplitAxis=1 + IsTnd=1 + DTemplateNum=192    单独排除=128  唯一依据=48
SplitAxis=1 + IsTnd=1 + DTemplateNum=256    单独排除=128  唯一依据=32
SplitAxis=1 + IsTnd=1 + DTemplateNum=768    单独排除=128  唯一依据=32
```

**证明**：`SplitAxisEnum::BN2 = 1`，只在 `isBn2` 为真时被设置（`common_regbase.cpp:1640-1641`、`normal_regbase.cpp:691`）。而 TND 场景下 `isBn2MultiBlk` 必为假（引理组五已证 `bnSparseLimit` 排除 TND），因此下面这段一定会执行：

```cpp
// common_regbase.cpp:1604-1611
if (fBaseParams.isBn2 && !fBaseParams.isBn2MultiBlk) {
    fBaseParams.isDeterministic = false;
    if ((fBaseParams.layoutType == INPUT_FORMAT_TND && fBaseParams.d > ALIGN128) ||
            fBaseParams.dropMaskOuter) {
        fBaseParams.isBn2 = false;          // <-- TND 且 d>128 时 BN2 被取消
        fBaseParams.isDeterministic = (context_->GetDeterministic() == 1);
    }
}
```

`ALIGN128 = 128`。`isBn2` 全仓只会被置假、不会被重新置真，且 `layoutType` 回到 TND 的唯一入口被 `!isBn2` 守卫（同引理组五）。所以 `SplitAxis=1` 且 `IsTnd=1` 蕴含 `d <= 128`。

---

### 引理组十：fp32 大 D 固定基本块

```
InputDType=1 + DTemplateNum=768 + S1TemplateNum=128   单独排除=352  唯一依据=192
```

**证明**：`GetS1S2TemplateType` 的第一个分支直接返回固定的 (64, 128)：

```cpp
// common_regbase.cpp:810-816
std::pair<uint32_t, uint32_t> GetS1S2TemplateType(FuzzyBaseInfoParamsRegbase& fBaseParams)
{
    if (fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d > static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)) {
        fBaseParams.s1TemplateType = ConstAxisTemplateNum::NUM64;
        fBaseParams.s2TemplateType = ConstAxisTemplateNum::NUM128;
        return std::make_pair(NUM64, NUM128);
    }
```

三个条件对齐：`InputDType=1` 即 `FLOAT32`，对应 `queryType == DT_FLOAT`（`DetermineMode`，`common_regbase.cpp:1650-1651`）；`DTemplateNum=768` 当且仅当 `!hasRope && d > 256`（`GetDTemplateType`）；两者同时成立就落进这个分支，`S1TemplateNum` 只能是 64。

> 这一条是靠**运行时反例定位**找到的，不是靠读代码猜到的。构造式生成器为这批 Key 造了 3192 个被 Host 接受的用例，却一个目标都没命中；逐维对比"要的"与"得到的"，发现 720 个接受用例无一例外地把 `S1TemplateNum` 从 128 压成了 64。带着这个现象去查 `GetS1S2TemplateType`，第一个分支就是答案。它一条就关掉了当时剩余 200 个未判定 Key 中的 192 个。

---

### 引理组十一：nEqual 依赖 deter 类型

```
IsNEqual=1 + DeterType=0    单独排除=0
IsNEqual=1 + DeterType=1    单独排除=0
```

**证明**：Key 里的 `IsNEqual` 槽位放的是 `isDeterNEqual`，它不是形状属性：

```cpp
// normal_regbase.cpp:1444-1446
bool isDeterNEqual = fBaseParams.deterSparseType != static_cast<uint32_t>(DeterSparseType::DETER_OLD) &&
                     fBaseParams.deterSparseType != static_cast<uint32_t>(DeterSparseType::NO_DETER) &&
                     fBaseParams.g == 1;
```

`NO_DETER = 0`、`DETER_OLD = 1`（`common_regbase.h:309-315`），而 `DeterType` 槽位放的就是 `deterSparseType` 本身。声明集内无此组合，排除数为 0，同引理组六保留。

---

### 引理组十二：无 attenMask 时 deter 类型只能是 0/1/2

```
IsAttenMask=0 + DeterType=4      单独排除=992  唯一依据=632
IsAttenMask=0 + DeterType=3      单独排除=912  唯一依据=576
```

这是排除数最大的一组。

**证明**：先看 `GetDeterSparseTilingKey` 的完整分支结构：

```cpp
// normal_regbase.cpp:790-814
uint32_t GetDeterSparseTilingKey()
{
    if (!fBaseParams.isDeterministic) {
        return NO_DETER;                                          // 0
    }
    if (!fBaseParams.isSparse || sparseMode == ALL_MASK ||
        (sparseMode == NO_MASK && s1Token >= s1 && s2Token >= s2)) {
        return DETER_DENSE;                                       // 2
    } else if (sparseMode == LEFT_UP_CAUSAL || ... ) {
        return DETER_CAUSAL;                                      // 3
    } else if (sparseMode == BAND || RIGHT_DOWN_CAUSAL || NO_MASK) {
        return DETER_BAND;                                        // 4
    }
    return DETER_OLD;                                             // 1
}
```

关键在第二个 `if` 的第一个析取项 `!isSparse`——一旦 `isSparse` 为假就在这里返回 2，根本走不到 3 和 4。

再看 `isSparse` 与 attenMask 的关系：

```cpp
// common_regbase.cpp:1534-1545
bool SetSparseParams(gert::TilingContext *context_, FuzzyBaseInfoParamsRegbase& fBaseParams)
{
    if (sparseMode == PREFIX || sparseMode == PREFIX_COMPRESS) {
        return SetPrefixSparseParams(context_, fBaseParams);      // <-- 例外分支
    }
    if (sparseMode == ALL_MASK || fBaseParams.attenMaskOptional == EMPTY_TENSOR) {
        return false;                                             // <-- 无 mask 即非 sparse
    }
    ...
```

**这里有一个必须处理的例外**：`sparseMode` 为 PREFIX(5) / PREFIX_COMPRESS(6) 时会先走 `SetPrefixSparseParams`，可能在没有 mask 的情况下返回 true。那时 `isSparse` 为真，回到 `GetDeterSparseTilingKey`：

- 第二个 `if`：`!isSparse` 假、`ALL_MASK` 假、`NO_MASK` 假 → 不成立
- 第三个：`LEFT_UP_CAUSAL(1)`？否。`NO_MASK(0)`？否。`RIGHT_DOWN_CAUSAL(2)`？否 → 不成立
- 第四个：`BAND(4)`？否。`RIGHT_DOWN_CAUSAL(2)`？否。`NO_MASK(0)`？否 → 不成立
- → 落到最后一行，返回 `DETER_OLD = 1`

所以例外分支导向的是 1，不是 3 或 4，引理依然成立。

**这个例外给了一个可证伪的预测**：无 mask 时 `DeterType=1` 应当是**可达**的。数据完全对上：

| IsAttenMask=0 时的 DeterType | witness 数 |
| --- | ---: |
| 0 | 601 |
| 1 | **261** |
| 2 | 643 |
| 3 | **0** |
| 4 | **0** |

261 个 `DeterType=1` 的 witness 正是走 PREFIX 分支来的。如果当初偷懒把引理写成"无 mask 时 DeterType 只能是 0 或 2"，就会错误地排除掉 261 个真实可达 Key——反例检验会当场拦下，但更好的做法是一开始就把例外分支读进去。

---

### 引理组十三：TND swizzle 与确定性计算互斥

```
IsTndSwizzle=1 + DeterType=2     单独排除=608  唯一依据=576
IsTndSwizzle=1 + DeterType=3     单独排除=608  唯一依据=288
IsTndSwizzle=1 + DeterType=4     单独排除=608  唯一依据=288
```

**证明**：`isTndSwizzle` 要求 `templateSupportCond`，而后者的确定性分支被一个字面量 `false` 掐死：

```cpp
// normal_regbase.cpp:453-463
bool templateSupportCond =
    (fBaseParams.isDeterministic && fBaseParams.splitAxis == SplitAxisEnum::BN2GS1S2 &&
     fBaseParams.deterSparseType == DETER_DENSE && false) ||          // <-- 恒为假
    (!fBaseParams.isDeterministic && fBaseParams.splitAxis == SplitAxisEnum::BN2S2 && ...);
tndBaseInfo.isTndSwizzle = fBaseParams.enableSwizzle && layoutType == INPUT_FORMAT_TND &&
                           templateSupportCond && b < TND_SWIZZLE_PREFIX_NUM &&
                           !tndBaseInfo.isSeqExistZero && tailZeroCount == 0;
```

第一个析取项恒假，所以 `templateSupportCond` 成立必须走第二项，要求 `!isDeterministic`。而 `GetDeterSparseTilingKey` 第一句就是 `if (!isDeterministic) return NO_DETER`。

**执行顺序需要单独核对**，因为 `deterSparseType` 在 `DoSparse`（第 663 行）算出，而 `isTndSwizzle` 在其后（第 461 行）算出，中间第 683 行还有一处 `isDeterministic = (GetDeterministic() == 1)` 可能把它改回真。分情况：

- 会话 deterministic=0：`isDeterministic` 全程为假 → `deterSparseType = 0`，与结论一致
- 会话 deterministic=1，且 663 行时为假（被 `SetSplitAxis` 关掉）：`deterSparseType = 0`；随后 683 行可能恢复为真 → 461 行 `!isDeterministic` 为假 → swizzle 关闭，前提不成立
- 会话 deterministic=1，且 663 行时为真：`deterSparseType != 0`；461 行 `isDeterministic` 仍为真 → swizzle 关闭，前提不成立

三种情况下 `isTndSwizzle=1` 都蕴含 `deterSparseType = 0`。

**数据印证**：112 个 swizzle witness，`DeterType` 全部为 0。

---

## 3. 过程中发现的缺陷

### 3.1 宽表 CSV 引号 bug（已修）

`ReplayRunner.wide_row` 只对 `reject` 字段做了逗号清洗，没管 `tag`，而 `BSND:d=64,d1=16` 这类 tag 很常见，导致约 **16% 的行列数错位**。严格 CSV 读取器会丢弃这些行，账本因此少算了 **150 个早已命中的 Key**。

修复：所有字段统一走 `_plain()` 清洗（`scripts/replay/runner.py`）。

### 3.2 算子 SIGFPE 崩溃（未修，需算子侧处理）

TND 布局下，当 **q 侧和 kv 侧各有一个零长度分段、且落在不同 batch 条目**时，Host tiling 触发整数除零，driver 以 `rc=136`（SIGFPE）退出。

最小复现：

```
layout=TND  dtype=FLOAT16  b=2  n2=1  g=1  d=64  d1=64
atten_mask=none  pse=false  sparse_mode=0
seq_q  = [0, 512]      即 lens_q  = [0, 512]
seq_kv = [256, 256]    即 lens_kv = [256, 0]
```

2×4 网格对照实验确认了触发条件的边界——以下情形都正常：

| lens_q | lens_kv | 结果 |
| --- | --- | --- |
| [512, 512] | [256, 256] | 正常 |
| [0, 512] | [256, 256] | 正常（仅 q 侧有零） |
| [512, 512] | [256, 0] | 正常（仅 kv 侧有零） |
| [0, 512] | [0, 256] | 正常（两侧零对齐在同一条目） |
| [0, 0] | [256, 256] | 正常（q 侧全零） |
| [512, 512] | [0, 0] | 正常（kv 侧全零） |
| **[0, 512]** | **[256, 0]** | **崩溃 rc=136** |
| **[512, 0]** | **[0, 256]** | **崩溃 rc=136** |

### 3.3 批次静默截断（已修）

WSL 里的 `run_replay.sh` 无论 driver 是否崩溃都 `echo BATCH_DONE rc=$rc; exit 0`，而 `ReplayRunner.run` 只检查 `BATCH_DONE` 是否出现。driver 崩溃后，剩余用例被 `parse_log` 填成空 `Result`，与"Host 看过并拒绝"完全无法区分。

后果有两层：一是浪费——实测一批 1500 个用例只跑了 249 个，其余 1251 个被记成"拒绝"；二是污染——这些假阴性会被反馈进模型训练集。

修复（`scripts/replay/runner.py`）：按 `rc` 与实际完成数判断截断，识别肇事用例并标记为 `HOST_CRASHED`，自动重发剩余用例，实在跑不到的标 `NOT_RUN`。新增 `Result.verdict` 属性区分"Host 给出了裁决"与"没跑成"。对照测试（20 个用例中植入 3 个已知崩溃用例）：3 个杀手精确识别，17 个幸存用例全部得到裁决，零丢失。

### 3.4 driver 未设置 npuArch（已修）

`FlashAttentionScoreGradCompileInfo` 的最后一个字段是 `npuArch`，driver 的聚合初始化只写到 `socVersion`，`npuArch` 被值初始化为 0，于是：

```cpp
// flash_attention_score_grad_tiling.cpp:417-428
if (npuArch == NpuArch::DAV_3510) {
    if (IsEmptyOutput(context)) return RunEmptyTilingRegbase(context);   // 走不到
} else {
    if (IsEmptyOutput(context)) return RunEmptyTiling(context);          // 实际走这里，返回 key 0
}
```

空张量场景一直走的是 pre-regbase 分支、返回 `FAG_EMPTY_TILING_KEY = 0`，所以 `IsEmptyTensor=1` 的 Key 从来没被产生过。

**算子自己的 arch35 UT 也有同样的问题**——`tests/ut/op_host/arch35/test_flash_attention_score_grad_tiling.cpp` 里全部 10 处 `compileInfo` 初始化都只写到 `socVersion`。也就是说这条 regbase 空张量路径此前从未被任何测试覆盖过。

修复：driver 补上 `NpuArch::DAV_3510`（`scripts/replay/wsl/replay_main.cpp`）。回归验证 60 个已知 witness 全部返回原 Key，同时 `IsEmptyTensor=1` 的 Key 首次产生。建议算子侧 UT 一并补上该字段。

### 3.5 内核未声明但 Host 会产生的 Key（需算子侧确认）

真实 Host 产生了 **57 个内核未声明**的 TilingKey，全部具有相同特征：

```
InputDType=1 (fp32) + IsRope=1 + IsDNoEqual=1 + DTemplateNum=192
```

声明表按 (InputDType, IsRope) 分组的统计说明了问题：

| InputDType | IsRope | 声明数 |
| --- | ---: | ---: |
| 1 (fp32) | 0 | 2112 |
| 1 (fp32) | **1** | **0** |
| 2 (bf16) | 1 | 496 |
| 3 (fp16) | 1 | 496 |

bf16 和 fp16 都声明了 rope 变体，唯独 fp32 没有。而 Host tiling 会为 fp32+rope 的输入算出对应 Key，运行时将找不到 kernel 模板。这是与覆盖率相反方向的问题：不是测试缺口，是**分发缺口**。

明细见 `fag_arch35_undeclared_keys.csv`。

---

## 4. 交付物

| 文件 | 内容 |
| --- | --- |
| `docs/fag/data/fag_arch35_reachable_cases.csv` | 4226 个可达 Key，每个附完整输入与 19 维取值 |
| `docs/fag/data/fag_arch35_closure.csv` | 8705 个声明 Key 逐个判定与依据 |
| `docs/fag/data/fag_arch35_undeclared_keys.csv` | 57 个未声明但可产生的 Key |
| `.probe_cache/vg_excluded_why.csv` | 4536 个不可达 Key 与命中的规则 |
| `operators/.../arch35/proof_rules.yaml` | 引理与源码引用 |

`fag_arch35_reachable_cases.csv` 的每一行都经过复跑确认：把该行输入送给真实 Host，返回的就是该行 Key。列结构为

```
tiling_key, tiling_key_hex, declared,
layout, dtype, b, s1, s2, n2, g, d, d1, atten_mask, pse, pse_shape,
pse_type, rope, keep_prob, sparse_mode, pre_tokens, next_tokens,
out_dtype, deterministic, seq_q, seq_kv,
dim_IsEmptyTensor ... dim_IsRegbase
```

---

## 5. 复现方式

```bash
python .probe_cache/vg_ledger.py            # 从原始记录重建 R 账本
python .probe_cache/vg_check_inherited.py   # 引理的数据侧交叉验证
python .probe_cache/vg_exclude.py           # 应用引理生成 E（含反例门禁）
python .probe_cache/vg_closure.py           # 逐 Key 闭合报告
python .probe_cache/vg_witness_csv.py       # 重建并复跑确认可达用例表
python .probe_cache/vg_verify_csv.py        # 交付物自检
```
