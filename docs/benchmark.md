# UO 当前版本 benchmark

记录 **2026-08-13** 对 `flash_attention_score_grad` / **arch35** 的 `/uo-init`。当前口径是 **true cold start**（抹掉 `.ascendc-pilot/arch35`，含 TU cache），默认 profile `fast`。

机器：Windows，8 核。产品：

`<op>/.ascendc-pilot/arch35/uo/flash_attention_score_grad.arch35.uo`

默认 profile（未设 `UO_INIT_PROFILE` 即 `fast`）：`closure_mode=keypath`，**1 个 kernel dtype**，`fold_kernel=false`，`with_api=False`。完整抽取用 `UO_INIT_PROFILE=full`（全 dtype + fold + API clang），冷启动会明显超过 3 分钟预算。

同日家族泛化抽检见 [test/uo-init-generalization.md](test/uo-init-generalization.md)（**不当本页质量入口**）。pass7 全量：prepare 4/33、`.uo` 5 份（unknown 仍为 0）；墙钟与 verify 口径仍只以本页 FAG 冷启动为准。

更早的 action 级 harness 见 [history/benchmarks/uo-timing-baseline.md](history/benchmarks/uo-timing-baseline.md)。打开 Clang API 的对照见 [history/benchmarks/uo-fag-arch35-clang-api.md](history/benchmarks/uo-fag-arch35-clang-api.md)：**API 段 8s、36 条 grounded premises，`.uo` 图不变**；默认仍关 API。

---

## 冷启动（uo-init 五步）

Harness：`engines/understand-operator/tools/uo_init_perf_gate.py`（必须显式 `--arch` 或 `UO_ARCH`）。收据：`artifacts/fag-arch35-rebuild/cold-start-120s/{run.log,rebuild.json}`。

优化前同机冷启动约 **348s**（prepare 45 / extract 196 / analyze 86 / commit 20 / verify 1）。优化后：

| 阶段 | 优化前 (s) | 当前 (s) |
| --- | ---: | ---: |
| prepare | 45.2 | **15.8** |
| extract | 196.1 | **22.7** |
| analyze | 86.0 | **64.7** |
| commit | 19.5 | **14.7** |
| verify | 1.2 | **1.4** |
| **合计** | **348** | **119.4** |

当前冷启动落到 **3 分钟预算内**（`UO_COLD_BUDGET_S=180`）。主要手段：prepare 探针与 include parse 复用、extract 复用 prepare 的 clang scope、kernel 单次 AST walk、commit `executemany` 且默认跳过 VACUUM。

verify **pass**，TilingKey 声明 / packing / producer / root **19/19**，`has_tilingdata_kernel_path=true`。依赖骨架仍是 **12/19**（运行时叶，不挡 verify）。

产品：**13220** entities / **23611** relations。`OTHER` **413**，`OPERATION` **4289**（kernel_root_trace `reached_operations` **2624**，trace `gap_count` **202**）。`BINDS` **1664**，`ROOTED_AT` **5391**。Flag identity 已知 **15** 对，`UNPAIRED_FLAG_SYNC` **1**（fold 关闭后比同日较早的全量产品多 1 条未配对）。

`semantic_completeness=partial`，`unresolved.yaml` **2019** 条，主因是 `entity_status=partial`，**不是** verify 失败，也不是大量 `status=unknown`。

---

## 同日较早的缓存 extract（对照，不要和 119s 混比）

当时未抹 TU cache，`--analyze-only` 里 compile 含一次冷 extract；profile 注释为全 dtype。产品约 **10472** entities / **19825** relations。

| 阶段 | 墙钟 (s) |
| --- | ---: |
| analyze resolve_inputs（冷 extract） | **154.4** |
| analyze compile | **74.1**（其中 `kernel_root_trace` **23.1**） |
| commit | 19.6 |
| verify | 1.3 |

那次 unresolved **1615 → 800**（partial OPERATION **1326 → 593**），TilingKey 结构门同样 19/19。查询表和下节「未闭合项」仍以该产品为准；当前 119s 产品实体更多（kernel_root_trace / REGISTER 更全），gap 计数也更高，不宜直接当同一张图。

