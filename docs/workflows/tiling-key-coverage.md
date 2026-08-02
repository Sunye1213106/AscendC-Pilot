# 拿到算子库文件，得到覆盖全部 TilingKey 的用例集

面向的问题：给定一个算子的 host tiling 实现，产出一张表——每一行是一个具体输入、
它算出的 TilingKey、以及这个 key 解码出的每一维取值；并且能回答「哪些声明出来的
key 根本产不出来，为什么」。

本文以 FlashAttentionScoreGrad（arch35，19 维 key）为样本，流程本身与算子无关。

## 0. 核心判断

先说结论：**这套流程不保证覆盖全部 TilingKey，它保证的是把「不知道」压缩成一张有限
的、逐条可裁决的清单。** 覆盖率的说法只在明确了分母之后才有意义——见第 5.5 节和第 7 节。


早期思路是纯静态：把 host 代码符号化，解出每一维的闭式表达式。这条路会卡在
`invalidS1Array[j]`、`parseInfo[last]`、`CheckExceedL2Cache()` 这类需要循环摘要、
数组不变式、函数契约才能处理的地方，而且修一个变量表达式就膨胀一圈。

实际有效的分工是：

- **静态分析负责定形**：读 TPL 声明拿到维度表和位布局，读 host 源码拿到每一维的
  判定条件、以及各 layout 的 shape 语义。它回答「输入空间长什么样」「某个取值由
  哪几个条件决定」。
- **动态回放负责定性**：把具体输入喂给真实的 host tiling，读回真实的 key。它回答
  「这个 key 到底能不能产出」。

tiling 是纯计算，一个用例的成本是微秒级——本次实测每秒约 1500 个用例。所以判定
可达性根本不需要求解器，跑一遍就知道。求解器的价值只剩剪枝和证明不可达。

## 1. 一次性环境

只需要 host 侧，不需要 NPU 硬件，也不需要编译 kernel。

1. WSL2 + Ubuntu 22.04。`/mnt/d` 走 9p，比 WSL 内部 ext4 慢约 35 倍，仓库必须
   `rsync` 到 `/work` 再编译。
2. CANN 最小集：`cann-npu-runtime`、`cann-metadef`、`cann-opbase`、`cann-ge-compiler`、
   `cann-ge-executor`、`cann-asc-devkit`、`cann-asc-tools`、`cann-bisheng-compiler`、
   `cann-hcomm`。缺 `asc-devkit` 会少 `libtiling_api` 和 `platform_ascendc.h`；
   缺 `asc-tools` 会少 `tikicpulib`。
3. 从 Windows 同步过来的脚本要 `dos2unix`，CRLF 会让 bash 直接报错。

编译只编 host：

```bash
./build.sh --ophost_test --ops=<算子名> --soc=<型号> --noexec -j12
```

产物 `build/tests/ut/framework_normal/op_host/libophost_transformer_ut.so` 里带着
算子的 tiling 注册，回放驱动 dlopen 它就能拿到 tiling 函数。**改了 host tiling 只
需重编这一个 so，增量编译是秒级的**，这是整个流程能进 PR 流水线的前提。

## 2. 回放驱动

`ExecuteTiling`（`tests/ut/framework_normal/common/tiling_case_executor.h`）是通用的：
它按算子名从 `spaceRegistry` 取 tiling 函数，换算子只需换名字和 `compileInfo` 结构体。

驱动 `E:\wsl\replay\replay_main.cpp` 读一行 CSV 跑一个用例：

```
id ; 输入shape ; 输入dtype ; 输出shape ; 输出dtype ; attrs ; deterministic
```

三个容易踩的点：

- **常量张量**。像 `actual_seq_qlen` 这种 tiling 要读内容的输入，光给 shape 不够，
  不给数据会段错误。CSV 里用 `4@128/384/768/974` 表示「shape 为 [4]，数据是这四个
  值」，驱动侧要保证这块内存在 `ExecuteTiling` 返回前一直有效。
- **deterministic 不是 attr**，tiling 从 context 读，得单独一列传。
- **tiling data 大小**。UT 里给 4096 字节，够普通场景但不够 TND swizzle
  （它要存两份 129 个前缀和）。这一项卡住时的报错是 `InitTilingData failed`，看起来
  像输入非法，其实是回放环境给小了。本流程默认给 65536。

