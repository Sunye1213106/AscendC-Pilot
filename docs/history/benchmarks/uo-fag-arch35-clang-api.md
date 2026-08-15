# FAG arch35：打开 Clang API（`with_api=True`）分析报告

日期：2026-08-13。算子 `flash_attention_score_grad` / `arch35`。对照基线：同日默认 extract（`with_api=False`，全 dtype，`closure_mode=keypath`），见 [docs/benchmark.md](../../benchmark.md)。

本次**只打开 API clang**，没有切 `UO_INIT_PROFILE=full`（否则还会把 closure 打成 full、解开 fold 上限）。命令：

```text
$env:UO_TIMING = "1"
$env:UO_WITH_API = "1"
python engines/understand-operator/tools/experiments/fag_arch35_rebuild_check.py --with-api
```

收据：`ir/_host_bundle_meta.yaml` 中 `with_api: true`。产物路径仍是 `<op>/.ascendc-pilot/arch35/uo/flash_attention_score_grad.arch35.uo`。原始 timing / premises：`artifacts/fag-arch35-rebuild/with-api/`。

---

## 1. 结论（先看这个）

| 问题 | 答案 |
| --- | --- |
| API clang 有没有真正跑？ | **有。** 2 个 `op_api` TU，`api_contract.done` **8.07s**，抽出 **36** 条 legality premises，**36/36 grounded**。 |
| `/uo-init` 墙钟有没有明显变慢？ | **没有。** 合计 **215s** vs 基线 **227s**（机器热缓存）。extract 仍约 **142s**，API 段叠在 host/kernel 之后只加了 **~8s**。历史注释里「API ~70s」对本算子不成立。 |
| `.uo` / `uo-query` 变了吗？ | **几乎没变。** entities **10725**、relations **16582**、INPUT **41**、带 dtype **27**、gap **2772**、TilingKey **19/19**、verify **pass** — 与关 API 时同一张图。 |
| 36 条 premises 进 CodeMap 了吗？ | **没有。** `analyze`/`compile_codemap` 只吃 tiling `host_ir` + `kernel_ir`；`api_contract` 不在编译输入里。`derive_key_fields`（TG 推导）才会用 premises，而当前 uo-init 五步**不跑**它。合同也没有落成独立 YAML。 |
| 默认要不要开？ | **cannbot 源码定位 / CodeMap 查询：不要开。** 开了多付 ~8s，查询面不变。需要「aclnn 拒绝条件作为合法输入前提」时再开，并且要接到 TG 推导或把 premises 写进可查询层，否则白抽。 |

---

## 2. 提取耗时对照

| 阶段 | 关 API (s) | 开 API (s) |
| --- | ---: | ---: |
| prepare | 26.2 | 17.8 |
| extract | **142.5** | **141.5** |
|  extract_host | ~99（host\|\|kernel） | 118.4（host\|\|kernel 93.9 + **api\|\|bind 8.1** + 其它） |
|  extract_kernel | （含在 extract 内） | 23.0 |
| analyze | 45.0 | 44.0 |
| commit | 9.9 | 9.9 |
| verify | 0.6 | 0.7 |
| **合计** | **227.0** | **215.3** |

开 API 时 extract_host 分解：

| 子阶段 | s |
| --- | ---: |
| scope_clang_enrich | 14.1 |
| host\|\|kernel（4 host TU + 3 dtype kernel） | 93.9 |
| var_model+platform | 0.5 |
| **api\|\|bind** | **8.1** |
| controllability keypath 96 nodes | 1.1 |
| extract_host_bundle TOTAL | 117.8 |

API 自己走的 TU（与 tiling host 不是同一批）：

- `op_api/flash_attention_score_grad.cpp` — 3.7s，controls=37
- `op_api/aclnn_flash_attention_score_grad.cpp` — 7.2s，controls=850，writes=68，calls=2212

bind 与 API 线程并行（bind 0.05s），墙钟 ≈ 较慢的 API walk。

---

## 3. API clang 抽出了什么

`extract_api_contract` 读的是 **aclnn 拒绝条件的否定**：每条是「能进 Tiling 的输入必须满足的前提」，ground 到 REG_OP / opdef 参数名。

- 声明参数 47 个；premises **36**；**全部 grounded**（`unresolved` 空）。
- 参数命中次数（约束热度）：`input_layout` 27，`query` 18，`key` 15，`dq/dk/dv/head_num` 14，`value` 13，`dy` 8，以及 `drop_mask` / `actual_seq_*` / `query_rope` 等。

例（`aclnn_flash_attention_score_grad.cpp`）：

- `InputOutputShapeCheck:1458` — layout ∈ `{BNSD, BSND, BSH, SBH, TND}`，绑 `input_layout`
- `InputDtypeCheck:1395` — query/key/value/dy dtype 一致（含 FP8 分支），绑 `query,key,value,dy`

这正是 runtime-debug 561003 / 161002 在 **aclnn 层**要的合同，不是 `op_graph` 里 `TensorType({DT_*})` 那份集合，也不是 Host tiling 的 `OP_CHECK_IF`。

---

## 4. 为什么 CodeMap 不变

当前流水线：

```text
extract_host  →  bundle{host_ir, kernel_ir, api_contract, …}
analyze       →  compile_codemap(host_ir, kernel_ir)   // 不读 api_contract
commit        →  .uo
```

`codemap_engines._compiler_inputs` 明确只解析结构 IR；`host_derivation.yaml` / API premises 故意不进 CodeMap。`host_derivation._api_premises()` 是给 **derive_key_fields（TG）** 用的：没有这些前提，推导会以为 FP16 query 可以搭配 rope，从而报出 kernel 从未声明的 Key。

本次 uo-init **没有**跑 `derive_key_fields`。`api_contract` 也只活在 extract 进程内存里（落盘的是 `host_ir.pkl` / `kernel_ir.yaml` / meta），进程结束后 36 条 premises **不在 `.uo` 里，也不能 `uo-query`。**

因此：开 API 对 cannbot 的 `locate` / `field` 写读点 / `buffer` / `kernel_api` **零增量**。INPUT `facts.dtype` 仍来自 `source_reg_op`（proto `TensorType`），不是 aclnn `InputDtypeCheck`。

结构门与关 API 时相同：19/19 TilingKey，strict closure，`semantic_completeness=partial`，2772 条 entity_status — **API clang 不闭合这些缺口，也不制造新缺口。**

---

## 5. 和「默认不要 full / with_api」的关系

文档里说默认不开 API clang，这次实测支持该决策：

1. CodeMap 查询面不依赖它。
2. 本算子增量只有 ~8s，但若不接到 TG，这 8s 没有产品可见收益。
3. 历史 ~70s 更像旧口径（更多 TU / 冷缓存 / 把 API 和别的 clang 算在一起）。FAG 现在就是 2 个 API TU。

若以后要让 API 合同可查，需要单独做一件事（本次未做）：把 grounded premises 写成 CodeMap 上的 INPUT `check_sites` / 独立 PREDICATE，或持久化给 `derive_key_fields`。那才是「561003 用 clang 合同」而不是再用 proto 集合。

---

## 6. 建议

- 日常 `/uo-init`、cannbot 源码定位：**保持 `with_api=False`。**
- 要 Host 合法 Key 与 aclnn 拒绝条件对齐：开 `with_api`，并跑 **derive_key_fields / TG**，不要指望 `.uo` 自动变大。
- 不要用 `UO_INIT_PROFILE=full` 当「只开 API」——full 还会把 closure 打满，墙钟与本次 8s 不是同一量级。
