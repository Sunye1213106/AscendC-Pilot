# uo-init 家族泛化：现在过了什么、还差什么

> 这不是 FAG 119s 质量入口（那个仍看 [benchmark.md](../benchmark.md)）。本页回答：**换成别的算子，产品路径能不能交出一份能用的 `.uo`。**

产品路径不许设 `UO_TEST_ALLOW_UNVERIFIED_SCOPE`。未 wipe FAG arch22。

收据：`artifacts/uo-init-generalization/pass8-accept/`（2026-08-13，33 个冷启动 + 1 个 arch22 审计，771s）

---

## 先看结果（人话）

`/uo-init` 要连续过五步才算**闭合**：prepare → extract → analyze → commit → **verify pass**。

| 状态 | 几个算子 | 含义 |
| --- | ---: | --- |
| 真正闭合（verify pass，有完整 `.uo`） | **2** | `flash_attention_score_grad`；以及后来冷启动过线的 `matmul_reduce_scatter_v2` arch22（unknown=0，locate 1.0） |
| 有 `.uo` 但 verify 失败（图不完整） | **10** | 进了 analyze/commit，缺 packing / TilingData / Input 路径 |
| 卡在 extract | **1** | `rotary_position_embedding_grad`：`extract_host` 崩在 `'NoneType' object has no attribute 'group'` |
| 卡在 prepare，根本没有 `.uo` | **21** | pass8 当时 kernel 探针仍把算子 TU 判脏；其中 `matmul_reduce_scatter_v2` 已在后续通用假编译环境修复后离开此桶 |
| 已有产物只审计、未重抽 | 1 | FAG arch22 |

所有已经写出来的 `.uo` 里 **unknown 都是 0**。过线标准仍是每个抽到的算子 verify pass，且 locate 到 Key/Field/Kernel/Input/`OP_CHECK`。pass8 当时只有 FAG 达到；假编译环境去 FAG 特化之后，`mc2/matmul_reduce_scatter_v2` arch22 也闭合（收据 `artifacts/uo-init-generalization/mrs-v2-accept/`，约 39s）。

对照 pass7：prepare 过 4→12；有 `.uo` 5→11；verify pass 仍是 1。计划里点名的挡门（`*TilingData`、`RegTensor` ambiguous、`lib/matrix/matmul/tiling.h`、`acl/acl_base_mdl.h`、PFA 未限定 `string`）**探针 samples 里已经不再出现**。剩下的一律记成仍未修掉的 UO 缺口，不改算子仓，不用 unverified scope。

---

## 计划里那几项现在怎样

| 原挡门 | pass8 |
| --- | --- |
| `unknown type name '*TilingData'` | 未再出现。prepare 生成 packed stub + `GET_TILING_DATA*` 并 force-include |
| `RegTensor` ambiguous | 未再出现。prelude 不再 stub 与 CANN 同名的 `RegTensor`/`VecReg` |
| `'lib/matrix/matmul/tiling.h' file not found` | 未再出现。include-heal 把该前缀改写到现存 `lib/matmul/` |
| `'acl/acl_base_mdl.h' file not found` | 未再出现。`spec/compat/acl/acl_base_mdl.h` 洞补 |
| PFA `use of undeclared identifier 'string'` | 未再出现。host-only force-include `using std::string` |
| 无 TPL 头时 MISSING_KERNEL | 有 `.uo` 的算子 kernel API span 多数已齐；挡门改成 packing / TilingData 边 |

FAG arch35 冷启动仍约 119s、verify pass、unknown=0、locate 1.0，质量入口未动。Kernel `-D` 按 `arch_dir` 表注入，不再使用 FAG-calibrated 冻结宏。

---

## 仍未修掉的 UO 缺口

### 1. Kernel 仍脏：CANN 残差被算进算子错误（约 12 个）

`Mode` / `atomic_type_t` 以前当 CANN 头残差，现在出现在算子 kernel 探针 samples 里，且 `operator_error_count≥1`，直接 `SCOPE_VALIDATE_BLOCKED`。

代表：FAS、FIAS、SFA、lightning_indexer、mla_prolog、compressor、causal_conv1d、mhc_sinkhorn、moe_init_routing_v2、matmul_all_reduce（kernel 侧）。`matmul_reduce_scatter_v2` 已不再属于这一类（探针 `operator_error_count==0`，verify pass）。

