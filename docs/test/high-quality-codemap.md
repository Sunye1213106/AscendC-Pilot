# 什么是高质量信息库

> 抽检口径，不是架构权威。实现与 [uo.md](../modules/uo.md)、[uo-product-map.md](../../skills/operator-analysis/references/uo-product-map.md) 冲突时，以代码和那两份为准。
>
> 收据：`artifacts/uo-init-generalization/host-recv-narrow/`（2026-08-14，FAG arch35 + IFA arch22 冷启动）。

信息库就是已经 commit 的 `.ascendc-pilot/<arch>/uo/<op>.<arch>.uo`（CodeMap）。高质量的意思是：**cannbot 问「事实在哪、怎么连」时，用 `uo-query` 能给出带 `file:line` 的结构答案，而不必再 grep 整份算子。**

UO 不替代 cannbot。条例是否违规、golden 是否过线、卡死是不是 happens-before、561002 根因是什么，仍由 cannbot 判断。信息库只负责如实交出可证明关系，以及明确标出还没闭合的叶子。

```text
问题 → uo-query 定位点 + 最小源码窗 → cannbot 判断
```

---

## 一句话标准

一份高质量信息库同时满足三件事：

1. **合法**：`integrity: pass`（verify 过线）。packing / producer / root、Host→Kernel、TilingData→Kernel 缺一则图不能当底座。有 OUTPUT 时 INPUT→OUTPUT 必须通；proto 无 `.OUTPUT` 的 fusion send 是诚实，不挡。
2. **可定位**：`quality.grade: ready` 且 `locate_ready: true`。Key / Field / Kernel / Input / `OP_CHECK` 都能按名字落到 `file:line`；Kernel 目录里真有 EnQue / DataCopy / SetFlag 这类调用点，而不是只抽出 `__global__` 壳。
3. **诚实**：未闭合项分类清楚。`host_runtime_leaf` 可以留着；`locate_blocking` 必须是 0。禁止用 LLM 把缺口补进 `.uo`。

`artifact existence ≠ semantic completeness`：有 `.uo` 不等于高质量。verify 失败、OTHER 一堆、Kernel 走查只有入口三个函数，都不是高质量。

---

## cannbot 要什么，图上必须有什么

`quality.py` 的打分面就是按 cannbot 的定位面写的，不是按实体总数写的。

| cannbot skill | 反复要的源码点 | 信息库必须交出 | 查询 |
| --- | --- | --- | --- |
| code-review / issue-handler Step 3 | 符号、入口、字段的 `file:line` | INPUT / KERNEL / TILING_KEY / TILING_FIELD 全有 span | `locate` |
| code-review「TilingData 值域」 | `set_*` / 赋值写点，kernel `tilingData->x` 读点 | 字段有 owner；writer site 带 span | `field` / `tiling_data` |
| code-review 校验策略 | `OP_CHECK_IF` 行 | BRANCH `host_check` 全有 span | `locate` → `check_sites` |
| crash-debug | Buffer / Queue、`tposition`；EnQue/DeQue、SetFlag/WaitFlag、Alloc/Free、InitBuffer | BUFFER/QUEUE 有放置信息；OPERATION 有 callee + `file:line` | `buffer` / `kernel_api` |
| precision-debug | DataCopy / DataCopyPad / Cast；多 dtype | 搬运/Cast 调用点；INPUT 有 `facts.dtype` | `kernel_api` / `search INPUT` |
| runtime-debug 561002 / 561003 | TilingKey 声明与 packing；接口 dtype | 声明 Key 全部绑上 Host packing；dtype 可查 | `tiling_key` |
| whitebox-design | 分支路径、合法 Key 组合 | KERNEL 分支 span；packing 维能指到源 | `kernel_branch` / `legal_key` |
| issue-handler / PR 检视 | 改动碰到哪些路径 | 有向有用边，能分桶 | `impact` |

