## 测什么

本次 PR 把 TND dense swizzle 的确定性臂从编译期 `&& false` 解开。新增 host helper `IsTndDeterSwizzleScheduleSafe`（`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:106-134`），在 `DoOpTiling` 里写成 `deterTndSwizzleSafe = !isDeterministic || IsTndDeterSwizzleScheduleSafe`（`:743`），再进入 `templateSupportCond` 的 deter 析取支（`:744-747`）。**唯一写点**是 `:753-755`：

`tndBaseInfo.isTndSwizzle = enableSwizzle ∧ layout==TND ∧ templateSupportCond ∧ B<TND_SWIZZLE_PREFIX_NUM(129) ∧ ¬isSeqExistZero ∧ tailZeroCount==0`

打包进 TILING_KEY `replay.IsTndSwizzle`（`:1787-1795`）。`InitTilingData` 为 swizzle 选带 `tndSwizzleParam_` 的模板（`:2082-2095` deter、`:2109-2120` nondeter）。kernel 新增 `CalTNDDenseSwizzleIndex`（`op_kernel/arch35/deter.h:1607-1646`）；`CalDenseDeterIndex` 的 `IS_TND_SWIZZLE` 臂调用它（`flash_attention_score_grad_kernel_deter.h:437-443`），`CalDeterMaxLoopNum` 同旗标读 `tndS2BlockPrefixSum`（`:606-608`）。既有 `IsTndSwizzle` TILING_KEY 位（`flash_attention_score_grad_template_tiling_key.h:123`）扩展 ARGS_SEL。

这次改动的实质是 **TND 下按 batch 的 S2 前缀和做 dense swizzle 重排**，确定性臂还要先通过 `m >= min(aicNum, n)` 的安全检查；声称逐位结果不变。行为面不是 `deterMaxRound>0`（causal/BAND/GQA 也会写那个字段），而是 `isTndSwizzle` 能否被写成 1。该赋值只有这一处，Target 用 `replay.IsTndSwizzle==1` 即可与兄弟写点分开。

`templateSupportCond` 是同一层 `||` 的两支，**取反一支后另一支仍能打到 expected=1**：

- deter：`isDeterministic ∧ splitAxis==BN2GS1S2 ∧ DETER_DENSE ∧ g==1 ∧ deterTndSwizzleSafe`
- nondeter：`¬isDeterministic ∧ splitAxis==BN2S2 ∧ (s1>=2048 ∨ (s2>128 ∧ s1>=1024)) ∧ sparseType≠UNSUPPORTED`

因此 **`is_deter=0` 不是 Guard**。`g==1` 与 `deterTndSwizzleSafe` 只出现在 deter 支：`g>1` 或 unsafe 时 nondeter 支仍能 HIT，建成 Dimension 两格都是 ON；**不要和切 `is_deter` 的维做 L1**（`g>1 ∧ is_deter=1`、`unsafe ∧ is_deter=1` 是死格）。

`SetSplitAxis`（`tiling_common_regbase.cpp:1657-1718`）会改写 `splitAxis` / 有时改写 `isDeterministic`。`BN2_MAX_S=128`，HIT 行 S 通常已经 >128，`isBn2` 为假。此时 TND + `n1==n2` + `d<=512` + `¬hasRope` 会走上 `BN2S2`。deter 支需要 `BN2GS1S2`，所以 **p-deter 配 `rope=1` 打断 `bn2S2RouteLimit`；p-nondeter 配 `rope=0` 才能保持 BN2S2**。禁止用全局 `constraints` 钉死 `rope`（会杀死另一臂）。

`enableSwizzle = (isExceedL2Cache ∨ isLargeInvalidBlk) ∧ blockOuter==aicNum`（`:731`）。前一项同一层 `||` 两支都能开 swizzle，建成一维两格互斥 ON（probe 观测，不要猜幅度）。`blockOuter==aicNum` 是合取，HIT 行都要成立，用 probe constraint，不要钉 Dimension/Guard 列。

杀整 Target（取反后 expected 再也打不到）：`layout≠TND`、`B>=129`、`isSeqExistZero`、PREFIX 5/6（deter 落 DETER_OLD，nondeter `GetSparseType` 落 UNSUPPORTED）。空 mask 下 `sparse_mode∈{0,1,2,3,4}` 仍 `¬isSparse`→DETER_DENSE，**不能**当 Guard。

## 覆盖什么