## 3. 维度级 oracle

打开 CANN 日志：

```bash
export ASCEND_SLOG_PRINT_TO_STDOUT=1
export ASCEND_GLOBAL_LOG_LEVEL=1
```

`GetTilingKey` 里的 `OP_LOGI` 会把 19 维的语义值原样打出来，`DoOpTiling` 那条会打出
`isExceedL2Cache` / `sparseType` / `enableSwizzle`。这些中间量决定了搜索是有向的还是
盲目的：某一维始终翻不过来时，可以逐个条件统计「有多少用例满足」，直接看出卡在哪一条。

日志和驱动输出混在同一个 stdout，所以驱动在每个用例前后打 `###CASE id` /
`###DONE id` 作为栅栏，解析时按栅栏归属，用例被拒、没产生日志也不会串行。

**上线前必须做一次交叉校验**：日志里的 18 维语义值，和从 key 解码出来的值逐个比对。
两条路径独立，对得上才能相信解码的位布局。本次 18/18 全部一致。

## 4. 输入模型：按 layout 分族

随机采 shape 会被 host 的一致性检查挡掉绝大部分。正确做法是把 layout 的 shape 语义
写进生成器：用例只描述 tiling 真正读的量（B、S1、S2、N2、G、D、D1），shape 由 layout
推出来。

| layout | query | key | value | dy |
|---|---|---|---|---|
| SBH | [S1,B,N1·D] | [S2,B,N2·D] | [S2,B,N2·D1] | [S1,B,N1·D1] |
| BSH | [B,S1,N1·D] | [B,S2,N2·D] | [B,S2,N2·D1] | [B,S1,N1·D1] |
| BNSD | [B,N1,S1,D] | [B,N2,S2,D] | [B,N2,S2,D1] | [B,N1,S1,D1] |
| BSND | [B,S1,N1,D] | [B,S2,N2,D] | [B,S2,N2,D1] | [B,S1,N1,D1] |
| TND | [T1,N1,D] | [T2,N2,D] | [T2,N2,D1] | [T1,N1,D1] |

**TND 是必须单独建模的一族**。B 和 S 完全不在任何 shape 里：B 是 `actual_seq_qlen`
的长度，每个 batch 的序列长是这个向量的**一阶差分**（向量本身存的是前缀和）。一整批
tiling 决策只看这个向量的性质——是否等长、是否有零段、是否有 EOD 尾零、S1 与 S2 是否
逐位相等——再怎么改 shape 都碰不到。

TND 还有一个陷阱：序列全等长且 sparse_mode ≤ PREFIX_COMPRESS 时，host 会把
layoutType 悄悄改写成 BSND（`SupportTrans2BS2N2GD`），于是 `IsTnd` 回来是 0。要保住
TND 这一维，序列必须不等长，或者 sparse_mode 足够高。

## 5. 覆盖引导搜索

新颖度信号就一条：**这个用例产出了没见过的 key，或者让某一维出现了没见过的取值**。
命中就留下，后续在它周围变异。这是 fuzzer 的思路，但不需要插桩——tiling 是纯函数，
输出本身就是反馈。

种子是结构化的，不是随机的：能直接从输入决定的维度（dtype、layout、mask 有无、rope、
deterministic、out_dtype）全部枚举；尺寸放在源码里比较的那些常数附近（128/2048/L2 容量）。
第一批种子就能覆盖大部分空间，变异只负责填缝。

变异算子对 TND 单列一套：缩放、抖动、置零、增删 batch、拉平成等长、追加 EOD 尾零——
都作用在差分序列上，改完再转回前缀和。

**shape 变体本身是维度**。`atten_mask` 的秩和前两维决定 host 怎么归类它
（`[S1,S2]` / `[B,N1,S1,S2]` / `[B,1,S1,S2]` / `[1,1,S1,S2]` 走不同分支），
`pse_shift` 同理。只用一种形状会漏掉一片 key——补上这几种变体后，实测 key 从 1808
涨到 1883。

实测节奏（FAG arch35，2000 用例/轮）：