Flag 成对、TQue/TPipe 机制标注是加分项。EnQue 在 `InitAllZeroOutput` 这类方法里也必须进图——只扫 `__global__` 入口会得到「ready 但 Kernel 空」的假高质量。

---

## 过线门槛（ready）与加分项

### 必须（缺了就不是 ready）

来自 `uo_init/diagnostics/quality.py`：

- `integrity` pass（verify 无 blocking）
- Kernel 至少一个带 span
- 有 TilingKey 时，packing site 不能是 0
- TilingField 无 `field_owner_unknown` / `field_owner_ambiguous`
- 有 KERNEL 则 Host→Kernel 通；有 TILING_DATA 则 TilingData→Kernel 通；有 OUTPUT 则 INPUT→OUTPUT 通（无 OUTPUT 不算缺路径）
- `locate_blocking == 0`
- 八个定位面全部 `ok`：`symbol_span`、`tiling_key`、`field_rw`、`host_check`、`buffer`、`kernel_api`、`dtype`、`paths`

`paths`：Host→Kernel、TilingData→Kernel；有 OUTPUT 时再加 INPUT→OUTPUT。cannbot 还依赖 **INPUT→TilingKey→Kernel**（audit 的 `MISSING_INPUT_TILINGKEY_KERNEL_PATH`）；这条挂了 integrity 也会失败。

### 应当（ready 允许缺，但「能当 cannbot 底座」要看这些）

| 指标 | 含义 | 近期提取里什么算够 |
| --- | --- | --- |
| packing / producer / root | 声明 Key 全部绑上当前源的 Host packing，且能追到 INPUT/编译期根 | FAG **19/19**，IFA **12/12** |
| `tiling_key_dependency_coverage` | packing 上游没有 `dependency_unresolved` 叶子 | FAG 历史最高 **12/19**；其余 7 个 Key 挂的是 `actualSeqQlen` / `parseInfo` 这类真 runtime 值，策略上不闭合 |
| Kernel 颗粒 | OPERATION 是走查到的 API，不是 OTHER 垃圾 | FAG EnQue 61 / DataCopy 158 / SetFlag 249 / LoadAlign 282；IFA EnQue 60 / DataCopy 204 / SetFlag 145（AllVec 路径 LoadAlign=0 是路径选择，不是缺目录） |
| OTHER | 未归类实体 | 高质量目标 **0** |
| locate 命中率 | Key / Field / Kernel / Input 探针 | **1.0** |
| Host check / field owner | `OP_CHECK` 与字段归属 | FAG 117/117、163/163 owner |

`12/19` 不是 packing。packing 19/19 且 integrity pass 时，dependency 骨架不完整只打 `PARTIAL_TILINGKEY_DEPENDENCY_SKELETON`，**不挡 ready**。评价建库看 `grade` 和 `locate_blocking`，不要用 `unresolved.yaml` 总条数。

### 禁止（会把库做假或做窄）

- 用 LLM 补边进 canonical `.uo`
- 按算子名字写特化（FAG/IFA 分支、名字表）
- `UO_TEST_ALLOW_UNVERIFIED_SCOPE` 换 verify pass
- 把方法调用的接收者（`context_->GetInputShape`）当成 TilingKey 的 unresolved 值叶子——会把 12/19 打成 2/19，定位面却不变
- 反过来丢掉 `ctx.query.desc->GetDataType()` 这种嵌套路径——INPUT→Key 会断，cannbot 的 dtype/Key 查询会空
- 只抽 Host、Kernel TU 不解开：include 闭包里的 `ORIG_DTYPE_*` / `TILING_KEY_VAR` 打不开，walk 停在入口，EnQue 为 0。同一 `#if` 里两个 `ORIG_DTYPE_*` 等于**不同** `DT_*` 时，不能把全部 ORIG 打成同一个 preferred dtype；需要一次 per-macro 赋值的额外 walk。当前架构 `op_kernel/<arch>/` 里未进确认闭包的头，TQue/DataCopy/SetFlag 仍应 lexical 补进图。
- 把 kernel 入口 include 闭包里的第一套 `ASCENDC_TPL_ARGS_DECL` 和 layout glob 扫到的另一套 sibling `*_tiling_key.h` 合成一张 Key 表。声明维数对不上 `GET_TPL_TILING_KEY` 实参数，packing 会变成 0/N；`TILING_KEY_IS` 仍是合法 packed catalog，不是维名

