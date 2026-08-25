## 测什么

本次 PR 新增 host 侧 `GQADenseScheduleResult`、`PositiveGcd`、`SelectGQADenseSchedule`（`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:48-104`），以及三个调度常量 `GQA_DENSE_MAX_ROUND_GROWTH_PERCENT=3`、`GQA_DENSE_MAX_INVALID_PERCENT=4`、`GQA_DENSE_PERCENT_BASE=100`（`flash_attention_score_grad_tiling_common_regbase.h:139-141`）。接入点是既有 `CalcleDeterParam` 的新分支（`:1203-1214`）：在 `layout≠TND ∧ deterSparseType==DETER_DENSE ∧ g>1` 时调用选择器，并把 `fBaseParams.deterMaxRound = selectedRound * s1Outer`。既有 TILING_FIELD `deterMaxRound` 因此多了一条 **GQA DENSE 覆写路径**（打包 `baseDeterParam_->set_deterMaxRound`，`:2187`）。kernel 侧既有 `CalGQADenseIndex`（`deter.h:241`）新增 `denseRound` 入参：`denseRound>0` 时直接当 R，否则回退 `max(ceil(b*n*g/k), ceil(n/m), g)`；`CalDenseDeterIndex` 的 GQA 臂（`kernel_deter.h:459-462`，`IS_N_EQUAL==false`）把 `deterMaxRound/s1Outer` 传进去；`CalDeterMaxLoopNum` 的 DETER_DENSE∧¬IS_N_EQUAL 臂（`:623-624`）在 `deterMaxRound>0` 时直接返回该值。

这次改动的实质是 **GQA DENSE 确定性调度把 round 对齐到 g，以缩短 batch/head 遍历周期**，同时声称逐位结果不变。行为面不是「`deterMaxRound` 是否非零」（causal / band / TND / varlen 也会写这个字段），而是三层：(1) 进入新选择器的入口路由；(2) 选择器内部「保持 `baseRound`」vs「升到 `candidateRound`」——由 `baseRound % g == 0` 早退，以及未对齐时 `roundCostOk ∧ invalidCostOk ∧ localityBetter ∧ rowOffsetEnough` 四项合取决定；(3) kernel 用 host 写下的 R 替换本地公式。第 (2) 层是本次核心。

可达性结论：本行为的 **唯一写点** 是 `tiling_normal_regbase.cpp:1209`。到该行的路径条件 = `isDeterministic` ∧ `deterSparseType≠DETER_OLD` ∧ `layout≠TND` ∧ `deterSparseType==DETER_DENSE` ∧ `g>1`。`CalcleDeterParam` 在 DETER_DENSE 下 **不会** 走 `needChangeSplitItemMode1/2`（`:1178-1183` 把 DENSE 排除），因此写完后 **不会** 再 `deterMaxRound *= 2`。

`GetDeterSparseTilingKey`（`:1075-1078`）把 DETER_DENSE 判给：`¬isSparse` **或** `sparse_mode==ALL_MASK(1)` **或** `(NO_MASK(0) ∧ s1Token≥s1 ∧ s2Token≥s2)`。这与 PR-9851 的 BAND 入口方向相反，但不能把 9851 的 token 句子整句取反就当成本次 HIT 条件。`SetSparseParams`（`tiling_common_regbase.cpp:1594-1598`）在 `ALL_MASK` **或** `attenMaskOptional==EMPTY_TENSOR` 时直接 `isSparse=false`；`ProcessTokensInfo`（`:1325-1328`）在同样条件下把 `s1Token/s2Token` 改成 `INT32_MAX`。init 默认 `Atten_mask_shape=NONE` 时，**case 列上的 Pre/Next_Tockens 不会分流本写点**（空 mask 已使 `¬isSparse` 成立，token 也被改成盖满）。因此：