| 轮次 | 累计 key |
|---|---|
| 种子批 | ~170 |
| 10 轮 | ~1000 |
| 50 轮 | ~1700 |
| 100 轮 | ~1870 |
| 150 轮 | 1883（最后 15 轮只 +1） |

30 万个用例总共 268 秒。判定可达性的成本低到可以当成常规检查跑。

## 5.5 「饱和」不等于「覆盖」

这是本流程里最容易骗自己的地方，必须单独讲。

第一次跑到 150 轮时，连续 15 轮没有新 key，1883 个 key 看起来已经穷尽。后来发现
`attention_in` 的形状写错了——它是前向输出，带的是 value 的 D，我却给了 query 的 D。
所有 `D1 != D` 的用例（1.7 万个）因此被 host 的一致性检查挡在门外，只有 17 个漏进来。
改一行之后，key 从 1883 涨到 **3409**。

也就是说，**搜索饱和只证明「当前生成器的输出空间被搜遍了」，完全不能证明「host 的输入
空间被搜遍了」**。生成器的盲区在饱和曲线上是完全看不见的。

要发现盲区，得用与搜索独立的指标。可用的有三层：

1. **1-wise**：每一维的每个声明取值都被产出过。这是底线，达不到说明有整片区域没碰。
2. **2-wise**：kernel 声明的每一对「维度值组合」都被产出过。这一层能发现 1-wise
   发现不了的盲区——上面那个 bug 的表征就是 `IsDNoEqual=1` 只在 rope 场景出现过，
   在 2-wise 报表上是刺眼的一行。
3. **未触达实例的归因**：每个没产出的声明实例，要么被某个「从未共现的值对」解释，
   要么归入「所有值对都见过、整体却没产出」。后者需要 3-wise 才能解释。

FAG arch35 修完 bug 后的实测：

| 指标 | 结果 |
|---|---|
| 1-wise | 19/19 维的全部声明取值都产出过 |
| 2-wise | 919/940 = 97.8%，缺 21 个值对 |
| 未触达的 5414 个实例 | 4360 个由缺失值对解释，1054 个需要更高阶解释 |

**21 个缺失值对是可以逐条裁决的规模**——每一条要么给出用例，要么给出代码理由。这比
「跑到不出新 key 为止」强得多，因为它把「不知道」变成了一张有限的清单。

`scripts/replay_coverage_audit.py` 就是算这三层的。每次改完生成器都要重跑。

## 5.6 为什么「穷举等价类」不能当作覆盖证明

一个很自然的想法：如果 key 只依赖输入的有限个特征，每个特征只有有限个相关取值，
那么穷举所有等价类就是构造性的完全覆盖证明。`replay_scan_axis.py` 是用来检验这个
前提的——逐值扫一根轴，看 key 在哪里跳变。

第一组扫描很鼓舞人（base = BSND/FP16/b=2/s2=512/n2=2/g=1/d=128）：

| 轴 | 扫描范围 | 跳变点 |
|---|---|---|
| s1 | 1..1024 | **0 个**，key 恒定 |
| b | 1..256 | 1 个（b=64） |
| d | 1..256 | 3 个（65 / 129 / 193，正好是 D 模板边界） |

key 确实是阶梯函数。但第二组扫描（`--couple`）推翻了「逐维分桶」的可行性——同一根
s1 轴，换个上下文，跳变点集合完全变了：

| 上下文 | s1 的跳变点 |
|---|---|
| base（b=2） | 无 |
| b=64 | 128, 160, 256, 320, 384, 768 |
| b=128 | 768 |
| s2=128 | 160 |
| n2=8 | 512 |

**跳变边界不是「每维各自的阈值」，而是若干个联合表达式的等值面**（L2 容量估算是
`b·n·s1·s2·d·dtype_bytes` 这一类乘积，核数分配则涉及整除关系）。所以等价类不是各维
桶的笛卡尔积，逐维分桶是 unsound 的：在 b=2 上扫遍 s1 得出「s1 不影响 key」，拿到
b=64 就是错的。

两个直接后果：

1. **有界穷举给不出理论保证**。除非先精确知道那些联合表达式，而它们恰恰是静态最难
   sound 建模的部分（容量估算、循环归约、调度分配）。