一个 Target：`replay.IsTndSwizzle==1`。Dimension 覆盖 enableSwizzle 外层 `||`、templateSupportCond 两臂（含 rope 与 split 耦合）、`deterTndSwizzleSafe`、nondeter 内层 S1 阈值 `||`、`g==1` vs `g>1`。L3 覆盖非 TND、B 越界、seq 含 0、PREFIX。L1 只配字段不相交且笛卡尔每格都能 HIT 的对。

## 怎么判定

命中看 `replay.IsTndSwizzle`（辅读 `probe.isTndSwizzle` / `probe.deterTndSwizzleSafe`）。正确性看 oracle：kernel 重排 index，md5 在 `is_deter=1` 时由 harness 落盘；全体行做精度比对。

```yaml
schema: tg-plan/v3
requirement:
  id: R-fag-tnd-dense-swizzle
  text: >
    新增：IsTndDeterSwizzleScheduleSafe（flash_attention_score_grad_tiling_normal_regbase.cpp:106-134），
    每 batch 要求 m=ceil(actualSeqQ/cubeBaseM) >= min(aicNum, n=ceil(actualSeqKv/cubeBaseN))，
    否则返回 false。DoOpTiling 写 deterTndSwizzleSafe=!isDeterministic||safe（:743），
    templateSupportCond（:744-752），tndBaseInfo.isTndSwizzle（:753-755），
    打包 replay.IsTndSwizzle（:1787-1795）。InitTilingData：IsNewDeter∧isTndSwizzle
    走 FagTilingWithTemplateTTTT+tndSwizzleParam_（:2082-2095）；isTndSwizzle 走
    FagTilingWithTemplateFFTT（:2109-2120）。新增 kernel CalTNDDenseSwizzleIndex
    （deter.h:1607-1646）；改动 CalDenseDeterIndex IS_TND_SWIZZLE 调该函数
    （kernel_deter.h:437-443）及坐标 decode（:471-480）；CalDeterMaxLoopNum
    IS_TND_SWIZZLE 读 tndS2BlockPrefixSum（:606-608）。既有 IsTndSwizzle TILING_KEY
    （template_tiling_key.h:123）扩展 ARGS_SEL；enableSwizzle（:731）；
    GetDeterSparseTilingKey DETER_DENSE（:1111-1114）；SetSplitAxis
    （tiling_common_regbase.cpp:1657-1718）。
    唯一写点 :753。Target HIT = replay.IsTndSwizzle==1（不要用 deterMaxRound>0）。
    路径条件 = enableSwizzle ∧ layout==TND ∧ templateSupportCond ∧ B<129 ∧
    ¬isSeqExistZero ∧ tailZeroCount==0；DoSparse 成功。
    templateSupportCond 同一层 ||：deter(isDeterministic∧BN2GS1S2∧DETER_DENSE∧g==1∧
    deterTndSwizzleSafe) | nondeter(¬isDeterministic∧BN2S2∧(s1>=2048||(s2>128∧s1>=1024))∧
    sparseType≠UNSUPPORTED)。两支都能打到 expected=1，is_deter=0 不是 Guard。
    g==1 与 safe 只杀 deter 支，g>1 / unsafe 靠 nondeter 仍 HIT，建成 Dimension；
    不要和切 is_deter 的维 L1。
    SetSplitAxis：BN2_MAX_S=128，HIT 行通常 !isBn2；TND∧n1==n2∧d<=512∧¬hasRope
    → BN2S2。deter 支要 BN2GS1S2，故 p-deter 用 rope=1 打断 bn2S2RouteLimit；
    p-nondeter 用 rope=0 保持 BN2S2。禁止全局 constraints 钉 rope。
    enableSwizzle 同一层 ||：isExceedL2Cache | isLargeInvalidBlk，再合取
    blockOuter==aicNum。CheckIsLargeInvalidBlk 要 LEFT_UP_CAUSAL 且 s1Outer<s2Outer
    且 (s2Outer-s1Outer)*s1Outer>=3072 且 d<=256；空 mask 下 sm=2 仍 DETER_DENSE。
    空 mask 下 sm∈{0,1,2,3,4} 都 ¬isSparse→DETER_DENSE，不能当 Guard。
    PREFIX 5/6：GetDeterSparseTilingKey→DETER_OLD，GetSparseType→UNSUPPORTED，杀整。
    layout≠TND、B>=129、seqlens 含 0（isSeqExistZero）杀整。
    environment：aicNum=32（tests/ut/op_host/arch35/test_flash_attention_score_grad_tiling.cpp:49），
    coreNum 取 compile aivNum=64（同文件:48 → GetPlatformInfo:673），不要抄 UT 结构体里另一个 coreNum=32。

targets:
  - id: T-is-tnd-swizzle-on
    evidence: {kind: replay_field, field: replay.IsTndSwizzle, expected: 1}

dimensions:
  - id: D-enableSwizzle-arm
    target: T-is-tnd-swizzle-on
    controls: [S1, S2, D, B, N1, sparse_mode]
    classifier: {requires: [probe.isExceedL2Cache, probe.isLargeInvalidBlk]}
    partitions:
      - id: p-exceed-l2cache-on
        predicate:
          op: and
          args:
            - {op: eq, field: probe.isExceedL2Cache, value: 1}
            - {op: eq, field: probe.isLargeInvalidBlk, value: 0}
      - id: p-large-invalid-blk-on
        predicate:
          op: and
          args:
            - {op: eq, field: probe.isExceedL2Cache, value: 0}
            - {op: eq, field: probe.isLargeInvalidBlk, value: 1}

  - id: D-template-deter-nondeter
    target: T-is-tnd-swizzle-on
    controls: [is_deter, rope]
    classifier: {requires: [case.is_deter, case.rope]}
    partitions:
      - id: p-template-deter-arm
        predicate:
          op: and
          args:
            - {op: eq, field: case.is_deter, value: 1}
            - {op: eq, field: case.rope, value: 1}
      - id: p-template-nondeter-arm
        predicate:
          op: and
          args:
            - {op: eq, field: case.is_deter, value: 0}
            - {op: eq, field: case.rope, value: 0}

  - id: D-deterTndSwizzleSafe
    target: T-is-tnd-swizzle-on
    controls: [seqlens_list_q, seqlens_list_kv, N1, S1, S2, D]
    classifier: {requires: [probe.deterTndSwizzleSafe]}
    partitions:
      - id: p-deter-swizzle-safe
        predicate: {op: eq, field: probe.deterTndSwizzleSafe, value: 1}
      - id: p-deter-swizzle-unsafe-nondeter-fallback
        predicate: {op: eq, field: probe.deterTndSwizzleSafe, value: 0}

  - id: D-nondeter-s1-threshold
    target: T-is-tnd-swizzle-on
    controls: [S1, S2]
    classifier: {requires: [case.S1, case.S2]}
    partitions:
      - id: p-s1-ge2048-on
        predicate:
          op: and
          args:
            - {op: ge, field: case.S1, value: 2048}
            - {op: ge, field: case.S2, value: 16}
      - id: p-s2gt128-s1ge1024-on
        predicate:
          op: and
          args:
            - {op: lt, field: case.S1, value: 2048}
            - {op: gt, field: case.S2, value: 128}
            - {op: ge, field: case.S1, value: 1024}

  - id: D-g-eq1
    target: T-is-tnd-swizzle-on
    controls: [N1, N2]
    classifier: {requires: [case.N1, case.N2]}
    partitions:
      - id: p-g-eq1-mha
        predicate:
          op: and
          args:
            - {op: eq, field: case.N1, value: 4}
            - {op: eq, field: case.N2, value: 4}
      - id: p-g-gt1-gqa
        predicate:
          op: and
          args:
            - {op: eq, field: case.N1, value: 8}
            - {op: eq, field: case.N2, value: 2}

guards:
  - id: G-layout-not-tnd
    target: T-is-tnd-swizzle-on
    controls: [Input_Layout]
    predicate: {op: ne, field: case.Input_Layout, value: TND}
    negate_hint: {Input_Layout: TND}

  - id: G-b-ge-swizzle-prefix
    target: T-is-tnd-swizzle-on
    controls: [B]
    predicate: {op: ge, field: case.B, value: 129}
    negate_hint: {B: 8}

  - id: G-seq-exist-zero
    target: T-is-tnd-swizzle-on
    controls: [seqlens_list_q, seqlens_list_kv]
    predicate: {op: eq, field: case.seqlens_list_q, value: "[16,0,16]"}
    negate_hint: {seqlens_list_q: "[16,16,16]"}

  - id: G-prefix-old
    target: T-is-tnd-swizzle-on
    controls: [sparse_mode]
    predicate: {op: in, field: case.sparse_mode, values: [5, 6]}
    negate_hint: {sparse_mode: 0}

coverage:
  L0:
    dimensions:
      - D-enableSwizzle-arm
      - D-template-deter-nondeter
      - D-deterTndSwizzleSafe
      - D-nondeter-s1-threshold
      - D-g-eq1
  L1:
    combinations:
      - dims: [D-enableSwizzle-arm, D-template-deter-nondeter]
        reason: enableSwizzle 外层 || 与 templateSupportCond 析取字段不相交；rope 只服务 splitAxis 耦合
      - dims: [D-enableSwizzle-arm, D-deterTndSwizzleSafe]
        reason: enableSwizzle 与 safe 字段不相交；unsafe 格靠 is_deter=0 仍可达
      - dims: [D-enableSwizzle-arm, D-g-eq1]
        reason: enableSwizzle 与 g 分岔不相交；g>1 仅杀 deter 臂
      - dims: [D-enableSwizzle-arm, D-nondeter-s1-threshold]
        reason: enableSwizzle 与 nondeter S1 内层 || 不相交；deter 臂不依赖该阈值
      - dims: [D-nondeter-s1-threshold, D-g-eq1]
        reason: S1/S2 与 N1/N2 不相交；g>1 不阻断 nondeter 臂
  L2:
    mode: full_cross
    exclusions:
    - partitions: {D-template-deter-nondeter: p-template-deter-arm, D-g-eq1: p-g-gt1-gqa}
      reason: "g>1 只杀 deter 析取支；与 is_deter=1 同格是死格，HIT 只能走 nondeter"
    - partitions: {D-template-deter-nondeter: p-template-deter-arm, D-deterTndSwizzleSafe: p-deter-swizzle-unsafe-nondeter-fallback}
      reason: "deterTndSwizzleSafe==0 只杀 deter 支；与 is_deter=1 同格是死格，unsafe 格靠 nondeter HIT"
  L3:
    guards:
      - G-layout-not-tnd
      - G-b-ge-swizzle-prefix
      - G-seq-exist-zero
      - G-prefix-old

oracle:
  - id: O-tnd-swizzle-md5
    kind: md5
    fields: [Actual_dq_Md5sum, Actual_dk_Md5sum, Actual_dv_Md5sum]
    when: {op: eq, field: case.is_deter, value: 1}
    reason: TND dense swizzle 重排核间累加顺序但声称逐位不变；harness 仅 is_deter=1 时算 md5。
  - id: O-golden-precision
    kind: precision
    fields: [Actual_dq_pricision, Actual_dk_pricision, Actual_dv_pricision]
    reason: 比对 golden，确认调度重排不改变 dq/dk/dv 数值。

constraints:
  - id: c-block-outer-eq-aic-num
    reason: enableSwizzle 合取项 blockOuter==aicNum（tiling_normal_regbase.cpp:731）
    predicate: {op: eq, field: probe.blockOuter, value: 32}
  - id: c-tail-zero-count-zero
    reason: isTndSwizzle 写点要求 tailZeroCount==0（:755）
    predicate: {op: eq, field: probe.tailZeroCount, value: 0}

environment:
  aicNum: 32
  coreNum: 64

untestable:
  - id: u-Dtype
    kind: control_gap
    reason: Dtype unresolved，挡住 queryType→CheckExceedL2Cache 输入字节宽度。
    needs_binding:
      - {column: Dtype, want: "confirmed+active，并证实 dtype→queryType→CheckExceedL2Cache 传导链"}
  - id: u-out_dtype
    kind: control_gap
    reason: out_dtype unresolved，与 IsTndSwizzle 写点无 confirmed 绑定。
    needs_binding:
      - {column: out_dtype, want: "confirmed+active"}
  - id: u-Atten_mask_dtype
    kind: control_gap
    reason: Atten_mask_dtype unresolved。
    needs_binding:
      - {column: Atten_mask_dtype, want: "confirmed+active"}
  - id: u-Atten_mask_shape
    kind: control_gap
    reason: >
      Atten_mask_shape unresolved。空 mask 下 ¬isSparse 已是 DETER_DENSE，
      sm∈{2,3,4} 不能当杀整 Guard。要构造真正 isSparse=true 的 CAUSAL/BAND
      逃逸，必须 Atten_mask_shape≠NONE。
    needs_binding:
      - {column: Atten_mask_shape, want: "confirmed+active，并证实 atten_mask_shape→isSparse→GetDeterSparseTilingKey"}
  - id: u-PSE_shape
    kind: control_gap
    reason: PSE_shape unresolved，不进入 isTndSwizzle 写点。
    needs_binding:
      - {column: PSE_shape, want: "confirmed+active"}
  - id: u-eod
    kind: control_gap
    reason: eod unresolved；tailZeroCount 本轮只能 probe，不能用 eod 列直接构造。
    needs_binding:
      - {column: eod, want: "confirmed+active，并证实 eod→tailZeroCount"}
  - id: u-inner_drop
    kind: control_gap
    reason: inner_drop unresolved，不进 controls。
    needs_binding:
      - {column: inner_drop, want: "confirmed+active"}
  - id: u-is_sink
    kind: control_gap
    reason: is_sink unresolved。
    needs_binding:
      - {column: is_sink, want: "confirmed+active"}

test_harness_gap:
  done: false
  reason: >
    Dtype 挡住 CheckExceedL2Cache 字节宽度维；Atten_mask_shape 挡住 isSparse=true
    时 CAUSAL/BAND 对 deter 臂的逃逸。IsTndDeterSwizzleScheduleSafe 的 m=min(k,n)
    临界更适合 host UT 直调。
  needs_binding:
    - {column: Dtype, want: "confirmed+active"}
    - {column: Atten_mask_shape, want: "confirmed+active"}
  missing_rows:
    - "Atten_mask_shape≠NONE + sparse_mode=2 + is_deter=1 + TND，覆盖真正 isSparse 的 DETER_CAUSAL 对 deter 臂的影响（nondeter 仍可能 HIT）"
    - "Dtype∈{bf16,fp32} × TND × enableSwizzle 两臂"
  alternative_carrier:
    - "host UT 直调 IsTndDeterSwizzleScheduleSafe，覆盖 m==min(aicNum,n)-1 与 m>=min(k,n) 边界"
```