- HIT 见证可以是 `sparse_mode=0`（空 mask 即 DETER_DENSE），`sparse_mode=1`（ALL_MASK）也是同一层 `||` 的另一支 ON，不要写成 Guard。
- 不要把「token 不覆盖」抄成 GQA 写点的必要 HIT 条件；也不要把「token 不盖满」写成杀整 Guard——空 mask 下小 token 仍是 DETER_DENSE。
- `sparse_mode∈{2,3,4}` 在空 mask 下同样走 `¬isSparse` → DETER_DENSE，**不能**当成本 Target 的 Guard。要让 CAUSAL/BAND 杀整本写点，必须 `isSparse=true`，依赖 `Atten_mask_shape≠NONE`，该列 `unresolved`，本轮 untestable。
- 仅当 atten_mask 非空且 `sparse_mode=0` 时，token 不盖满才会落到 DETER_BAND（`:1086-1090`）。那条逃逸本轮构造不了，不要假装已经建成 Guard。
- `PREFIX` 5/6 在 `SetSparseParams` 里先走 `SetPrefixSparseParams`，`GetDeterSparseTilingKey` 落到 DETER_OLD，`CalcleDeterParam` 开头直接 return，这才是稀疏模式上的杀整 Guard。

`g==1`（MHA，kernel `IS_N_EQUAL`）杀整本写点：host 不进 `:1203` 分支，kernel 走 `CalDenseIndex/CalDenseSwizzleIndex`。不要把 `g==1` 做成 Dimension 的 off 格。`g>1` 的不同比值（如 2 与 4）两格都能 HIT，那才是 Dimension。

选择器内部（`:70-104`）：`k=min(aicNum, b*g*m, b*n)`（此处 `b` 实参已是 `fBaseParams.b*n2`，且已减 `tailZeroCount`）；`baseRound=max(ceil(b*n*g/k), ceil(n/m), g)`；若 `baseRound%g==0` 直接返回（selected=base）。否则 `candidateRound=ceil(baseRound/g)*g`，仅当四项合取成立才改写 selected。**保持 base 与升到 candidate 都能打到写点**（两格都是 ON）。四项合取只在未对齐臂上赋值，不能当成对所有 HIT 行做 unique class 的 L0 probe 维；它们必须写进 requirement，边界更适合 host UT。`baseRound % g` 早退本身是新增 `if`，在固定 `g=2` 时用 `probe.baseRound` 的奇偶做成 Dimension（两格都 ON）。

观测面：`baseRound` / `selectedRound` / `basePeriod` / `selectedPeriod` 在 `% g` 早退前就有 `<name> =`，可 probe；`roundCostOk` 等四布尔在对齐早退后才赋值。打包字段 `replay.deterMaxRound` 可回读，但 **不能单独当 Target evidence**。本 Target 用 `probe.selectedRound>0` 标识「`SelectGQADenseSchedule` 产出了有效日程」。

## 覆盖什么

一个 Target：`SelectGQADenseSchedule` 产出 `selectedRound>0`（从而 `:1209` 覆写 `deterMaxRound`）。Dimension 覆盖 DETER_DENSE 入口析取（`sparse_mode=0/1`）、GQA 比、k 夹紧、layout、S1 几何、以及 `baseRound%g` 早退。L3 覆盖杀整门：非 deter、TND、MHA `g==1`、PREFIX。L1 只配字段不相交且笛卡尔每格都能 HIT 的对；`D-align` 不与 `D-k-clamp` / `D-gqa-ratio` 交叉（前者会死格，后者 H7 撞 N1/N2）。

## 怎么判定

命中看 `probe.selectedRound`（辅读 `replay.deterMaxRound`）；正确性看 oracle md5（GQA index 重排仍声称逐位不变）。harness 仅 `is_deter=1` 时算 `Actual_dq/dk/dv_Md5sum`，与本 Target 定义域重合。

