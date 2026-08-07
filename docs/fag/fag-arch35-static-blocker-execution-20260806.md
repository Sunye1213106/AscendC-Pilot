# FlashAttentionScoreGrad arch35：静态 blocker、脚本优化与全量 tilingkey 闭环执行记录

时间：2026-08-06/07（Asia/Shanghai）  
Pilot 仓库：`D:\TEST\AscendC-Pilot`  
Pilot HEAD：`c099dd12c879a75dae393a31ac0419a438dd91c6`  
FAG 算子路径：`D:\TEST\ops-transformer\attention\flash_attention_score_grad`  
FAG 源码 HEAD：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`  
分析架构：`op_host/arch35` + `op_kernel/arch35`  
本轮 run：`RUN_20260806_145234_1b8a792b`

## 最终结论

这轮已经做到 `full tilingkey closure`：

| 集合 | 数量 | 说明 |
|---|---:|---|
| `D` | 8705 | 从 arch35 kernel tilingkey 模板声明域展开得到的 legal key |
| `R` | 3521 | WSL Host replay 真实命中的 declared key，有可复现实例 |
| `E` | 5184 | 经源码 guard 证明不可达的 key，由 source-lemma rules 排除 |
| `R - D` | 0 | 没有越过 kernel declared domain 的 replay key |
| `R ∩ E` | 0 | 没有把已命中的 key 错排除 |
| `D - R - E` | 0 | 没有剩余 open key |

最终校验：

```json
{
  "ok": true,
  "declared": 8705,
  "R": 3521,
  "R_declared": 3521,
  "undeclared": 0,
  "E": 5184,
  "violation": 0,
  "gap": 0
}
```

关键产物：

- closure：`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\closure.csv`
- real examples：`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\R.txt`
- source exclusions：`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\excluded.txt`
- active source lemmas：`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\lemmas\active_rules.yaml`
- residual：`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\residual.csv`

## KB 是否包含 kernel 和 tilingdata 信息

包含。当前 UO/TG 静态产物不是只有 host predicate，也包含 kernel 分支和 tilingdata 字段信息。

| 项 | 值 |
|---|---:|
| `source_closure` | 1.0 |
| `blocker_count` | 0 |
| `KernelBranch` | 485 |
| `TilingDataField` | 143 |
| `TilingKeyDim` | 19 |
| `TemplateBinding` | 65 |
| `Variable` | 542 |
| `operator_graph.node_count` | 1254 |
| `operator_graph.edge_count` | 355 |
| `legal_key_count` | 8705 |
| `integrity.status` | pass |
| `kb_review.verdict` | pass |

需要分清两件事：

1. `underivable=8705` 不是 KB 没有 kernel/tilingdata，也不是 UO source closure 失败；它只表示没有启用 UO deep value_expr/Z3 去逐值反推每个 key。
2. 本轮正确路线是 Z3-free：用 KB/domain 构造候选，用 WSL Host replay 得到 `R`，再对剩余 open key 做源码 guard 审核并生成 source-lemma `E`。

## 本轮执行路线

1. 删除旧 TG 产物，避免混入之前随机、越域或失败回放结果。
2. 本机静态分析 UO/KB/TG host view，确认 KB 包含 kernel 和 tilingdata。
3. 本机根据 KB/open domain 做 candidate 构造，不做无依据随机。
4. WSL 运行 Host replay，把真正命中的 key 写入 `R`。
5. 对 replay 后剩余 open key 做静态 residual 分类。
6. 逐个读 FAG arch35 源码 guard，判断是脚本构造问题还是源码不可达组合。
7. 对源码不可达组合生成 source-lemma 证书，先 dry-run 验证 `bad_R=0`，再 promote。
8. 再跑 `state/report/residual/route` 和 pytest。

这条链路没有使用 UO deep Z3。sklearn 只保留为 observation/ranking/blocker 诊断工具，不作为证明来源，也不允许它把 direct KB 构造候选过滤掉。

## 清理和重跑

按要求删除了旧产物后重跑。清理目标限定在本算子的 TG 目录：

- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure`
- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\replay`

清理后重建 declared domain：

```text
D = 8705
R = 0
E = 0
gap = 8705
```

静态分析在 Windows 本机完成；Host replay 在 WSL 完成。两边使用同一份工作区代码和同一份算子源码。

## UO 静态 blocker：31 个逐项归因

最初 UO static source closure 有 31 个 blocker。逐项读源码后判断，这批大多不是“必须让 LLM 猜引理”的问题，而是静态脚本对 C++ 局部状态、容器、range-for、tuple unpack、caller/callee 参数传播、generated tiling pointer 等模式覆盖不足。

最终处理策略是修静态分析器，让它从源码机械推导这些 provenance，而不是把它们写成手工排除规则。

| blocker id | symbol/text | 初始类型 | 根因 | 处理 |
|---|---|---|---|---|
| `BLK_16E26E92B857` | `s1Max` | `UNMAPPED_SYMBOL` | 局部循环派生变量未被识别 | local root inference |
| `BLK_4F98EFC62AB9` | `s2Max` | `UNMAPPED_SYMBOL` | 同上 | local root inference |
| `BLK_690E9785207F` | `actualCalcS1Token` | `UNMAPPED_SYMBOL` | 循环内累积/自派生局部变量断链 | loop-derived local |
| `BLK_4AE6E1EBB077` | `actualCalcS2Token` | `UNMAPPED_SYMBOL` | 同上 | loop-derived local |
| `BLK_CE3B2E2B61C0` | `needCoreNum` | `UNMAPPED_SYMBOL` | 局部状态由 loop/container 推导 | local propagation |
| `BLK_74D0DC32002A` | `usedl2CacheSize` | `UNMAPPED_SYMBOL` | 容器/循环派生局部状态 | container/local propagation |
| `BLK_DB8BC1178103` | `invalidS1Array` | `UNMAPPED_SYMBOL` | 本地容器 `.size/.empty/.find` 等 accessor 未透明化 | transparent local container accessor |
| `BLK_806F53E02B1A` | `dkDvOffsetSet` | `UNMAPPED_SYMBOL` | 本地 set/vector/map 容器状态 root 丢失 | local container root |
| `BLK_BCC3415DD857` | `dqOffsetSet` | `UNMAPPED_SYMBOL` | 同上 | local container root |
| `BLK_2BC05D783EB7` | `dropMaskShapeSize` | `UNMAPPED_SYMBOL` | 输入 shape 派生到局部后断链 | local propagation |
| `BLK_2F7906B55DCB` | `w` | `UNMAPPED_SYMBOL` | 局部表达式/shape 派生断链 | local propagation |
| `BLK_F0FEE1EB1BE7` | `CheckExceedL2Cache` | `UNMAPPED_SYMBOL` | helper guard 返回值依赖 caller shape 和局部参数 | caller→callee parameter root propagation |
| `BLK_731408BC1F43` | `fBaseParams.splitAxis` | `UNMAPPED_SYMBOL` | TILING_DATA/member base 追踪不足 | TILING_DATA base member provenance |
| `BLK_3F08EA2C6B43` | `deterPrefixData.qNewList` | `UNMAPPED_SYMBOL` | tuple/container unpack 后局部 root 断链 | tuple/local propagation |
| `BLK_7B75629428D8` | `deterPrefixData.pNewList` | `UNMAPPED_SYMBOL` | 同上 | tuple/local propagation |
| `BLK_44821205A32D` | `deterTilingSplitMode` | `UNMAPPED_SYMBOL` | 常量分支 ternary 被误判为值不明 | constant-branch ternary provenance |
| `BLK_DCA2D1EB4F14` | `needSyncRounds` | `UNMAPPED_SYMBOL` | range-for/容器元素局部 root 缺失 | range/local inference |
| `BLK_FAC9F3EB04FA` | `needSyncRound` | `unexpected_token` | `CXX_FOR_RANGE_STMT` header 直接出现 `VAR_DECL` 未识别 | clang_walk range-for header |
| `BLK_6F34A244570C` | `syncRounds` | `FUNCTION_PARAMETER` | caller 局部容器传入 callee 后 formal root 丢失 | inferred_parameter_roots |
| `BLK_45DD6BE7E672` | `syncRoundRanges` | `FUNCTION_PARAMETER` | 同上 | inferred_parameter_roots |
| `BLK_B3734AE1F1FE` | `coreId` | `FUNCTION_PARAMETER` | loop induction 变量传入 callee 后 root 丢失 | caller loop root propagation |
| `BLK_AFD681358CAA` | `batchId` | `FUNCTION_PARAMETER` | loop-derived/induction 参数传播不足 | parameter root propagation |
| `BLK_8BD4FC8CFB17` | `gTail` | `FUNCTION_PARAMETER` | callee formal 来自 caller loop/container 表达式 | parameter expression root propagation |
| `BLK_250412B7899F` | `possibleMax` | `FUNCTION_PARAMETER` | callee formal 来自 loop-derived 局部 | parameter root propagation |
| `BLK_2B7172DA3802` | `num2` | `FUNCTION_PARAMETER` | helper 参数由 tuple/loop 派生 | tuple + parameter propagation |
| `BLK_99BA712D55D2` | `num1` | `FUNCTION_PARAMETER` | tuple unpack + `AbsCeil` actual 参数传播不足 | tuple unpack + actual expression propagation |
| `BLK_ABAB2AE983CF` | `s1ValidIdx` | `FUNCTION_PARAMETER` | caller/callee loop index formal root 丢失 | parameter root propagation |
| `BLK_D8712F8F4BA5` | `round` | `FUNCTION_PARAMETER` | range/loop 派生参数 root 丢失 | range-for + parameter propagation |
| `BLK_99781789024B` | `this.tndParam_` | `TILING_DATA_NO_WRITER` | generated tiling pointer 初始化为 `nullptr`，无显式 writer，但字段命名和使用表明是 generated tiling data pointer | field declaration fallback for `*Param_/*Params_` |
| `BLK_E27CD303BFD4` | `this.prefixN` | `TILING_DATA_NO_WRITER` | TILING_DATA/member default/write 覆盖分析不足 | TILING_DATA/member chase |

修完后：

```text
host-only static source_closure = 1.0
host-only blocker_count = 0
full refresh with kernel blocker_count = 0
kernel_branches = 485
```

这一步说明：UO 静态侧的问题主要是静态脚本能力不足，不是源码里不可建模的复杂循环，也不是要依赖 deep Z3。

## TG replay 前的构造问题和修复

### 问题 1：反向构造命中少，不应该靠盲随机

之前命中少的主要原因不是 sklearn 不够强，而是候选生成路线不对：有一部分流程会在 direct KB 构造不够时直接用 witness mutation/schema fallback 填满 budget。这样的样本不保证保持 `_target_key`，看起来像“在尝试某个 open key”，实际是在漂移探索。

本轮修改：

- `kb_guided_pool()` 默认 `explore_fill=False`。
- 先按 KB/open domain 对每个 open key 调 operator-specific inverse constructor。
- direct `kb_construct` 候选拥有最高优先级，sklearn 只能排序，不能把它们挤掉。
- mutation 只在显式打开 exploration 时使用，且 `_target_key=0`，避免被记成某个 target 的失败。
- random/control arm 也从当前 open set 取 target，只随机顺序和 knob choice，不回到无约束随机。

涉及代码：

- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\generate.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\search_round.py`

### 问题 2：同一轮 model/random 重复打同一批 key

之前同一轮里 model arm 和 random arm 都基于旧 open set 生成，model arm 新增的 R 不会及时从 random arm 候选里扣掉，导致 replay budget 浪费。

本轮修改：

- 先跑 model arm。
- 写回 `R` 后重算 open set。
- random/control arm 再从更新后的 open set 生成。

最终 clean run 里 round1/round2 都是 100% 新 declared key，没有同轮重复。

### 问题 3：17 位 tiling key 被 float/pandas 读坏

FAG tiling key 多为 17 位整数，CSV/pandas 很容易变成 float 后丢低位，造成 predicted/target/replay accounting 错乱。

本轮修改：

- 新增 `int_exact()`。
- corpus/generate/search/model 读取 key 时统一走 exact int。
- 增加 key precision 单测。

涉及代码：

- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\key_utils.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\tests\test_closure_key_precision.py`

### 问题 4：residual `--rows` 会把磁盘 CSV 也截断

`residual --rows 10` 本意只是命令行返回 10 行预览，但旧实现把写到磁盘的 `residual.csv` 也截断了，后续 blocker summary 会被污染。

本轮修改：

- 内存返回 `rows` 可以按 `max_rows` 截断。
- 磁盘 `residual.csv` 始终写完整 open set。
- 返回 `row_count` 和 `rows_truncated`。
- residual 距离计算增加 projection index，先查 distance=1/2，再 fallback 全扫。

涉及代码：

- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\residual.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\tests\test_closure_generation_policy.py`

### 问题 5：host view/export 重建太慢

`export_tg_host_view` 之前即使已有匹配的 `tg_host_view.yaml`，仍可能触发 `_ensure_bundle()` 重建 graph/host view，FAG 上会带来几十秒级开销。

本轮修改：

- 快速读取 `operator_graph.yaml` fingerprint 和 manifest。
- 如果现有 `tg_host_view.yaml` 的 graph fingerprint / manifest / source revision 匹配，则复用 durable view。
- 只重建 codemap index 和 receipt，不再重跑 full bundle。
- 默认 `with_kernel=False`，TG host view 不为 kernel 额外重建。

涉及代码：

- `D:\TEST\AscendC-Pilot\engines\understand-operator\src\uo_init\pilot_engines.py`
- `D:\TEST\AscendC-Pilot\engines\understand-operator\tests\test_tg_host_view.py`

已观测性能改善：真实 FAG cached export 从约 31.7s 降到约 2.0s。

### 问题 6：domain suspect 不能混进 R

探索 mutation 曾经发现 63 个 host replay 命中的 key 不在 kernel declared domain `D` 里，集中在 FLOAT32 + RoPE 相关区域。原因是 host 仍能 pack 出某些 key，但 kernel 模板声明域没有覆盖这类组合。

这不是可以计入 full closure 的 `R`；它是 host/kernel declared-domain mismatch 信号。

本轮修改：

- `search_round` 增加 `undeclared_R`、`new_undeclared_R`、`undeclared_path`。
- 只要出现 `R - D`，回合 `ok=false` 并标记 `domain_suspect=true`。
- clean run 使用 direct-KB-first 且默认关闭 exploration，最终 `undeclared=0`。

## WSL Host replay clean run

本轮 clean replay 的日志：

- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\runs\RUN_20260806_145234_1b8a792b\manual_logs\tg_search_round_final_clean6_seq_0001_budget1024.out.log`
- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\runs\RUN_20260806_145234_1b8a792b\manual_logs\tg_search_round_final_clean6_seq_0002_budget2048.out.log`
- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\runs\RUN_20260806_145234_1b8a792b\manual_logs\tg_search_round_final_clean6_seq_0003_budget8192.out.log`
- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\runs\RUN_20260806_145234_1b8a792b\manual_logs\tg_search_round_final_clean6_seq_0004_budget1024.out.log`
- `D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\runs\RUN_20260806_145234_1b8a792b\manual_logs\tg_search_round_final_clean6_seq_0005_empty_budget64.out.log`

回放结果：

| round | budget | model new declared | random new declared | undeclared | reject/crash/parse fail | 备注 |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 1024 | 512 | 512 | 0 | 0 | 初始 open=8705 |
| 2 | 2048 | 1024 | 1024 | 0 | 0 | round1 后 open=7681 |
| 3 | 8192 | 448 | 0 | 0 | 0 | direct KB 构造耗尽；open=5185 |
| 4 | 1024 | 0 | 0 | 0 | 0 | 暴露 empty tensor 构造漏掉 |
| 5 | 64 | 1 | 0 | 0 | 0 | 补上 `IsEmptyTensor=1` 的 1 个 key |

最终 replay corpus：

```text
rows = 3521
accepted = 3521
refused = 0
unique declared keys = 3521
undeclared = 0
```

empty tensor 处理：

- 去掉 `construction_hints.yaml` 里 `IsEmptyTensor: "0"` 的硬性要求。
- 在 FAG `construct_case()` 中增加空 tensor witness。
- WSL probe 验证 empty tensor 可命中 key `18014398509481985`。

## replay 后 residual 静态分析

在 replay 得到 `R=3521` 后，剩余 open：

```text
open = 5184
distance = {1: 3576, 2: 1392, 3: 216}
```

这 5184 个 open 被 `construct_reasons()` 压缩成 45 个 reason combination，再归并成 10 个源码 guard 家族。

完整 45 组明细在：

`D:\TEST\ops-transformer\attention\flash_attention_score_grad\.ascendc-pilot\arch35\tg\closure\construct_blocker_summary.csv`

10 个 guard 家族统计如下。计数是“命中该原因的 open key 数”，不同原因可以重叠，所以总和大于 5184。

| guard family | count | 判定 | 源码证据 |
|---|---:|---|---|
| `SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128` | 1920 | 源码不可达组合 | `flash_attention_score_grad_tiling_normal_regbase.cpp` 设置 `tndBaseInfo.isTndSwizzle`，依赖 TND、BN2S2/SplitAxis=5、非 FLOAT、D=64/128 等条件 |
| `ProcessSparseModeInfo: DeterType 3/4 requires atten_mask` | 1904 | 源码不可达组合 | `flash_attention_score_grad_tiling_common_regbase.cpp::ProcessSparseModeInfo` 只有从 sparse atten_mask 模式才能导出 DeterType 3/4 |
| `SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128)` | 640 | 源码不可达组合 | `SetSplitAxis` 中 BN2 路由要求 clean BN2 shape，且确定性/Drop/NEqual 会改写路线 |
| `SetSplitAxis: SplitAxis=5 requires non-FLOAT, no rope/deter/NEqual/BN2MultiBlk, DTemplate 64/128` | 608 | 源码不可达组合 | `SetSplitAxis` 中 BN2S2 路由要求非 FLOAT、非 RoPE、非 deterministic sparse、D=64/128 |
| `SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` | 600 | 源码不可达组合 | `SetSplitAxis` 计算 `isBn2MultiBlk`，受 BN2 shape、非 TND、非 RoPE、非 DNoEqual、非 Drop 等条件约束 |
| `IsNzOut: requires SplitAxis=0, non-TND, non-FLOAT, DTemplate=128, DeterType 0/2` | 544 | 源码不可达组合 | `flash_attention_score_grad_tiling_normal_regbase.cpp` 中 `isNzOut` 依赖 SplitAxis=BN2GS1S2、非 TND、非 FLOAT、D=128 等条件 |
| `SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` | 512 | 源码不可达组合 | TND 下 SplitAxis=1 的 route 会因 DTemplate/RoPE 条件被改写 |
| `GetDTemplateType: IsRope=1 forces DTemplateNum=192` | 512 | 源码不可达组合 | `GetDTemplateType()` 中 `hasRope` 直接返回 192 |
| `GetS1S2TemplateType: FLOAT expects S1/S2=(64,128) only for DTemplate=768 else (128,128)` | 352 | 源码不可达组合 | `GetS1S2TemplateType()` 对 FLOAT + 大 D 有特殊 S1 模板 |
| `GetTilingKey: IsRope=1 forces IsDNoEqual=1` | 320 | 源码不可达组合 | `GetTilingKey()` 中 `dNoEqual = (d1 != d) || hasRope` |

这些不是静态脚本 bug。它们的共同特点是：kernel tilingkey 模板枚举出了组合，但 host 写 key 时有更强的 derived guard，会把这些组合改写成别的 key 或根本不会生成。

## 45 个 residual reason combination 明细

| # | count | reasons |
|---:|---:|---|
| 1 | 1024 | `ProcessSparseModeInfo: DeterType 3/4 requires atten_mask` |
| 2 | 1024 | `SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128` |
| 3 | 512 | `ProcessSparseModeInfo: DeterType 3/4 requires atten_mask || SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128` |
| 4 | 432 | `SetSplitAxis: SplitAxis=5 requires non-FLOAT, no rope/deter/NEqual/BN2MultiBlk, DTemplate 64/128` |
| 5 | 224 | `IsNzOut: requires SplitAxis=0, non-TND, non-FLOAT, DTemplate=128, DeterType 0/2` |
| 6 | 192 | `GetS1S2TemplateType: FLOAT expects S1/S2=(64,128) only for DTemplate=768 else (128,128)` |
| 7 | 128 | `ProcessSparseModeInfo: DeterType 3/4 requires atten_mask || IsNzOut: requires SplitAxis=0, non-TND, non-FLOAT, DTemplate=128, DeterType 0/2` |
| 8 | 128 | `SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128 || IsNzOut: requires SplitAxis=0, non-TND, non-FLOAT, DTemplate=128, DeterType 0/2` |
| 9 | 120 | `SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128)` |
| 10 | 120 | `SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 11 | 96 | `SetSplitAxis: SplitAxis=5 requires non-FLOAT, no rope/deter/NEqual/BN2MultiBlk, DTemplate 64/128 || SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128` |
| 12 | 80 | `ProcessSparseModeInfo: DeterType 3/4 requires atten_mask || SetSplitAxis: SplitAxis=5 requires non-FLOAT, no rope/deter/NEqual/BN2MultiBlk, DTemplate 64/128` |
| 13 | 80 | `SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 14 | 64 | `GetS1S2TemplateType: FLOAT expects S1/S2=(64,128) only for DTemplate=768 else (128,128) || ProcessSparseModeInfo: DeterType 3/4 requires atten_mask` |
| 15 | 64 | `GetS1S2TemplateType: FLOAT expects S1/S2=(64,128) only for DTemplate=768 else (128,128) || SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128` |
| 16 | 64 | `ProcessSparseModeInfo: DeterType 3/4 requires atten_mask || SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128 || IsNzOut: requires SplitAxis=0, non-TND, non-FLOAT, DTemplate=128, DeterType 0/2` |
| 17 | 56 | `SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 18 | 56 | `SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 19 | 56 | `SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 20 | 56 | `SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 21 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1` |
| 22 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 23 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128)` |
| 24 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 25 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 26 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 27 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 28 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 29 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192` |
| 30 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 31 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128)` |
| 32 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 33 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 34 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 35 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 36 | 32 | `GetDTemplateType: IsRope=1 forces DTemplateNum=192 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 37 | 32 | `GetS1S2TemplateType: FLOAT expects S1/S2=(64,128) only for DTemplate=768 else (128,128) || ProcessSparseModeInfo: DeterType 3/4 requires atten_mask || SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128` |
| 38 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1` |
| 39 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 40 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128)` |
| 41 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope` |
| 42 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 43 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 44 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |
| 45 | 8 | `GetTilingKey: IsRope=1 forces IsDNoEqual=1 || SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128) || SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope || SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape` |

## source lemma 是怎么来的

当前 active rules 不是从外部材料“抄来的”，也不是任意写 21 条引理。

实际过程是：

1. 用 `construct_reasons()` 对剩余 open key 做静态解释。
2. 把 45 个组合归并为 10 个源码 guard 家族。
3. 逐个读 FAG arch35 host 源码确认 guard。
4. 为 rule engine 能支持的等值 conjunction 形式展开成 83 条 combo rule。
5. dry-run：确认这些 rule 覆盖所有 open key，且不会碰任何已 replay 命中的 `R`。
6. promote 到 active rules。
7. apply rules 后再次校验 `gap=0`、`violation=0`。

dry-run/promote/apply 结果：

```text
rules = 83
dry_run.excluded = 5184
dry_run.bad_R = 0
dry_run.miss_open = 0
dry_run.extra_not_open = 0
promoted = 83
skipped = 0
apply.excluded = 5184
revoked_count = 0
gap = 0
```

如果前面讨论里出现过“21 条引理”，那只是早期草案/中间候选。当前落地版以源码 guard 家族为证据来源，并由脚本展开为 83 条可执行 combo rule。

## 为什么之前“推理证明”单次慢

慢的主要原因有四类：

1. 旧路线会重复做 clang AST walk / host bundle / kernel API 解析，而不是复用已落盘 UO 产物。
2. `export_tg_host_view` 没有命中 durable cache，会重建 host view。
3. TG 侧候选生成存在重复 replay 和漂移探索，花了 budget 但不增加 declared `R`。
4. residual 旧实现对 open key 到 witness 的距离接近全量笛卡尔扫描。

这不是因为必须跑 deep Z3。当前路线把“证明”改成有限域枚举 + Host replay + 源码 guard certificate，单次耗时主要落在 WSL replay 和必要的静态解析上。

已做的提速：

- UO host view 可复用 cache，避免重复 `_ensure_bundle()`。
- residual 增加 projection index。
- `residual --rows` 不再截断磁盘全量 CSV。
- TG search 先 replay model/direct arm，再重算 open 给 random/control arm。
- direct KB 构造优先，不让 sklearn 或 mutation 挤掉。
- 增加 domain gate，遇到 undeclared key 立即暴露。

## 当前修改的脚本和测试

核心脚本：

- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\generate.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\search_round.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\residual.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\construct.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\testcase_agent\closure\key_utils.py`
- `D:\TEST\AscendC-Pilot\operators\flash_attention_score_grad\arch35\input_semantics.py`
- `D:\TEST\AscendC-Pilot\operators\flash_attention_score_grad\arch35\construction_hints.yaml`
- `D:\TEST\AscendC-Pilot\scripts\replay\inputs.py`
- `D:\TEST\AscendC-Pilot\engines\understand-operator\src\uo_init\pilot_engines.py`

测试：

- `D:\TEST\AscendC-Pilot\engines\testcase-generation\tests\test_closure_generation_policy.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\tests\test_closure_key_precision.py`
- `D:\TEST\AscendC-Pilot\engines\testcase-generation\tests\test_fag_arch35_input_semantics.py`
- `D:\TEST\AscendC-Pilot\engines\understand-operator\tests\test_tg_host_view.py`

本轮最终测试：

```text
26 passed in 2.66s
```

最终 TG 验证：

```text
state:    ok=true, D=8705, R=3521, E=5184, gap=0, violation=0, undeclared=0
report:   ok=true, witnessed=3521, excluded=5184, open=0, problem_count=0
residual: ok=true, open=0, row_count=0
route:    ok=true, reason=GAP_ZERO
```

## 当前还需要注意的边界

1. `R=3521` 是真实 Host replay example 覆盖；`E=5184` 是源码 guard 证明不可达，不是实际样例。
2. clean closure 没有包含 exploration mutation 发现的 FLOAT32+RoPE 越域 key；这类 key 已被标记为 host/kernel domain mismatch，不能算入 declared-domain closure。
3. source lemma 的安全门是 `bad_R=0` 和 `R∩E=0`；后续如果算子源码或 kernel 模板变了，需要用新的 `source_revision` 和 `uo_graph_fingerprint` 重新 dry-run/promote。
4. 本机未依赖 `clang.exe` 跑回放；WSL replay 路线可用。若后续要在 Windows 本机跑 harness/fold，再配置 LLVM/`CLANG_EXE` 即可。