<!-- ===================== GRADING RUBRIC (not part of the artifact) =====================

评分不做字面 diff。ID、具体 S1/S2/B/N1、L1 选哪几对允许不同。
必过 = 路径正确 + Solve 能消费（validate_plan_fence + compile_obligations）。
规模（维数/partition 个数）只作 INFO，不决定 PASS/FAIL。

必过:

R1  Target 标识本次写点：replay.IsTndSwizzle 或 probe.isTndSwizzle。
    只用 replay.deterMaxRound>0 ⇒ FAIL（兄弟路径也会写）。

R2  templateSupportCond 是 ||：is_deter=0 仍能 HIT。把 is_deter=0 / ¬is_deter
    写成杀整 Guard ⇒ FAIL。

R3  g==1 只杀 deter 支。把 g>1 或 N1≠N2 写成杀整 Guard ⇒ FAIL。
    把 g==1 vs g>1 建成两格都 ON 的 Dimension 是对的（与 10295 相反）。

R4  layout≠TND、B>=129、isSeqExistZero 才是杀整 Guard。不要把 TND 写成
    Guard 谓词（那是 HIT 取值）。

R5  IsTndDeterSwizzleScheduleSafe / m>=min(aicNum,n) 必须出现。
    unsafe 格靠 nondeter 仍 HIT，不要写成杀整；不要和切 is_deter 的维 L1。