```yaml
schema: tg-plan/v3
requirement:
  id: R-fag-gqa-dense-schedule
  text: >
    新增：GQADenseScheduleResult、PositiveGcd、SelectGQADenseSchedule
    （flash_attention_score_grad_tiling_normal_regbase.cpp:48-104）；
    常量 GQA_DENSE_MAX_ROUND_GROWTH_PERCENT/MAX_INVALID_PERCENT/PERCENT_BASE
    （flash_attention_score_grad_tiling_common_regbase.h:139-141）；
    CalcleDeterParam GQA DENSE 分支写 fBaseParams.deterMaxRound=selectedRound*s1Outer
    （:1203-1214），打包 baseDeterParam.set_deterMaxRound（:2187）。
    改动 kernel：CalGQADenseIndex 增 denseRound 入参（deter.h:241-246），
    denseRound>0 则 R=denseRound 否则回退 max(ceil(b*n*g/k),ceil(n/m),g)；
    CalDenseDeterIndex GQA 臂传 deterMaxRound/s1Outer（kernel_deter.h:459-462）；
    CalDeterMaxLoopNum DETER_DENSE∧¬IS_N_EQUAL 在 deterMaxRound>0 时直接返回
    （:623-624）。既有：GetDeterSparseTilingKey（:1069）、deterMaxRound TILING_FIELD、
    DeterSparseType::DETER_DENSE=2、CalcleDeterParam 入口。
    唯一写点 :1209。路径条件 = isDeterministic ∧ deterSparseType≠DETER_OLD ∧
    layout≠TND ∧ deterSparseType==DETER_DENSE ∧ g>1。DETER_DENSE 下
    needChangeSplitItemMode1/2 为假，写后不会 *=2。
    DETER_DENSE 入口 ||：¬isSparse | ALL_MASK | (NO_MASK ∧ token 盖满)。
    init 默认 Atten_mask_shape=NONE 时 SetSparseParams:1594-1598 使 isSparse=false，
    ProcessTokensInfo:1325-1328 把 token 改成 INT32_MAX，故 sparse_mode=0 即 HIT，
    不必再把「token 盖满」写成必要约束，更不能抄 9851「token 不覆盖全长」当 HIT。
    sparse_mode=1 ALL_MASK 是同一层 || 的另一支 ON，不是 Guard。
    sparse_mode∈{2,3,4} 在空 mask 下仍 ¬isSparse→DETER_DENSE，不能当 Guard；
    CAUSAL/BAND 杀整依赖 isSparse=true 与 Atten_mask_shape≠NONE（unresolved）。
    PREFIX 5/6 → DETER_OLD，CalcleDeterParam 开头 return，才是稀疏模式 Guard。
    g==1 杀整写点（Guard），g=2 与 g=4 两格都能 HIT。
    选择器：k=min(aicNum,b*g*m,b*n)；baseRound=max(ceil(bng/k),ceil(n/m),g)；
    baseRound%g==0 则 selected=base 返回；否则 candidateRound=ceil(baseRound/g)*g，
    仅当 roundCostOk（增长≤3%）∧ invalidCostOk（无效 ID≤4%）∧ localityBetter
    （candidatePeriod<basePeriod 且 <k）∧ rowOffsetEnough
    （ceil(k/candidatePeriod)≤m）才升 selected。保持 base 与升 candidate 都能
    打到 expected。四布尔只在未对齐臂赋值，不对所有 HIT 行做 L0 unique class。
    实参 b 已是 (B-tailZeroCount)*N2。kernel CalDenseDeterIndex 用 coreNum/2 当 k，
    host 用 aicNum；本 UT aivNum=64→coreNum、aicNum=32，二者相等，不要把
    coreNum==2*aicNum 抄进本计划 constraints。
    environment：aicNum=32（tests/ut/op_host/arch35/test_flash_attention_score_grad_tiling.cpp:49），
    coreNum 取 compile aivNum=64（同文件:48 → GetPlatformInfo:643）。

targets:
  - id: T-gqa-dense-schedule
    evidence:
      kind: derived
      predicate: {op: gt, field: probe.selectedRound, value: 0}

dimensions:
  - id: D-entry-route
    target: T-gqa-dense-schedule
    controls: [sparse_mode]
    classifier: {requires: [case.sparse_mode]}
    partitions:
      - {id: p-entry-no-mask, predicate: {op: eq, field: case.sparse_mode, value: 0}}
      - {id: p-entry-all-mask, predicate: {op: eq, field: case.sparse_mode, value: 1}}

  - id: D-gqa-ratio
    target: T-gqa-dense-schedule
    controls: [N1, N2]
    classifier: {requires: [case.N1, case.N2]}
    partitions:
      - id: p-g-eq-2
        predicate:
          op: and
          args:
            - {op: eq, field: case.N1, value: 4}
            - {op: eq, field: case.N2, value: 2}
      - id: p-g-eq-4
        predicate:
          op: and
          args:
            - {op: eq, field: case.N1, value: 8}
            - {op: eq, field: case.N2, value: 2}

  - id: D-k-clamp
    target: T-gqa-dense-schedule
    controls: [B, S2]
    classifier: {requires: [case.B, case.S2]}
    partitions:
      - id: p-k-full-aic
        predicate:
          op: and
          args:
            - {op: eq, field: case.B, value: 8}
            - {op: eq, field: case.S2, value: 4096}
      - id: p-k-clamped
        predicate:
          op: and
          args:
            - {op: eq, field: case.B, value: 1}
            - {op: eq, field: case.S2, value: 256}

  - id: D-layout
    target: T-gqa-dense-schedule
    controls: [Input_Layout]
    classifier: {requires: [case.Input_Layout]}
    partitions:
      - {id: p-layout-bnsd, predicate: {op: eq, field: case.Input_Layout, value: BNSD}}
      - {id: p-layout-bsnd, predicate: {op: eq, field: case.Input_Layout, value: BSND}}
      - {id: p-layout-bsh, predicate: {op: eq, field: case.Input_Layout, value: BSH}}
      - {id: p-layout-sbh, predicate: {op: eq, field: case.Input_Layout, value: SBH}}

  - id: D-s1-outer
    target: T-gqa-dense-schedule
    controls: [S1]
    classifier: {requires: [case.S1]}
    partitions:
      - {id: p-s1-256, predicate: {op: eq, field: case.S1, value: 256}}
      - {id: p-s1-4096, predicate: {op: eq, field: case.S1, value: 4096}}

  - id: D-align-early-return
    target: T-gqa-dense-schedule
    controls: [N1, N2]
    classifier: {requires: [probe.baseRound]}
    partitions:
      - id: p-base-aligned
        predicate:
          op: and
          args:
            - {op: eq, field: case.N1, value: 4}
            - {op: eq, field: case.N2, value: 2}
            - {op: mod_eq, field: probe.baseRound, divisor: 2, value: 0}
      - id: p-base-unaligned
        predicate:
          op: and
          args:
            - {op: eq, field: case.N1, value: 4}
            - {op: eq, field: case.N2, value: 2}
            - {op: mod_eq, field: probe.baseRound, divisor: 2, value: 1}

guards:
  - id: G-is-deter-off
    target: T-gqa-dense-schedule
    controls: [is_deter]
    predicate: {op: eq, field: case.is_deter, value: 0}
    negate_hint: {is_deter: 1}

  - id: G-tnd-layout
    target: T-gqa-dense-schedule
    controls: [Input_Layout]
    predicate: {op: eq, field: case.Input_Layout, value: TND}
    negate_hint: {Input_Layout: BNSD}

  - id: G-mha-g-eq-1
    target: T-gqa-dense-schedule
    controls: [N1, N2]
    predicate:
      op: and
      args:
        - {op: eq, field: case.N1, value: 4}
        - {op: eq, field: case.N2, value: 4}
    negate_hint: {N1: 4, N2: 2}

  - id: G-prefix-old
    target: T-gqa-dense-schedule
    controls: [sparse_mode]
    predicate: {op: eq, field: case.sparse_mode, value: 5}
    negate_hint: {sparse_mode: 0}

  - id: G-prefix-compress
    target: T-gqa-dense-schedule
    controls: [sparse_mode]
    predicate: {op: eq, field: case.sparse_mode, value: 6}
    negate_hint: {sparse_mode: 0}

coverage:
  L0:
    dimensions:
      - D-entry-route
      - D-gqa-ratio
      - D-k-clamp
      - D-layout
      - D-s1-outer
      - D-align-early-return
  L1:
    combinations:
      - dims: [D-entry-route, D-gqa-ratio]
        reason: "NO_MASK/ALL_MASK 都是 DETER_DENSE；g 进入 baseRound=max(...,g) 与 %g 早退，sparse_mode 与 N1/N2 不相交"
      - dims: [D-entry-route, D-k-clamp]
        reason: "入口路由不改变 k=min(aicNum,b*g*m,b*n) 的几何夹紧"
      - dims: [D-entry-route, D-layout]
        reason: "非 TND layout 改变 s1/s2 轴来源，与 sparse_mode 入口析取独立"
      - dims: [D-entry-route, D-s1-outer]
        reason: "s1Outer=m 进入 ceil(n/m) 与 k 的 b*g*m 项，与入口析取独立"
      - dims: [D-gqa-ratio, D-k-clamp]
        reason: "k=min(aicNum,b*g*m,b*n)，g 与 (B,S2) 共同决定是否夹到 aicNum"
      - dims: [D-gqa-ratio, D-layout]
        reason: "layout 改 g 的形状来源轴（BNSD 直接 N1/N2，BSH/SBH 用 H 比），g 比值仍由 N1/N2 列给出"
      - dims: [D-gqa-ratio, D-s1-outer]
        reason: "g 与 m=s1Outer 同时进入 baseRound 的 max 与 k 夹紧项 b*g*m"
      - dims: [D-k-clamp, D-layout]
        reason: "B、S2 决定 b*n 夹紧项，layout 决定 S2 轴在 tensor 上的位置"
      - dims: [D-k-clamp, D-s1-outer]
        reason: "m=s1Outer 进入 k=min(...,b*g*m,b*n)，n=s2Outer 进入 b*n 夹紧与 ceil(n/m)"
      - dims: [D-layout, D-s1-outer]
        reason: "非 TND layout × S1 共同决定 s1Outer"
      - dims: [D-align-early-return, D-layout]
        reason: "baseRound%g 早退与 layout 轴来源不相交；不要和 D-k-clamp 交叉（p-k-full 在 g=2 时常使 baseRound 恒偶，p-unaligned 死格）"
      - dims: [D-align-early-return, D-s1-outer]
        reason: "m 改变 ceil(n/m) 与 ceil(bng/k)，可翻转 baseRound 奇偶；不要和 D-gqa-ratio 交叉（H7 撞 N1/N2）"
      - dims: [D-align-early-return, D-entry-route]
        reason: "对齐早退在选择器内部，入口 sparse_mode 析取在 GetDeterSparseTilingKey，字段不相交"
  L2: []
  L3:
    guards:
      - G-is-deter-off
      - G-tnd-layout
      - G-mha-g-eq-1
      - G-prefix-old
      - G-prefix-compress

oracle:
  - id: O-gqa-bitwise-md5
    kind: md5
    fields: [Actual_dq_Md5sum, Actual_dk_Md5sum, Actual_dv_Md5sum]
    reason: >
      GQA dense index 重排核间累加顺序但声称逐位不变；harness 在 is_deter=1 时
      计算 Actual_dq/dk/dv_Md5sum。
  - id: O-golden-precision
    kind: precision
    fields: [Actual_dq_pricision, Actual_dk_pricision, Actual_dv_pricision]
    reason: 比对 golden，确认调度重排不改变 dq/dk/dv 数值。

constraints: []

environment:
  aicNum: 32
  coreNum: 64

untestable:
  - id: u-dtype
    kind: control_gap
    reason: Dtype 列 unresolved，不能把 dtype 分岔建成 Dimension。
    needs_binding:
      - {column: Dtype, want: "confirmed+active，并证实 Dtype→queryType→tiling dtype 传导链"}
  - id: u-out-dtype
    kind: control_gap
    reason: out_dtype unresolved，未映射到本写点。
    needs_binding:
      - {column: out_dtype, want: "confirmed+active，并证实 out_dtype→outDtype 传导链"}
  - id: u-atten-mask-shape
    kind: control_gap
    reason: >
      Atten_mask_shape unresolved。空 mask 下 ¬isSparse 已是 DETER_DENSE，token 与
      sparse_mode∈{2,3,4} 都不分流本写点。要构造 isSparse=true 从而让 NO_MASK 未盖满
      落到 DETER_BAND、或让 CAUSAL/BAND 杀整本写点，必须 Atten_mask_shape≠NONE。
    needs_binding:
      - {column: Atten_mask_shape, want: "confirmed+active，并证实 Atten_mask_shape→attenMaskOptional→SetSparseParams.isSparse→GetDeterSparseTilingKey"}
  - id: u-atten-mask-dtype
    kind: control_gap
    reason: Atten_mask_dtype unresolved。
    needs_binding:
      - {column: Atten_mask_dtype, want: "confirmed+active，并证实 atten_mask dtype 传导链"}
  - id: u-pse-shape
    kind: control_gap
    reason: PSE_shape unresolved，不进入 SelectGQADenseSchedule。
    needs_binding:
      - {column: PSE_shape, want: "confirmed+active"}
  - id: u-eod
    kind: control_gap
    reason: eod unresolved；选择器实参 b 已减 tailZeroCount，本轮无法用 eod 列直接构造 trim。
    needs_binding:
      - {column: eod, want: "confirmed+active，并证实 eod→tailZeroCount→SelectGQA 的 b 实参"}
  - id: u-inner-drop
    kind: control_gap
    reason: inner_drop unresolved。
    needs_binding:
      - {column: inner_drop, want: "confirmed+active"}
  - id: u-is-sink
    kind: control_gap
    reason: is_sink unresolved。
    needs_binding:
      - {column: is_sink, want: "confirmed+active"}

test_harness_gap:
  done: false
  reason: >
    Atten_mask_shape 挡住 isSparse=true 的 BAND 逃逸与 CAUSAL/BAND 杀整；Dtype 挡住
    dtype 维。选择器四布尔与 candidate 3%/4% 临界更适合 host UT 直调
    SelectGQADenseSchedule。
  needs_binding:
    - {column: Atten_mask_shape, want: "confirmed+active，证实到 isSparse→DETER_BAND 逃逸"}
    - {column: Dtype, want: "confirmed+active，证实到 tensor dtype"}
  missing_rows:
    - "Atten_mask_shape≠NONE + sparse_mode=0 + token 不盖满 + is_deter=1 + N1=4 N2=2，覆盖 NO_MASK→DETER_BAND 对本写点的逃逸"
    - "Atten_mask_shape≠NONE + sparse_mode=2 + is_deter=1 + g>1，覆盖真正的 DETER_CAUSAL 杀整"
    - "Dtype∈{bf16,fp32} × is_deter=1 × sparse_mode=0 × g>1"
  alternative_carrier:
    - "host UT 构造 (k,m,n,b,g) 直调 SelectGQADenseSchedule，断言 selectedRound∈{baseRound, candidateRound}，覆盖 roundCostOk 增长=3%、invalid=4%、localityBetter 临界、rowOffsetEnough 临界，以及 baseRound%g==0 早退"
```

