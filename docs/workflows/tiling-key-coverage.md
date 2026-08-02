# 拿到算子库文件，得到覆盖全部 TilingKey 的用例集

面向的问题：给定一个算子的 host tiling 实现，产出一张表——每一行是一个具体输入、
它算出的 TilingKey、以及这个 key 解码出的每一维取值；并且能回答「哪些声明出来的
key 根本产不出来，为什么」。

本文以 FlashAttentionScoreGrad（arch35，19 维 key）为样本，流程本身与算子无关。

## 0. 核心判断

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

FAG arch35 的实测结果：

| 判决 | 数量 | 占 8705 |
|---|---|---|
| `confirmed_runtime` | 1787 | 20.5% |
| `candidate_contradictory` | 6544 | 75.2% |
| `candidate_open` | 374 | 4.3% |
| `undeclared_runtime` | 96 | 额外产出 |

最常见的矛盾对是 `SplitAxis=0 与 IsTndSwizzle=1`（1824 个）——swizzle 只在 BN2S2
分核下成立，声明却把它和另外两种分核方式都配了一遍。

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