2. **搜索必须多基点**。固定一个基点扫某根轴，会系统性地漏掉另一基点下才存在的跳变。
   这解释了为什么两次不同种子的独立搜索各自「饱和」，却只共享 3302 个 key
   （A 独有 82，B 独有 87，并集 3471）。**单次搜索的饱和判据不可信，至少要多种子取并集。**

## 5.7 唯一站得住的 100% 定义：U − R = ∅

前面几节说清了什么**不能**证明完整性。能证明的只有一个形式——两侧独立夹逼：

- `R`：真实回放产出过的声明 key，可达下界。构造性的，每个都有可复现输入。
- `U`：sound 静态过近似认为**仍可能**产出的 key，可达上界。凡是模型搞不定的地方一律
  havoc（自由变量），只保留能证明的约束。

真实可达集 `H` 必然满足 `R ⊆ H ⊆ U`。于是 `R` 已证可达，`D − U` 已证不可达，
`U − R` 是真正未决。**完成条件是 `U − R = ∅`**，此时没有任何一项藏在"经验共现"或
"人为边界"背后。这个定义不含循环论证：下界靠运行，上界靠证明，互不引用。

`replay_closure_gate.py` 检查这套框架的前提条件 `R ⊆ U`——**任何被规则排除的 key
都不许有真实 witness**。它写出 `coverage_closure.yaml` 并以退出码表明成败。当前状态：

```
R = 4211，D = 8705，规则排除 3632，故 U = 5073，U − R = 958
gate: PASS（没有任何 witness 落在被排除的集合里）
```

注意 `replay_verdict.py` 里 confirmed 判断在前且 `continue`，所以规则与实测冲突会被
静默掩盖，**必须用独立的 gate 脚本查**，不能依赖判决输出。5.8 节记录了这个 gate 真的
拦下一条错误规则的过程。

### U − R 的结构

`replay_gap_distance.py` 量每个未决 key 到最近 witness 的维度距离：

| 距离 | 数量 |
|---|---|
| 差 1 维 | 1501 |
| 差 2 维 | 188 |
| 差 3 维 | 3 |

且全部落在 `S1TemplateNum=128 ∧ S2TemplateNum=128` 上，差 1 维的只涉及 10 个维度
（IsTnd 495、IsPse 426、DTemplateNum 221 居多）。看起来近在咫尺。

### 但 key 空间的邻近不等于输入空间的邻近

`replay_nudge.py` 直接验证了这一点：取每个未决 key 最近的 witness，只改与那一维相关的
输入。**150 个目标只命中 5 个（3%）。** 失败的不是"改了一维带动其他维"，而是变体被 host
直接拒绝——从 witness 继承的其他参数与翻转后的维度冲突。

结论：**闭合 U − R 不是搜索问题，是约束求解问题**。要命中一个未决 key，需要的是
「18 维保持不变、第 19 维变化」这个条件下的合法输入，随机变异和单维翻转都够不到。
必须允许影响锥内的多个输入协同变化，只冻结锥外的（见 5.8 的实例：要开 TND 的 PSE，
sparse_mode、pse 张量 dtype、pse_type 得跟着一起动）。

这也界定了静态分析真正的位置：**它的价值不在开头，在收尾。** 前 3477 个 key 随机搜索
几分钟就拿到了，静态一点用没有；剩下的这些，只有读代码能给出「要命中它，输入必须
满足什么」——5.8 节那一轮就靠四条读出来的 premise 把 gap 砍掉了 43%。

## 5.8 单 Key 闭合：一次完整的 CEGAR 记录

拿 `U − R` 里最简单的一个目标走完全程，用来检验这条路是否可行。这段记录值得原样保留，
因为其中每一步的失败都比成功更有信息量。

**目标**：`key 19703248907145904` = TND + FP16 + D=64 + `IsPse=1` + `IsAttenMask=0`，
与 witness `d192` 仅差 `IsPse`。`replay_pick_obligation.py` 按上下文复杂度自动选出。
顺带一提，777 个仅差 IsPse 的 key 里没有一个是"完全安静"的，全部带 `IsTnd=1`——
说明非 TND 下 IsPse 两种取值已经覆盖，gap 全在 TND。