<!-- ===================== GRADING RUBRIC (not part of the artifact) =====================

评分不做字面 diff。ID、具体 S1/S2/B/N1 取值、L1 选哪几对允许不同。只查下面语义。

必过（任一条不过即 FAIL）:

R1  可达性方向正确：主 Target 的 HIT 见证必须包含 sparse_mode=0。
    若计划把 9851 的「token 不覆盖全长」当成 *本* 写点的必要 HIT 条件 ⇒ FAIL。
    若计划把「token 不盖满」或 sparse_mode∈{1,2,3,4} 写成杀整 Guard ⇒ FAIL
    （空 mask 下它们仍是 DETER_DENSE；sm=1 更是同一层 || 的 ON 支）。
    依据：GetDeterSparseTilingKey:1075-1078；SetSparseParams:1594-1598；
    ProcessTokensInfo:1325-1328。

R2  路径条件含 layout≠TND 与 g>1；requirement 写明 g==1 杀整本写点。把 g==1
    做成 Dimension 第二格（两格都声称 HIT）⇒ FAIL。constraints 不得钉 N1==N2==1
    （那是 9851 BAND 的 g==1 前置，会杀死本写点）。

R3  不要把 ALL_MASK(sparse_mode=1) 写成杀整 Guard。它是 DETER_DENSE 合法入口。