R6  kernel 点名 CalTNDDenseSwizzleIndex。host 局部量有赋值不得标 opaque。
    至少一维用 probe.*。

R7  environment 同时有 aicNum 与 coreNum 整数。不要把 9851 的
    coreNum==2*aicNum 抄进本计划 constraints。coreNum 取 GetPlatformInfo
    赋给 fBaseParams.coreNum 的 aivNum，不是 UT 结构体里另一个 coreNum 字段。

R8  INFO：dims/partitions/guards 计数。不作为必过。

R9  oracle 含 md5（index 重排）。

R10 Dtype 与 Atten_mask_shape 必须 untestable control_gap，不得进 controls。

R11 形式：confirmed+active；H6 同维字段组相同；Guard 根 case.* + 能翻回的
    negate_hint；is_deter 用 int 0/1；constraints 不钉 Guard.controls。

R12 solve-contract：validate_plan_fence + compile_obligations。

加分（不影响 PASS/FAIL）:

B1  template 维把 rope 与 is_deter 耦合成两格，而不是全局钉 rope。
B2  PREFIX 5/6 建成 Guard。
B3  写明空 mask 下 sm∈{1,2,3,4} 仍 DETER_DENSE。
B4  L1 不配 D-g × D-template、D-safe × D-template。

===================================================================================== -->