---

## 未闭合项怎么读

| bucket | 典型 | 挡 ready？ |
| --- | --- | --- |
| `locate_blocking` | 字段无 owner、缺 Kernel span | **挡** |
| `host_runtime_leaf` | `context_`、`parseInfo`、`ifaContext_.queryRope.tensor` | 不挡。Host 依赖骨架停在运行时对象，策略是保留 |
| `catalog_unproven` | 未证伪的 OPERATION（如 `min`、`ComputePDS_VF_unalign`） | 不挡。目录没认出来，调用点往往仍在 |

FAG 当前 13 条 host leaf + 3 条 catalog，与 8e 那版「未闭合 14」同类：不是 19 个 Key 没绑上。IFA 当前 6 条全是 `ifaContext_.*` 字段读，packing 仍 12/12。

---

## 两份近期对照（何谓够用）

同一天冷启动，假编译环境通用，无算子特化。

| | FAG arch35 | IFA arch22 |
| --- | --- | --- |
| verify / grade | pass / **ready** | pass / **ready** |
| packing / producer / root | 19/19 | 12/12 |
| dependency 骨架 | **12/19** | 6/12 |
| OTHER | 0 | 0 |
| locate | 1.0 | 1.0 |
| INPUT→Key→Kernel | 通 | 通（`query.desc->GetDataType` 接到 INPUT） |
| OPERATION | 4728 | 3096 |
| EnQue / SetFlag / DataCopy | 61 / 249 / 158 | 60 / 145 / 204 |
| host_check / field owner | 117/117，163/163 | 528/528，469/469 |
| locate_blocking | 0 | 0 |

这两份达到「cannbot 可当底座」：检视能 locate 字段和 `OP_CHECK`，卡死能查 EnQue/SetFlag，精度能查 DataCopy/Cast，561002 能查 packing 点。dependency 不是 19/19 或 12/12 并不妨碍这件事。

---

## 怎么验收一份新算子的库

读 `<op>/.ascendc-pilot/<arch>/uo/checks/quality.yaml`，按这个顺序：

1. `integrity: pass`、`grade: ready`、`locate_ready: true`、`not_ready_reasons: []`
2. `surfaces.tiling_key.packing` 全覆盖；`surfaces.paths` 的 Host→Kernel / TilingData→Kernel 为 true；有 OUTPUT 时 INPUT→OUTPUT 为 true
3. `unresolved.locate_blocking: 0`；`OTHER` 用 generalization inspect 的 `other_count`
4. `surfaces.kernel_api`：源码里有的 EnQue/DataCopy/SetFlag 在图里 `n>0` 且 `with_span=n`（源码没有的 API 为 0 是正常）
5. `aux.tiling_key_dependency_coverage`：只作精度对照，不替代 packing

查询抽检（名字换成该算子真实符号）：

```text
acp uo-query --project <op> --mode locate --pattern <TILING_FIELD>
acp uo-query --project <op> --mode tiling_key --pattern <TILING_KEY>
acp uo-query --project <op> --mode kernel_api --pattern EnQue
acp uo-query --project <op> --mode kernel_api --pattern DataCopy
acp uo-query --project <op> --mode buffer --pattern <QUEUE>
```

泛化抽检过线仍是：**抽到的每个算子 verify pass，且能 locate Key / Field / Kernel / Input / `OP_CHECK`。** 当前并集 **49** 个不重复算子，见 [uo-init-generalization.md](uo-init-generalization.md)。
