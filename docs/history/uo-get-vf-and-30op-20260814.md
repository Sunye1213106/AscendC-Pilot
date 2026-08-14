# 工作记录：Get 绑回类方法、CANN VF 解析、ops-transformer 30 算子抽检

日期：2026-08-14  
仓库：`AscendC-Pilot`  
对照算子：`ops-transformer/attention/flash_attention_score_grad` arch35  
抽检根：`D:\TEST\ops-transformer`  
机器收据：`artifacts/uo-init-sample30-20260814/`

本记录对应两件 FAG 上故意不猜的 catalog 缺口，以及一次「质量是否被 FAG 特化」的均匀抽检。不改算子仓。

---

## 1. 问题

FAG arch35 当时 `quality.grade=ready`、`locate_blocking=0`，但 `catalog_unproven=55`。其中两类是定位面噪声，不是「没扫到调用点」：

| 类 | 约计数 | 现象 |
| --- | ---: | --- |
| `Get` | 28 | `dYL1Buf.Get()` / `pL1Buf.Get()` / `dSL1Buf.Get()`。接收者类型是 `std::conditional<IS_L1_REUSE, typename DyL1BuffSelector<…>::TYPE, …>`。多个 Policy 都有 `Get`。没有 USR、没有唯一声明根时，标成 CANN `Get` 或某个 Policy 都是猜。调用点在图里（`block_cube.h` 一带），只是不盖 REACHED。 |
| `Or` / `ExpSub` / `FusedMulDstAdd` / `FusedExpSub` | 24 | 全在 `vf_anti_quant_compute_p_ds.h`（Reg 向量形态）。同文件 `DataCopy` / `Cast` / `Log` / `Muls` 已 REACHED。这几个名字不在小 catalog；`Or` 不能按裸名字当 CANN（和逻辑或撞车）。词法看得见，没有 `callee_usr`、没有 CANN 声明路径，`_prove_ascendc_api_root` 过不了。 |

cannbot 要 buffer 用 buffer / `dYL1Buf`，不要靠裸名字 `Get`。

---

## 2. 做法（通用规则，不写 FAG 字段名）

### 2.1 Get → 类方法，不猜 CANN 自由 Get

- 有 receiver 的成员 `Get`：不是 wrapper / 不是 `Get<DType>()` 时标 **PROJECT**，BINDS 到 METHOD，attrs 带 `receiver`。`std::conditional` / `Selector` 不做 owner 猜测，不填某个 Policy。
- `MutexBuffer::Get` 仍走已有 wrapper bridge → `LocalTensor`（REACHED）。
- `mm1ResBuf[i].template Get<CALC_TYPE>()` 是 TBuf 形态：词法补上带下标的 receiver，`Get<DType>` → `LocalTensor`。
- 无 receiver、无 template 实参、无 identity 的残缺 `Get` 丢掉（Clang 未写出基表达式时的幽灵点），避免标成 CANN `Get`。

关键文件：`passes/kernel_root_trace.py`，`passes/kernel_scan.py`（`_CALL_RE` 允许 `ident[…].Get`）。

### 2.2 CANN VF / Reg API

- 新模块 `semantics/ascendc_vf.py`：从 CANN `kernel_reg_compute_*.h` / `kernel_operator_vec_*_intf.h` 扫 `__simd_callee__` / `__aicore__` 声明。
- 别名：`FusedExpSub`→`ExpSub`，`FusedMulDstAdd`→`MulDstAdd`。
- `Or` / `And` / `Xor` / `Min` / `Max` 必须是 Reg/向量形态（≥3 实参，或 `RegTensor` / `preg_` / `vreg_`）才 REACHED；裸 `Or` 不标 CANN。
- 词法扫描跨行补全括号（`Or(…,\n …)`）。
- `load_registry()` 合并 VF 名字，covered TU 的 primitives-only 填缝也能看见 `ExpSub`。

这次顺手把 Bisheng 限定符 `__no_simd_vf_fusion__` 加进 `spec/build_context.yaml` 的 `erase_qualifiers`（与 `__simd_callee__` 同类）。抽检里它曾作为 `unknown type name` 出现在多个 kernel 探针 sample 中。

---

## 3. FAG arch35 结果

只重跑 analyze → commit → verify（沿用已有 extract）。

| 指标 | 修之前 | 修之后 |
| --- | ---: | ---: |
| `catalog_unproven` | 55 | **1** |
| `host_runtime_leaf` | 13 | 13（Host 运行时叶子，保持） |
| `locate_blocking` | 0 | 0 |
| `unresolved.total` | 68 | **14** |
| `quality.grade` | ready | ready |
| verify | pass | pass |

按 callee：

| 名字 | 结果 |
| --- | --- |
| `Get` | 156 点：107 PROJECT（Policy/Selector，receiver=`dSL1Buf`/`pL1Buf`/`commonL1Buf`/…），49 REACHED（TBuf `Get<T>` + MutexBuffer） |
| `Or` | 9/9 REACHED |
| `ExpSub` | 6/6 REACHED |
| `FusedExpSub` | 4/4 → root `AscendC::ExpSub` |
| `FusedMulDstAdd` | 8/8 → root `AscendC::MulDstAdd` |

剩下 1 条 `catalog_unproven` 是项目函数 `ComputePDS_VF_unalign`（不是 CANN 头里的 VF API），不是这次两类缺口。

---

## 4. 30 算子抽检

种子 `UO_GEN_SEED=20260814`，按家族分层、优先 arch35，**强制纳入 FAG arch35 作对照**（不 wipe FAG arch22）。家族计数：attention 8、mc2 6、gmm 4、moe 4、mhc 3、posembedding 3、ffn 1、mamba 1。全程约 598s。