1. **直接翻开关，被拒。** 六种 pse 形状全部报 `pseShiftOptional` 形状非法，而且报出来的
   形状是同一个——查出 `pse_shape` 的取值名和 `_shapes()` 里的映射表对不上，所有变体
   都落到了默认形状。生成器 bug 之三。
2. **读 `CheckPseShape`，补 premise。** TND 只接受 alibi 两种形状 `[1|b, n1, 1024, s2]`
   （中间是常数 1024，不是 s1），且要 `isTndPse`，即 `s1 <= s1Token ∧ s2Token == 0`。
   照此构造，仍被拒。
3. **追 `s2Token` 的来源。** `ProcessTokensInfo` 在 attenMask 为空张量时把
   `s1Token = s2Token = INT32_MAX`（1277-1281）。于是"TND + PSE ⇒ 必须有 mask"。
   实测双向确认：给了 mask 就通过，没 mask 就拒。
4. **把它当规则加进去，gate 立刻报警。** `PROOF_RULE_KILLS_RUNTIME_WITNESS`，
   **80 个真实 witness 反驳**。这条规则会误杀 512 个 key。
5. **看反例。** 全部是 `pse_shape=slope`——rank 2 的 alibi 斜率向量，走的是另一条检查
   路径，压根不经过 `CheckPseShape`。规则作废（`replay_verdict.py` 里留了退役记录）。
   而我在第 2 步"顺手清理"时把 slope 从形状列表删掉了，那是个错误的修复：它恰恰是
   TND 无 mask 下唯一能开 PSE 的方式。
6. **最后一条 premise。** slope 要求 pse 张量 dtype 是 `FLOAT`，与 query 的 dtype 无关；
   而生成器让所有输入跟随 query dtype。改成独立设置后，`pse_type ∈ {2,3}` 命中目标。

**结论**：这条路走得通，但它的产出不是"关闭了一个 key"，而是四条可复用的 premise 和
三个生成器 bug。真正的价值在推广——把 premise 喂回生成器重跑搜索：

| | 之前 | 之后 |
|---|---|---|
| R（真实 witness） | 3477 | **4211** |
| U − R（未决） | 1692 | **958** |

**一个 obligation 的 premise 推广，把 gap 砍掉 43%。** 这就是这条路线的杠杆所在：
逐个 key 走不完 1692 个，但每个 obligation 产出的 premise 会成批解锁。

也要记下代价：这一个 key 花了约十轮交互，其中三轮是在追我自己生成器的 bug。

### gate 的价值在这一轮被证实

第 4 步那条规则如果没有 gate 拦住，就会以 `static_proven` 的名义误杀 512 个 key，
其中 80 个有真实 witness。而 `replay_verdict.py` 因为先判 confirmed 再看规则，
**不会报任何错**——它只会安静地把那 80 个算成 confirmed，另外 432 个算成 unreachable。

所以固定执行顺序：先加载 witness 和规则 → 独立检查 `R ∩ (D−U)` → 非空立即失败 →
通过后才允许生成判决。`replay_closure_gate.py` 就是这个 gate，它的退出码是有意义的。

被推翻的规则要留退役记录（连同反驳它的证据），不要静默删除，否则下一个人会重新推一遍。

## 6. 卡住时的定向诊断

某一维始终翻不过来，先别加采样量。把它的判定条件从源码抄成一串合取项，用日志里的
中间量逐条统计通过率，再算累积通过数。掉到 0 的那一步就是瓶颈。

本次 `IsTndSwizzle` 的诊断过程可以当模板：

```
enableSwizzle=1                       34/897
splitAxis=BN2S2(5)                   163/897
非确定性                              897/897
sparseType!=3                        795/897
s1>=2048 或 (s2>128 且 s1>=1024)      766/897
b<129                                895/897
无零长序列                            739/897

累积：34 → 6 → 6 → 2 → 2 → 0
```

单看通过率，`b<129` 有 895/897，最不像瓶颈；但累积到它就归零了。原因是几个条件互相
拉扯：`enableSwizzle` 要数据量超 L2，而搜索堆数据量的办法是加 batch，一加就越过 129
这道门；改用 sparse 模式凑，超 L2 路径又把 sparseType 标成 UNSUPPORTED。