---

## 查询（已 commit 的 `.uo`）

下面是同日较早那份已 commit 产品上的 `open_query`（加载约 **0.36s**）。当前 119s 冷启动产品路径相同，但图更大；查询语义预期一致，耗时未在 119s 产品上重测。

| 查询 | s | 结果要点 |
| --- | ---: | ---: |
| `locate s1Inner` | 0.007 | 5 处：kernel 头声明 + host 写点 |
| `field s1Inner` | 0.005 | host **写点** 2；**读点** 0（见下文） |
| `tiling_key SplitAxis` | 0.003 | 值域 `{0,1,5}` |
| `tiling_key IsNzOut` | 0.003 | packing `tiling_normal_regbase.cpp:444` |
| `kernel_api DataCopy` | 0.202 | 调用点 **66** 全部 REACHED（定义行已从调用图去掉） |
| `kernel_api EnQue` | 0.077 | total **38**，全部 `mechanism=tque`，**0** 条 `SIGNALS`/`AWAITS`；例 `attenMaskOrYInQue` VECIN |
| `kernel_api InitBuffer` | 0.092 | total **44**，全部 `mechanism=tpipe`（`TPipe::InitBuffer`） |
| `kernel_api LoadAlign` | 0.549 | total **239**，全部 REACHED（`AscendC::Reg`） |
| `kernel_api SetGlobalBuffer` | 0.171 | total **84**，全部 REACHED |
| `kernel_api CrossCoreSetFlag` | 0.193 | total **101**；展示 50 条里带 `SIGNALS` 且 `flag_paired=true` |
| `impact` host `:1900` | 0.008 | 3 hit：host PREDICATE + kernel 侧 TILING_FIELD 声明 |
| `legal_key SplitAxis=1` | 0.628 | 可滤；例 `status=template_admissible` |
| `buffer` / QUEUE `attenMaskOrYInQue` | 0.004 | `tposition=VECIN`（`block_vec.h:147`） |
| `kernel_branch IsNzOut` | **9.76** | 回了 **1022** 条 BRANCH，偏慢、偏宽 |
| 扫全部 163 字段写/读 | 0.91 | **142** 条同时有 host 写点 + kernel 读点 |

工程声明根（extracted，**不是** AscendC REACHED）：`commondef::AlignTo16` 等在类型唯一时 `BINDS` 到声明 `file:line`。Selector::TYPE 展开后多个 Policy 都有 `Get` 的（如 `dYL1Buf`）保持不绑。

---

## 未闭合项：要不要补闭合

`semantic_completeness=partial`。119s 冷启动产品 `unresolved.yaml` **2019** 条；下表数量来自同日较早的 800 条产品，**类型**仍然适用。

| 未闭合 | 数量 / 口径（较早产品） | 要不要为了 UO 产品去闭合 |
| --- | --- | --- |
| partial OPERATION / METHOD / TYPE | 593 / 141 / 53 | **有唯一声明根的已经 BINDS**。剩下：`Ceil`（工程无定义，CANN 多重载）、`Min`（`const_def.h` 不在 selected kernel files）、`Get`/`Init` 主要是 `Selector::TYPE`（展开后多个 Policy 都有该方法，不能猜）。`Process` / 宏 `X` / `vstas` 同样不猜。 |
| HOSTUNRESOLVED 运行时叶 | 13 个名字（`context_`、`fBaseParams`、`INT32_MAX`、`batchIdx`…） | **不必。** 对应 TilingKey 依赖骨架 **12/19**。结构 packing/producer 已 19/19；叶节点闭合是 TG 可达性，不是 UO 静态图义务。 |
| TILING_FIELD 无 `rhs` | 16 | **不必。** `reserved*` 填充位 + 嵌套 TilingData 成员（`preTilingData` 等），不是公式字段。 |
| EnQue/DeQue 无 `SIGNALS` | EnQue 38 / DeQue 36 均无 Flag 边 | **不是 Flag 缺口。** CANN TQue 封装交接，`mechanism=tque`，独立于 SetFlag↔WaitFlag。 |
| Flag identity 成对 | 较早产品 15 对、`UNPAIRED_FLAG_SYNC=0`；119s 产品 15 对、**未配对 1** | 已知 identity 成对出现。表达式 identity 仍不进配对。happens-before 仍不在 UO。 |
| `kernel_branch` 过宽 | IsNzOut → 1022 条 / 9.8s | **要修查询，不是补 extract。** 收窄 pattern，不要当闭合缺口。 |