名单见 `artifacts/uo-init-sample30-20260814/results.json`。

| 状态 | 个数 | 含义 |
| --- | ---: | --- |
| verify pass / `grade=ready` | **1** | 只有 FAG |
| 进了 analyze/commit，verify 失败 | 9 | 图写出了，Host packing / INPUT / TilingData 边不齐 |
| 卡在 extract | 1 | `rotary_position_embedding_grad`：`extract_host` `'NoneType' object has no attribute 'group'`（与 pass8 同一崩点） |
| 卡在 prepare `SCOPE_VALIDATE_BLOCKED` | 19 | kernel 探针仍脏，没有 `.uo` |

**结论：Get / VF 闭合没有被做成 FAG 字段特化**——FAG 上那两类 catalog 缺口按通用规则收掉了。30 算子质量远低于 FAG，挡门在 **Clang 假编译环境 / Host 边**，不是这次的 `Get`/`Or`/`ExpSub`。

### 4.1 过了 prepare 的 9 个（相对 FAG）

共同特征：kernel API 针（DataCopy/EnQue/…）多数已有 span；verify 卡在 `MISSING_INPUT`/`MISSING_OUTPUT`、`MISSING_HOST_TILINGKEY_PRODUCERS`、`UNROOTED_TILING_KEYS`、`MISSING_TILINGDATA_KERNEL_PATH`。这与 [uo-init-generalization.md](../test/uo-init-generalization.md) pass8「已出图但 Host packing 边不齐」是同一类，不是 VF catalog。

`ffn_worker_batching` 额外 `catalog_unproven=64`：`GetSortLen`、`SetWaitFlag`、`CeilDiv`、`ArithProgression`——下一批 CANN 名字（Sort / 标量辅助），不是 Reg `Or`/`ExpSub`。

`kv_rms_norm_rope_cache` 的 `locate_blocking=951` 几乎全是 `tilingData_.set_*` 的 `field_owner_ambiguous`（多份 TilingData 结构），FAG 的 `GET_TILING_DATA` 路径已经特化过，setter 风格没有同等闭合。

### 4.2 prepare 挡门（19 个）与一次复测

代表 sample（修限定符之前）：`unknown type name '__no_simd_vf_fusion__'`、`redefinition of 'asc_dump'`。

加上 `erase_qualifiers: __no_simd_vf_fusion__` 后复测：

- `moe/moe_gating_top_k`：`__no_simd_vf_fusion__` 从 sample 消失；仍 `SCOPE_VALIDATE_BLOCKED`，新 sample 是 **`unknown type name 'SoftMaxTiling'`**（pass8 已记录的 cube/softmax 高阶类型缺口）。
- `attention/scatter_pa_kv_cache`：同样不再报该限定符；仍脏，sample 变为 `asc_dump` / `cce` / `Dim3`。

所以 VF 限定符是真缺口、也已补上，但 **不足以** 让这 19 个算子过 prepare。下一刀仍是 CANN 类型进 kernel TU（`SoftMaxTiling` / `TCubeTiling` / `Dim3`），不要再往 FAG 字段名上靠。

---

## 5. 代码与测试

| 路径 | 作用 |
| --- | --- |
| `src/uo_init/semantics/ascendc_vf.py` | CANN VF 头扫描 + Fused* 别名 |
| `src/uo_init/semantics/registry.py` | 合并 VF 进 classify |
| `src/uo_init/passes/kernel_root_trace.py` | PROJECT 成员 Get；Reg 形态证明；`Get<T>` bridge |
| `src/uo_init/passes/kernel_scan.py` | 下标 receiver、跨行实参、primitives 含 Get/VF |
| `spec/build_context.yaml` | `__no_simd_vf_fusion__` |
| `tools/uo_init_generalization.py` | `UO_OPS_ROOT` / `UO_GEN_SAMPLE` / `UO_GEN_SEED`，inspect 读 `quality.yaml` |
| `tests/unit/test_kernel_root_trace.py` | Selector Get、TBuf `Get<T>`、VF/Or |
| `tests/unit/test_ascendc_vf.py` | 别名与 registry |

相关单测 47 passed（root-trace + VF + lexical + gaps）。

复现抽检：

```text
set UO_OPS_ROOT=D:\TEST\ops-transformer
set UO_GEN_SAMPLE=30
set UO_GEN_SEED=20260814
set UO_GEN_OUT=.../artifacts/uo-init-sample30-20260814
python engines/understand-operator/tools/uo_init_generalization.py
```

---

## 6. 下一步（按挡门人数，不是按 FAG 字段）

1. **Kernel 探针 CANN 类型可见性**（19/30 prepare）：`SoftMaxTiling` / `TCubeTiling` / `Dim3` / `cce`。假编译环境接到真编译器同级可见性；禁止 `UO_TEST_ALLOW_UNVERIFIED_SCOPE`。
2. **Host packing / INPUT proto**（9/30 有 `.uo` 但 not_ready）：与 pass8 同一张表，不是 kernel catalog。
3. **下一批 CANN 名字**：`GetSortLen`、`ArithProgression`、`SetWaitFlag`（ffn）。继续走头文件扫描，不要按算子白名单。
4. **`tilingData_.set_*` owner**（`kv_rms_norm_rope_cache` 类）：多结构 setter，和 FAG `GET_TILING_DATA` 不是同一条规则。
5. **extract_host `NoneType.group`**：`rotary_position_embedding_grad`，pass8 已点名。

FAG 冷启动质量入口未改：仍看 [benchmark.md](../benchmark.md)。本抽检不是质量门。