答对方向后（少 batch、长序列、多头堆量），发现真正的拦路虎是 tiling data 只给了 4096
字节——报错还伪装成 `InitTilingData failed`。放大到 65536 后 160/160 全中。

**结论：判一个 key 不可达之前，先确认卡点不在回放环境本身。**

## 7. 四档判决

`expand_legal_instances` 从 TPL 的 `ARGS_SEL` 分组展开出 kernel 真正会编译的模板实例
（FAG arch35 是 8705 个，而 19 维笛卡尔积是 1.65 亿）。拿它和回放结果对账：

| 判决 | 含义 |
|---|---|
| `confirmed_runtime` | 声明了，且有具体输入能产出，附 witness 用例 |
| `unreachable_static` | 声明了，但 host 代码路径证明产不出，附代码位置 |
| `candidate_static` | 声明了，没产出，也没证据说不可达——诚实的未知 |
| `undeclared_runtime` | host 产出了，但 kernel 没有对应实例——**这是真 bug**，运行期会找不到 kernel |

**注意区分 TPL 的两层声明**。`ASCENDC_TPL_ARGS_DECL` 给出每一维的取值域，
`ASCENDC_TPL_ARGS_SEL` 给出真正会实例化的组合。FAG arch35 的 DECL 域里有
`InputDType ∈ 0..6`，但 SEL 实例只用到 1/2/3。所以下面这些「DECL 里有、host 产不出」
的取值，在实例层面根本不存在，不会污染判决：

- `InputDType` 4/5/6（FP8_E5M2、FP8_E4M3FN、HIFLOAT8）：`ProcessQuantInfo` 在
  `common_regbase.cpp:1148-1155` 无条件拒绝这几种 dtype。`DetermineMode` 给它们分配了
  编码，但那行之后立刻返回失败，永远走不到 `GetTilingKey`。
- `S1TemplateNum=512`、`S2TemplateNum=512`：只有 `GetS1S2TemplateType` 的 HIFLOAT8
  分支会设（`common_regbase.cpp:825-829`），而 HIFLOAT8 进不来。
- `S2TemplateNum=256`：只有 FP8 分支会设（`common_regbase.cpp:819-824`）。
- `IsRegbase=0`：`GetTilingKey` 恒传 ENABLE（`normal_regbase.cpp:1447`）。

### candidate 要再分一层

声明实例是 SEL 分组的笛卡尔积，会配出 host 从不放在一起的值对。判断办法不需要额外
分析：统计所有实测 key 里出现过的「维度值对」，某个候选实例只要含一个从未共现的值对，
就归入 `candidate_contradictory`；每个值对都见过的才是真正的开放未知。

但归纳出来的「从未共现」只是线索，不是证据。真正的证据要落到代码，写成值对级的
不可达规则（`replay_verdict.py` 的 `UNREACHABLE_PAIRS`）。FAG arch35 目前有三条：

- `IsRope=1` 与 `DTemplateNum ∈ {64,128,256,768}`：`GetDTemplateType` 第一句就是
  `if (hasRope) return NUM192`，rope 场景 D 模板恒为 192（`common_regbase.cpp:849-852`）。
- `IsTndSwizzle=1` 与 `DeterType ≠ 0`：`templateSupportCond` 的确定性分支末尾硬编码了
  `&& false`，所以 swizzle 只在非确定性下成立；而非确定性时 `GetDeterSparseTilingKey`
  必返回 `NO_DETER`（`normal_regbase.cpp:453-461, 790-794`）。
- `IsAttenMask=0` 与 `DeterType ∈ {3,4}`：DETER_CAUSAL / DETER_BAND 都要求 `isSparse`，
  而 `SetSparseParams` 在 attenMask 为空时立刻返回 false（`common_regbase.cpp:1545-1549`）。

FAG arch35 的实测结果：

判决读取 `.probe_cache/replay/fag_key_cases*.csv` 的**并集**，不是最后一次运行——见 5.6 节，
单次搜索会饱和但不完全。三次运行（修 bug 前的一次 + 修好后两个种子）合起来 3477 个 key，
其中修 bug 前那次仍贡献了 6 个独有 key：生成器改了，覆盖到的区域也会挪，旧结果不能丢。