R4  Target evidence 不能只靠 replay.deterMaxRound>0（causal/band/TND 也会写）。
    必须能标识 SelectGQADenseSchedule 这条写点：probe.selectedRound / 选择器
    返回值。只断言 deterMaxRound>0 ⇒ FAIL。

R5  选择器内部判定点必须出现在 requirement：baseRound%g 早退、candidateRound
    对齐、roundCostOk、invalidCostOk、localityBetter、rowOffsetEnough。
    四布尔只在未对齐臂赋值，L0 用它们对**所有** HIT 行做 unique class ⇒ FAIL。
    完全不提这些判定点 ⇒ FAIL。

R6  命名 host 局部量不得写成 opaque：selectedRound / baseRound / basePeriod /
    selectedPeriod 在早退前就有赋值。kernel 必须点名 CalGQADenseIndex。
    至少有一个 Dimension 的 classifier/谓词引用 probe.*。

R7  环境：aicNum 与 coreNum 都有，且 aicNum 有 UT/platform 出处。SelectGQA 的 k
    是 aicNum。不要把 9851 的 coreNum==2*aicNum 抄进本计划的 constraints。

R8  规模（INFO，不决定 PASS/FAIL）：dimensions≥5，partitions≥12，guards≥4，L1 非空。
    必过是路径正确 + Solve 能消费（R12）。

R9  oracle 含 md5。改动重排 GQA index。

R10 Dtype 与 Atten_mask_shape 必须 untestable control_gap，不得进 controls。

R11 形式：confirmed+active 列；H6 同维字段组相同；Guard 根 case.* + negate_hint；
    eq 用 {op:eq,field:,value:标量}；constraints 不钉 Guard.controls；
    case.* 用 init 列名（Input_Layout、Pre_Tockens、Next_Tockens）；
    is_deter 字面量写 int 0/1。

R12 solve-contract：validate_plan_fence + compile_obligations 通过。

加分（不影响 PASS/FAIL）:

B1  写明 DETER_DENSE 下 needChangeSplitItemMode 为假，:1209 之后不会 *=2。
B2  alternative_carrier 指出四布尔临界与 baseRound%g 早退更适合 host UT。
B3  点名 CalDeterMaxLoopNum :623-624 与 CalGQADenseIndex denseRound>0 回退。
B4  明确空 mask 下 ProcessTokensInfo 改写 token，token 列不分流本写点；
    与 9851 BAND 入口方向相反但不能整句取反。

===================================================================================== -->