假编译环境还没把这些 CANN 类型接到和真编译器一样的可见性；禁止当算子仓问题。

### 2. Cube / SoftMax 高阶类型仍不进 kernel TU（约 8 个）

| 探针 sample | 代表 |
| --- | --- |
| `unknown type name 'TCubeTiling'` | IFA、PFA、grouped_matmul*、rotary_position_embedding |
| `unknown type name 'SoftMaxTiling'` | IFA、PFA、moe_gating_top_k、moe_gating_top_k_softmax |
| `unknown type name 'MatmulConfig'` / `GetNormalConfig` | `grouped_matmul_finalize_routing`（matmul 头映射之后仍缺类型） |
| `unknown type name 'GMMArray'` | `grouped_matmul` |

`lib/matmul/tiling.h` 已能找到文件，但 `TCubeTiling` / `MatmulConfig` 仍未进 TU。不要把 `ascendc/include/basic_api` 加进 kernel `-I`。

### 3. Host 缺 `nlohmann/json.hpp`（mc2 的 matmul 族）

`matmul_all_reduce` / `all_gather_matmul_v2` host fatal：`'nlohmann/json.hpp' file not found`，heal 正确保持 unresolved。完整 toolkit / 算子 3rd 里若有实体文件，应扩包或映射；禁止假造该头。

### 4. 已出图但 Host packing / TilingData 边不齐（10 个）

`fast` 下 skip fold 仍对。KERNEL 已能从 source 走查出来，verify 卡在 Host→Key→Kernel 边：

| 算子 | blocking | packing | locate |
| --- | --- | --- | --- |
| `fused_causal_conv1d` | TILING_DATA、HOST_TILINGKEY_PRODUCERS、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH | 0/4 | ready，缺 packing site |
| `ffn_worker_batching` | INPUT、OUTPUT、TILING_DATA、packing、producers、UNROOTED、HOST_KERNEL_PATH | 0/3 | 无 input span |
| `moe_distribute_dispatch` | TILING_DATA、packing、producers、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH | 0/3 | ready |
| `moe_distribute_combine` | TILING_DATA、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH | 0/3 | ready |
| `mhc_pre` | INPUT、OUTPUT、HOST_KERNEL_PATH、TILINGDATA_KERNEL_PATH | 1/2 | 无 input span |
| `mhc_post` | TILING_DATA、producers、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH | 0/1 | ready |
| `moe_init_routing` | TILING_KEY、TILINGDATA_KERNEL_PATH | 0/0 | ready |
| `moe_finalize_routing_v2` | packing、producers、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH | 1/99 | ready |
| `apply_rotary_pos_emb` | packing、producers、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH、TILINGDATA_KERNEL_PATH | 6/8 | ready |
| `rope_with_sin_cos_cache` | producers、UNROOTED、INPUT_TILINGKEY_KERNEL_PATH、TILINGDATA_KERNEL_PATH | 1/1 | ready |

无 TPL 时 `source_declared` keys 能建出来，但 `SetTilingKey` / `GetTilingKey()` 绑定仍经常是 0。TilingData class index 仍有漏 host `op_tiling` 头或 stub 未接到 kernel 读边的情况。

### 5. extract 脚本崩（1 个）

`rotary_position_embedding_grad` prepare 已过，`extract_host` 报 `'NoneType' object has no attribute 'group'`。这是 UO extract 正则/走查的空匹配，不是算子源码错误。

---

## 推广时测试怎样才算过

这个 harness 过线标准就是：**每个抽到的算子都要 verify pass，并且 `.uo` 能 locate Key/Field/Kernel/Input/`OP_CHECK`。** 目前闭合的是 FAG 与 `matmul_reduce_scatter_v2` arch22。

下一步仍只修 UO（假编译环境里的 Cube/SoftMax 类型可见性、`atomic_type_t`/`Mode` 残差归属、无 TPL packing 绑定、extract 空匹配），禁止改算子仓，禁止 `UO_TEST_ALLOW_UNVERIFIED_SCOPE`。

复跑：

```text
$env:UO_GEN_OUT = "artifacts/uo-init-generalization/pass8-accept"
python engines/understand-operator/tools/uo_init_generalization.py
```

不要设 `UO_TEST_ALLOW_UNVERIFIED_SCOPE`，不要 wipe FAG arch22。