| 判决 | 数量 | 占 8705 |
|---|---|---|
| `confirmed_runtime` | 4115 | 47.3% |
| `unreachable_static`（有代码证据） | 3632 | 41.7% |
| `candidate_contradictory` | 336 | 3.9% |
| `candidate_open` | 622 | 7.1% |
| `undeclared_runtime` | 96 | 额外产出 |

前两档合起来 89% 有明确结论。第二条规则值得单独说：那个 `&& false` 是代码里显式
关掉的功能，kernel 却为这些组合声明了 1824 个模板实例——纯死代码。

### 本次查出的实际问题

96 个 `undeclared_runtime` 全部只差 `IsRope` 一维：其余 18 维与某个声明实例逐位相同，
但 kernel 只为 `IsRope=1` 声明了 `InputDType ∈ {2,3}`（BF16、FP16），**没有声明
`InputDType=1`（FP32）**。而 host 在 FP32 + rope 输入下确实会产出 `IsRope=1` 的 key。

最小复现：`layout=SBH, dtype=FLOAT, D=192(rope), B=1, S1=S2=256, N2=1, G=1`，
产出 `key=18999562539110416`。这个 key 在运行期没有对应的 kernel 实例。

发现它靠的不是读代码，而是把「host 实际产出集」和「kernel 声明集」做差集——
这类问题静态分析很难看出来，因为两边分别都是自洽的。

## 8. 换一个算子要改什么

| 要改 | 在哪 | 工作量 |
|---|---|---|
| 算子名、`compileInfo` 结构体 | `replay_main.cpp` | 几行 |
| TPL 头文件路径 | `replay/runner.py` | 一行 |
| 输入张量顺序、attr 列表 | `replay/inputs.py` 的 `IN_ORDER` / attrs | 照 OpDef 抄 |
| layout → shape 映射 | `replay/inputs.py` 的 `_shapes` | 算子相关，读 host 的 shape 解析 |
| 日志字段名 → 维度名 | `replay/runner.py` 的 `LOG_FIELDS` | 照 `OP_LOGI` 抄 |
| 种子与变异算子 | `replay/search.py` | 先跑通用的，按诊断结果补定向种子 |

不需要改的：回放驱动的 CSV 协议、日志栅栏与解析、覆盖统计、四档判决、解码交叉校验。

如果算子没有 `OP_LOGI` 打印维度值，第 3 步的 oracle 就没有了，诊断只能靠二分输入。
建议给新算子的 `GetTilingKey` 补一条日志，成本极低，收益很大。

## 9. PR 影响分析怎么用

改了 host tiling 之后：

1. 增量重编 `libophost_transformer_ut.so`（秒级）。
2. 用同一份用例集（`fag_key_cases_full.csv` 里的输入列）在新旧两个 so 上各跑一遍。
3. 逐用例比对 key：
   - key 变了 → 这次改动改变了模板选择，列出受影响的输入特征。
   - 原来 ok 现在被拒 → 收窄了输入域。
   - 出现新 key → 检查它在不在 kernel 的声明实例里，不在就是 `undeclared_runtime`。
4. 重跑一次覆盖搜索，比对四档判决的变化：`candidate_static` 变多说明有路径变得更难
   触达，`unreachable_static` 的证据是否还成立要重新核对。

这套比对不需要理解改动的业务含义，纯粹是行为差分。

## 10. 脚本索引

| 脚本 | 作用 |
|---|---|
| `scripts/replay/inputs.py` | 输入模型：layout 分族、TND 前缀和、prefix 张量 |
| `scripts/replay/runner.py` | 跑回放、解析日志、解码 key、写宽表 |
| `scripts/replay/search.py` | 种子、变异、覆盖统计 |
| `scripts/replay_smoke.py` | 冒烟 + 解码交叉校验（改任何东西后先跑这个） |
| `scripts/replay_cover.py` | 覆盖引导搜索主程序，产出宽表和 witness 表 |
| `scripts/replay_diagnose.py` | 某维翻不过来时，逐条件统计瓶颈 |
| `scripts/replay_probe_swizzle.py` | 定向探测的样例写法 |
| `scripts/replay_verify_decode.py` | 用日志重新编码，验证位布局 |
| `scripts/replay_verdict.py` | 四档判决，产出 `key_reachability.csv` |
| `scripts/replay_check_undeclared.py` | 解释「产出了但没声明」的 key 差在哪一维 |
| `E:\wsl\setup\run_replay.sh` | WSL 侧执行入口 |
| `E:\wsl\replay\replay_main.cpp` | 回放驱动 |