**已经闭合、作为本版门槛的**：19 维 TilingKey 结构覆盖、strict 读写闭包、verify pass、跨层路径标志均为 true；TQue 不进 Flag 配对；TPipe `InitBuffer`/`FetchEventID`/`GetTPipePtr`；Reg 公开自由函数（LoadAlign 等）；`GlobalTensor::SetGlobalBuffer`；工程方法在类型唯一时 `BINDS` 到声明根（不标 CANN REACHED）。

---

## 跨 Host–Kernel 查阅：难查询实测

| 问题 | UO 是否串得起来 | 会不会漏关键信息 |
| --- | --- | --- |
| SplitAxis 在 Host 怎么 pack、Kernel 哪用 | **能。** packing `tiling_normal_regbase.cpp:1444`；kernel `apt.cpp:35` TEMPLATE_ARG；`block_cube.h` 上 `SPLIT_AXIS == …` 分支 | packing 路径有的带算子前缀、有的是 `op_host/...`，侧别分类要归一路径 |
| IsNzOut Host 条件 → Kernel 维 | **能。** producer `tiling_normal_regbase.cpp:444`；声明在 template tiling key 头 | — |
| TilingData 字段 Host 写 → Kernel 读 | **大多数能。** 163 字段里 **142** 条同时有 host 写点与 kernel 读点；没有「只有 kernel 读、没有 host 写」的字段 | `s1Inner` 等 arch35 **kernel cpp 不用该字段**（只有 tiling 头里的声明/get/set），`field` 读点为 0 是对的，不是漏边。`impact` 命中的 kernel 侧是**结构体声明行**，不要当成消费点 |
| INPUT `query` dtype | **能。** `proto.h:87` 五个 DT_* | 这是 graph 声明，不是 Host clang |
| DataCopy / 同步 API 定位 | **能定位 `file:line`。** DataCopy **66**、EnQue 38、InitBuffer 44、LoadAlign 239、SetGlobalBuffer 84、CrossCoreSetFlag 101 | EnQue/DeQue 是 **TQue**；InitBuffer 是 **TPipe**。SetFlag / WaitFlag / CrossCore* 做 identity 级成对出现 |
| 合法 Key 组合 | **能滤。** `legal_key` ~0.63s | 状态是 `template_admissible`，不是 Host 运行时一定产生 |

结论：跨 Host–Kernel 的 **TilingKey packing ↔ kernel 模板/分支**、**大多数 TilingData 写/读** 已经可查。TQue 的 EnQue/DeQue 不进入 Flag 成对检查；TPipe 的 InitBuffer 单独 `mechanism=tpipe`。工程侧 **声明根 + 调用点** 在类型唯一时已 `BINDS`。仍不在本层闭合的是：happens-before、把声明行当成读点、运行时叶、多个 Policy 都能 `Get` 的 selector 类型、无唯一工程定义的 `Ceil`/`Min`。

---

## 复测

```text
$env:UO_TIMING = "1"
# true cold start（会抹掉该算子 arch35 缓存）
python engines/understand-operator/tools/uo_init_perf_gate.py --arch arch35

# 10 算子量级抽检请设 UO_GEN_ONLY；无过滤会跑全家约 33 算子 + FAG arch22 审计
# $env:UO_GEN_ONLY = "attention/fused_causal_conv1d:arch35,..."
python engines/understand-operator/tools/uo_init_generalization.py

acp uo-query --project <op> --mode locate --pattern s1Inner
acp uo-query --project <op> --mode field --pattern s1Inner
acp uo-query --project <op> --mode tiling_key --pattern SplitAxis
acp uo-query --project <op> --mode kernel_api --pattern EnQue
```