## 10.5 静态分析在这套流程里到底做了什么

诚实记录一下，避免后来者重复投入。

**用到的静态信息，全部来自「读声明」和「读代码」，总量只有几十条：**

| 用途 | 来源 | 不可替代吗 |
|---|---|---|
| 19 维的位布局、编解码 | 解析 TPL 头文件 | 是。没有它拿不到维度值 |
| 8705 个声明实例 | 解析 `ASCENDC_TPL_ARGS_SEL` | 是。它是判决的分母 |
| 五种 layout 的 shape 映射 | 读 host 的 shape 解析代码 | 是。没有它输入全被拒 |
| 每一维的判定条件（合取式） | 读 `GetTilingKey` 及其调用链 | 是。诊断卡点全靠它 |
| 值对级不可达证据 | 读代码找到 `&& false` 这类硬约束 | 是。这是唯一能把 candidate 变成 unreachable 的东西 |

**没用到的：`derive_key_fields.py` / `concrete_eval.py` / Z3 那套 AST 符号推导管线，
本次工作从头到尾一次都没有调用。**

原因是它想回答的问题和实际需要的问题错位了：

- 它擅长回答「给定输入，算出 key」。但回放能精确回答同一个问题，成本是微秒级，而且
  不会因为模型不完整而出错。这条赛道上静态没有胜算。
- 它唯一的独占能力是「证明不存在任何输入使某个 key 出现」——搜索找不到不等于不存在，
  这确实只有静态能做。但要让 UNSAT 结论可信，模型必须是 sound 的过近似；当前实现里
  有 8 个 free variable 被当作任意值（这部分是过近似，没问题），同时也有
  `visible_defs`、`runs_once` 这类为了收敛而加的启发式（这部分可能砍掉真实路径，
  是 unsound 的）。混在一起，它的「不可达」结论不能采信。

所以本次的三条不可达证据，全部是人读代码写出来的，不是求解器给的。

**建议**：不要再往「消掉剩余 free variable、把 19 维全部闭合成表达式」的方向投入。
真正有产出的静态工作是轻量的：给每一维写一份判定条件的合取式（LLM 读代码即可产出，
落成 YAML），供诊断和值对级不可达规则使用。如果将来要认真做 UNSAT 证明，前提是先把
模型的 soundness 说清楚——过近似归过近似，启发式归启发式，两者不能混。

## 11. 产物

都在 `.probe_cache/replay/` 下。

- **`fag_key_cases_full.csv`**（30.2 万行）：每行一个用例。输入描述（layout / dtype /
  B / S1 / S2 / N2 / G / D / D1 / atten_mask / pse 及其形状 / pse_type / rope /
  keep_prob / sparse_mode / pre_tokens / next_tokens / out_dtype / deterministic /
  seq_q / seq_kv / 序列性质标记）+ `ok` + `tiling_key` + 19 个 `dim_*` 列
  + 18 个 `log_*` 列（tiling 自己打印的语义值）+ `isExceedL2Cache` / `enableSwizzle` /
  `sparseType` + 被拒时的原因。
- **`fag_key_witness.csv`**（1883 行）：每个实测到的 key 一行，19 维取值 + witness
  用例 id + 该用例的关键输入。要为某个 key 造用例，查这张表。
- **`key_reachability.csv`**（8801 行）：每个 kernel 声明实例一行，四档判决 + 证据；
  外加 96 个 `undeclared_runtime`。

19 维中每一个 host 能产出的取值都被覆盖到了。未出现的取值只有
`InputDType` 4/5/6、`S1TemplateNum=512`、`S2TemplateNum` 256/512、`IsRegbase=0`，
全部有代码位置佐证，且都不在 kernel 的实例集里。
