## 测什么

本次 PR 新增 `DeterBandScheduleMode` 枚举（DISABLED=0/CAUSAL=1/DENSE=2/BAND=3，`op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:28`）、TILING_FIELD `deterBandScheduleMode`（同文件:139）、host 侧两个新函数 `NormalizeDeterBandScheduleParams`（`op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:69`）与 `SelectDeterBandSchedule`（同文件:83）、`SelectBlockSchedule` 内 189-211 的 hybrid-band 选路、209-210 的 `isSplitByBlockIdx` 联动写入、182-187 新增的「RIGHT_DOWN_CAUSAL 保留 legacy swizzle」提前返回，以及 690-699 对 `deterMaxRound` 的覆写。既有符号（本次未引入，仅被新代码读写）：TILING_FIELD `isSplitByBlockIdx`（`tiling_data_regbase.h:133`，本次仅新增一条写入路径）、TILING_FIELD `deterMaxRound`（`tiling_normal_regbase.cpp:2122`，本次新增一条覆写路径）、`GetDeterSparseTilingKey`（同文件:1016）推导的 `deterSparseType`、`DeterType` TILING_KEY（`flash_attention_score_grad_template_tiling_key.h:93`）、kernel 侧 `CalBandDeterIndex`（`flash_attention_score_grad_kernel_deter.h:493`）与 `CalDeterMaxLoopNum`（同文件:594）—— 这两个函数既有，本次新增对 `deterBandScheduleMode` 的三路分支读取。

这次改动的实质是**重排 deterministic 累加的核间调度顺序以减少 round 数，同时要求逐位结果不变**。因此行为面不是「一个字段是否非零」，而是三层：(1) 进入新选择器的入口路由；(2) 选择器内部 BAND/DENSE/CAUSAL 的三路竞争，由 `bandBlocks`/`denseRound`/`causalRound` 三个 round 公式取 min 决定；(3) 选中之后 kernel 侧对应的 index 计算与 max-loop 公式。第 (2) 层是本次改动的核心，共 8 个判定点。

可达性结论：`deterBandScheduleMode` 非零的唯一写点是 `tiling_normal_regbase.cpp:689`，到该行的路径条件含一个**否定项** —— 必须 `¬(rightDownBandCond ∧ isSplitByBlockIdx)`，否则 182-187 提前返回保持 DISABLED。注意这个否定项**不等于**「排除 sparse_mode=3」：`isSplitByBlockIdx`（177-180）本身要求 `(b*n2)` 为偶数且 `s1 >= aicNum*128`，所以 `sparse_mode=3` 在 **B 为奇数**（本 plan 固定 `N2=1`，故 `b*n2` 奇偶即 B 奇偶）时该否定项成立，仍是合法入口。`sparse_mode=0` 需 token 不覆盖全长才被 `GetDeterSparseTilingKey` 判成 DETER_BAND。第三条入口 `sparse_mode=4`(BAND 掩码) 需要 `Atten_mask_shape != NONE`，该列 `confidence: unresolved`，本轮按 H1 不得进 controls。

观测面上，host 侧内部门（`canSplitByBlockIdx`、`hybridBandCond`、`useLowerCausal`、`denseK`、`bandBlocks`、`tailRound`）全部是有 `<name> =` 赋值的局部量，可由 replay-local 探针（sandbox 拷贝插 `TG_PROBE`、重编）直接观测，**不构成 opaque**。三路 mode 判别虽无法从 case 列预先算出，但 `replay.deterBandScheduleMode` 直接回读，可作为 classifier 依据 —— 覆盖靠观测而非预测。

## 覆盖什么

三个 Target 对应三个被本次改动写入的 TILING_FIELD：`deterBandScheduleMode`（新增字段）、`isSplitByBlockIdx`（新增写入路径）、`deterMaxRound`（新增覆写路径）。

11 个 Dimension 共 26 个 partition，分三组：入口层（`D-entry-route`、`D-token-normalize`）、选择器内部层（`D-band-geometry`、`D-schedule-mode`、`D-dense-candidacy`、`D-causal-embedding`、`D-causal-tail-parity`）、写入与形状层（`D-split-writer`、`D-max-round-override`、`D-layout`、`D-headdim-split`）。L1 取 12 对、L2 取 2 组三元，均在实现里有明确因果链；L3 覆盖 6 条负向门禁。

义务规模：L0 26 + L1 75 + L2 34 + L3 6 = 141 条。行数由 solve 决定，本 plan 不做构造。

## 怎么判定

`evidence` 全部落在 replay 字段与 replay-local 探针上，与 oracle 分账：命中判定看 `replay.*` / `probe.*`，正确性判定看 `oracle`。本次改动重排累加顺序但声称逐位不变，因此 oracle 必须包含 md5 逐位复现（harness 仅在 `is_deter=true` 时计算 `Actual_dq/dk/dv_Md5sum` 并落盘 dq/dk/dv.bin，恰好覆盖本 plan 全部义务行），以及对 golden 的精度比对。round 数下降是本次改动的性能主张，由 `Actual_kernel_time_backward` 配合 `replay.deterMaxRound` 记账。

```yaml
schema: tg-plan/v3
requirement:
  id: R-deter-band-schedule
  text: >
    新增：DeterBandScheduleMode 枚举（tiling_data_regbase.h:28）、TILING_FIELD
    deterBandScheduleMode（同文件:139）、NormalizeDeterBandScheduleParams
    （tiling_normal_regbase.cpp:69）、SelectDeterBandSchedule（同文件:83）、
    SelectBlockSchedule 内 189-211 hybrid-band 选路、209-210 isSplitByBlockIdx
    联动写、182-187 RIGHT_DOWN_CAUSAL legacy 提前返回、690-699 deterMaxRound 覆写。
    既有（本次仅新增读写路径）：isSplitByBlockIdx（tiling_data_regbase.h:133）、
    deterMaxRound（tiling_normal_regbase.cpp:2122）、GetDeterSparseTilingKey 推导的
    deterSparseType（同文件:1016）、DeterType TILING_KEY
    （template_tiling_key.h:93）、kernel 侧 CalBandDeterIndex
    （kernel_deter.h:493）与 CalDeterMaxLoopNum（同文件:594）。
    可达性：唯一非零写点 tiling_normal_regbase.cpp:689，路径条件
    = ¬(rightDownBandCond ∧ isSplitByBlockIdx) ∧ canSplitByBlockIdx
    ∧ deterSparseType==DETER_BAND ∧ g==1 ∧ coreNum==2*aicNum ∧ actualBatch>0。
    否定项不等于排除 sparse_mode=3：177-180 的 isSplitByBlockIdx 要求 (b*n2) 偶
    且 s1>=aicNum*128，故 sparse_mode=3 在 B 为奇数时该否定项成立，仍是合法入口
    （B 偶且 S1 大时才恒为 DISABLED，那条放 G-rdc-legacy-early-return）。
    sparse_mode=0 需 token 不覆盖全长才被判成 DETER_BAND。
    host 内部门均有 `<name> =` 赋值，可由 replay-local 探针观测，不是 opaque；
    BAND/DENSE/CAUSAL 三路判别不可预测但 replay.deterBandScheduleMode 可回读，
    故按 replay 字段做 classifier，覆盖靠观测不靠预测。

targets:
- id: T-deter-band-schedule-active
  evidence:
    kind: derived
    predicate: {op: gt, field: replay.deterBandScheduleMode, value: 0}
- id: T-deter-split-by-block-idx-on
  evidence: {kind: replay_field, field: replay.isSplitByBlockIdx, expected: 1}
- id: T-deter-max-round-overridden
  evidence:
    kind: derived
    predicate: {op: gt, field: replay.deterMaxRound, value: 0}

dimensions:
- id: D-entry-route
  target: T-deter-band-schedule-active
  controls: [sparse_mode, is_deter]
  classifier:
    requires: [case.sparse_mode, probe.rightDownBandCond]
  partitions:
  - {id: p-entry-no-mask, predicate: {op: eq, field: case.sparse_mode, value: 0}}
  - {id: p-entry-right-down-causal, predicate: {op: eq, field: case.sparse_mode, value: 3}}

- id: D-token-normalize
  target: T-deter-band-schedule-active
  controls: [Pre_Tockens, Next_Tockens]
  classifier:
    requires: [case.Pre_Tockens, case.Next_Tockens]
  partitions:
  - id: p-tokens-both-positive
    predicate:
      op: and
      args:
      - {op: gt, field: case.Pre_Tockens, value: 0}
      - {op: gt, field: case.Next_Tockens, value: 0}
  - id: p-pre-token-shifted
    predicate:
      op: and
      args:
      - {op: le, field: case.Pre_Tockens, value: -256}
      - {op: gt, field: case.Next_Tockens, value: 0}
  - id: p-next-token-shifted
    predicate:
      op: and
      args:
      - {op: gt, field: case.Pre_Tockens, value: 0}
      - {op: le, field: case.Next_Tockens, value: -256}

- id: D-band-geometry
  target: T-deter-band-schedule-active
  controls: [S1, S2]
  classifier:
    requires: [probe.bandBlocks, probe.colsPerBatch]
  partitions:
  - {id: p-band-blocks-small, predicate: {op: le, field: probe.bandBlocks, value: 64}}
  - {id: p-band-blocks-large, predicate: {op: gt, field: probe.bandBlocks, value: 64}}

- id: D-schedule-mode
  target: T-deter-band-schedule-active
  controls: [S1, S2, Pre_Tockens, Next_Tockens]
  classifier:
    requires: [replay.deterBandScheduleMode]
  partitions:
  - {id: p-mode-causal, predicate: {op: eq, field: replay.deterBandScheduleMode, value: 1}}
  - {id: p-mode-dense, predicate: {op: eq, field: replay.deterBandScheduleMode, value: 2}}
  - {id: p-mode-band, predicate: {op: eq, field: replay.deterBandScheduleMode, value: 3}}

- id: D-dense-candidacy
  target: T-deter-band-schedule-active
  controls: [S1, B]
  classifier:
    requires: [probe.denseK]
  partitions:
  - {id: p-dense-all-cores-active, predicate: {op: ge, field: probe.denseK, value: 8}}
  - {id: p-dense-core-starved, predicate: {op: lt, field: probe.denseK, value: 8}}

- id: D-causal-embedding
  target: T-deter-band-schedule-active
  controls: [S1, S2, Pre_Tockens, Next_Tockens]
  classifier:
    requires: [probe.useLowerCausal, probe.lowerWaste]
  partitions:
  - {id: p-causal-embeddable, predicate: {op: eq, field: probe.useLowerCausal, value: 1}}
  - {id: p-causal-not-embeddable, predicate: {op: eq, field: probe.useLowerCausal, value: 0}}

- id: D-causal-tail-parity
  target: T-deter-band-schedule-active
  controls: [B]
  classifier:
    requires: [case.B, probe.tailRound]
  partitions:
  - {id: p-batch-even, predicate: {op: mod_eq, left: case.B, divisor: 2, value: 0}}
  - {id: p-batch-odd, predicate: {op: mod_eq, left: case.B, divisor: 2, value: 1}}

- id: D-split-writer
  target: T-deter-split-by-block-idx-on
  controls: [sparse_mode, is_deter, B]
  classifier:
    requires: [probe.hybridBandCond, probe.canSplitByBlockIdx]
  partitions:
  - {id: p-writer-hybrid-new, predicate: {op: eq, field: probe.hybridBandCond, value: 1}}
  - {id: p-writer-legacy, predicate: {op: eq, field: probe.hybridBandCond, value: 0}}

- id: D-max-round-override
  target: T-deter-max-round-overridden
  controls: [S1, S2]
  classifier:
    requires: [replay.deterMaxRound]
  partitions:
  - {id: p-round-compact, predicate: {op: le, field: replay.deterMaxRound, value: 64}}
  - {id: p-round-long, predicate: {op: gt, field: replay.deterMaxRound, value: 64}}

- id: D-layout
  target: T-deter-band-schedule-active
  controls: [Input_Layout]
  classifier:
    requires: [case.Input_Layout]
  partitions:
  - {id: p-layout-bnsd, predicate: {op: eq, field: case.Input_Layout, value: BNSD}}
  - {id: p-layout-bsnd, predicate: {op: eq, field: case.Input_Layout, value: BSND}}
  - {id: p-layout-bsh, predicate: {op: eq, field: case.Input_Layout, value: BSH}}
  - {id: p-layout-sbh, predicate: {op: eq, field: case.Input_Layout, value: SBH}}

- id: D-headdim-split
  target: T-deter-band-schedule-active
  controls: [D_V]
  classifier:
    requires: [case.D_V]
  partitions:
  - {id: p-dv-equal-d, predicate: {op: eq, field: case.D_V, value: 64}}
  - {id: p-dv-differs-d, predicate: {op: eq, field: case.D_V, value: 128}}

guards:
- id: G-is-deter-off
  target: T-deter-band-schedule-active
  controls: [is_deter]
  predicate: {op: eq, field: case.is_deter, value: 0}
  negate_hint: {is_deter: 1}
- id: G-rdc-legacy-early-return
  target: T-deter-band-schedule-active
  controls: [sparse_mode, is_deter, B, S1]
  predicate:
    op: and
    args:
    - {op: eq, field: case.sparse_mode, value: 3}
    - {op: eq, field: case.is_deter, value: 1}
    - {op: mod_eq, left: case.B, divisor: 2, value: 0}
    - {op: ge, field: case.S1, value: 1024}
  negate_hint: {sparse_mode: 3, is_deter: 1, B: 1, S1: 1024}
- id: G-tnd-layout
  target: T-deter-band-schedule-active
  controls: [Input_Layout, is_deter]
  predicate:
    op: and
    args:
    - {op: eq, field: case.Input_Layout, value: TND}
    - {op: eq, field: case.is_deter, value: 1}
  negate_hint: {Input_Layout: BNSD, is_deter: 1}
- id: G-all-mask-sparse
  target: T-deter-band-schedule-active
  controls: [sparse_mode, is_deter]
  predicate:
    op: and
    args:
    - {op: eq, field: case.sparse_mode, value: 1}
    - {op: eq, field: case.is_deter, value: 1}
  negate_hint: {sparse_mode: 0, is_deter: 1}
- id: G-left-up-causal-sparse
  target: T-deter-band-schedule-active
  controls: [sparse_mode, is_deter]
  predicate:
    op: and
    args:
    - {op: eq, field: case.sparse_mode, value: 2}
    - {op: eq, field: case.is_deter, value: 1}
  negate_hint: {sparse_mode: 0, is_deter: 1}
- id: G-prefix-sparse
  target: T-deter-band-schedule-active
  controls: [sparse_mode, is_deter]
  predicate:
    op: and
    args:
    - {op: eq, field: case.sparse_mode, value: 5}
    - {op: eq, field: case.is_deter, value: 1}
  negate_hint: {sparse_mode: 0, is_deter: 1}

coverage:
  L0:
    dimensions:
    - D-entry-route
    - D-token-normalize
    - D-band-geometry
    - D-schedule-mode
    - D-dense-candidacy
    - D-causal-embedding
    - D-causal-tail-parity
    - D-split-writer
    - D-max-round-override
    - D-layout
    - D-headdim-split
  L1:
    combinations:
    - dims: [D-entry-route, D-token-normalize]
      reason: "sparse_mode 决定 s1Token/s2Token 取哪一路（GetDeterSparseTilingKey:1016），token 符号决定 NormalizeDeterBandScheduleParams:69 走哪条 shifted-BAND 转换；两者串联决定送进选择器的 (m,n,p,q)"
    - dims: [D-entry-route, D-layout]
      reason: "canSplitByBlockIdx:164 含 layoutType != TND，且 s1Outer/s2Outer 随 layout 变，同一 sparse_mode 在不同 layout 下进选择器的 m,n 不同"
    - dims: [D-token-normalize, D-band-geometry]
      reason: "token 定 p,q，p+q 与 m 的关系决定 :100 走哪条 bandBlocks 公式（l1/l2/l3 两套算法）"
    - dims: [D-token-normalize, D-schedule-mode]
      reason: "归一化后的 p,q 直接进三个 round 公式，token 形态换了谁最小就换"
    - dims: [D-band-geometry, D-schedule-mode]
      reason: "bandBlocks 同时进 :141 的 lowerWaste 阈值判定和 :116 的 BAND maxRound，是三路竞争的共同输入"
    - dims: [D-dense-candidacy, D-schedule-mode]
      reason: ":125 的 denseK==k 门决定 DENSE 是否参与竞争，直接改变 argmin 的候选集"
    - dims: [D-causal-embedding, D-causal-tail-parity]
      reason: "useLowerCausal:140 与 b 奇偶:150 共同决定 causalRound = pairRound + tailRound"
    - dims: [D-causal-embedding, D-schedule-mode]
      reason: ":142 的 useLowerCausal 是 CAUSAL 参与竞争的前置门"
    - dims: [D-layout, D-headdim-split]
      reason: "layout 与 D_V 共同决定 s1Inner/s1CvRatio，即 :199 的 cubeBase，进而决定 p,q 的量化粒度"
    - dims: [D-schedule-mode, D-headdim-split]
      reason: "cubeBase 变化改变 p,q,m,n 的比例关系，可能翻转三路 argmin"
  L2:
    combinations:
    - dims: [D-token-normalize, D-band-geometry, D-schedule-mode]
      reason: "完整因果链 token 符号 → (p,q) → bandBlocks/几何区间 → 三路 argmin，本次改动的核心路径"
    - dims: [D-entry-route, D-layout, D-headdim-split]
      reason: "入口路由 × layout × headdim 共同决定进选择器的 (m,n) 与 cubeBase，是 tiling 形状面的三元交互"
  L3:
    guards:
    - G-is-deter-off
    - G-rdc-legacy-early-return
    - G-tnd-layout
    - G-all-mask-sparse
    - G-left-up-causal-sparse
    - G-prefix-sparse

oracle:
- id: O-deter-bitwise-reproducible
  kind: reproducibility
  reason: >
    本次改动重排 deterministic 累加的核间顺序但声称逐位结果不变，故每条义务行都必须
    比对 Actual_dq_Md5sum / Actual_dk_Md5sum / Actual_dv_Md5sum 的跨次一致性。
    harness 仅在 is_deter=true 时计算这三列并落盘 dq/dk/dv.bin，恰好覆盖本 plan
    全部义务行，无需额外构造。
- id: O-golden-precision
  kind: precision
  reason: >
    比对 Actual_dq_pricision / Actual_dk_pricision / Actual_dv_pricision 对 golden，
    确认重排调度没有改变数学结果。
- id: O-round-reduction
  kind: performance
  reason: >
    本次改动的性能主张是 round 数下降，用 replay.deterMaxRound 与
    Actual_kernel_time_backward 对基线记账；仅作趋势记录，不设硬阈值。

constraints:
- id: C-group-one-n1
  predicate: {op: eq, field: case.N1, value: 1}
- id: C-group-one-n2
  predicate: {op: eq, field: case.N2, value: 1}

environment:
  aicNum: 8
  coreNum: 16

untestable:
- id: u-dtype-coverage
  kind: control_gap
  reason: >
    deter 累加路径的 dtype 覆盖（fp16/bf16/fp32）本该建成一个 Dimension，但 init.yaml
    的 Dtype 列 confidence: unresolved（仅 status: active，evidence 只有
    test_utils.py:448，未证实到 tensor dtype 的传导链），按 H1 不得进 controls /
    construct_hint。该列 profile 还含脏值「bf16，fp32」（中文逗号，n_unique=4）。
  needs_binding:
  - column: Dtype
    want: >
      confirmed+active，并证实 Dtype -> query/key/value/dy tensor dtype -> tiling
      dtype 分支的完整传导链；同时清理 topk 里的「bf16，fp32」脏值
- id: u-band-mask-entry
  kind: control_gap
  reason: >
    sparse_mode=4（BAND 掩码）是落 DETER_BAND 的第三条入口，构造该行需要
    Atten_mask_shape != NONE，但该列 confidence: unresolved 且 domains profile 为空
    （{}），按 H1 不得进 controls。本轮由 sparse_mode=0 与 sparse_mode=3 两条入口
    承载 D-entry-route。
  needs_binding:
  - column: Atten_mask_shape
    want: >
      confirmed+active，并证实 Atten_mask_shape -> atten_mask tensor 存在性 ->
      SetSparseParams 的 isSparse -> GetDeterSparseTilingKey 的 DETER_BAND 分支

test_harness_gap:
  done: false
  reason: >
    两列 unresolved 挡住两块覆盖：Dtype 挡住 deter 路径的 dtype 维度，
    Atten_mask_shape 挡住 sparse_mode=4 的 BAND 掩码入口。另外 init.yaml 自身有
    provenance 混用问题：defaults 取自 FASG_PSE_cases.csv 而 domains profile 取自
    FASG.xls，导致 Input_Layout / Pre_Tockens / Next_Tockens 等 11 列 profile 为空
    （表内列名为 Layout 等，profiler 未复用 harness 的列别名逻辑），谓词字面量类型
    只能靠 defaults 推断。
  needs_binding:
  - column: Dtype
    want: "confirmed+active，证实到 tensor dtype 的传导链"
  - column: Atten_mask_shape
    want: "confirmed+active，证实到 DETER_BAND 分支的传导链"
  missing_rows:
  - "sparse_mode=4 + Atten_mask_shape=[2048,2048] + is_deter=1 + N1=N2=1，用于覆盖 BAND 掩码入口"
  - "Dtype ∈ {bf16, fp32} × is_deter=1 × sparse_mode=0，用于覆盖 deter 累加路径的非 fp16 dtype"
  alternative_carrier:
  - "host UT 可直接构造 FuzzyBaseInfoParamsRegbase 调 SelectBlockSchedule 并断言 BlockScheduleResult，绕开 case 列绑定；三路 round 比较的边界（denseRound == maxRound、lowerWaste == (bandBlocks-1)/10）更适合放在 host UT 而不是端到端行"
```

<!-- ===================== GRADING RUBRIC (not part of the artifact) =====================

这份 golden 用来给 tg-plan 的 Plan Owner 打分。评分**不做字面 diff**：ID 名、具体
token / S1 / S2 / B / D_V 取值、partition 分档阈值（64 等）、L1 选哪 12 对都允许不同。
只查下面这些语义断言。

必过（任一条不过即 FAIL）:

R1  可达性方向正确且**不过度收紧**：主 Target 的 witness 必须包含 sparse_mode=0 这条
    入口。若 plan 声称 sparse_mode=3 恒不可达、只把它当 Guard，判 PARTIAL 而非 FAIL
    （方向对但漏了入口）；若把 sparse_mode=3 当 witness 却没有同时约束 B 为奇数
    （或 S1 < aicNum*128）来绕过 182-187 的提前返回 ⇒ FAIL。
    依据：rightDownBandCond ⟺ (deterSparseType==DETER_BAND ∧ sparseMode==RIGHT_DOWN_CAUSAL)，
    而 :185 早退还要求 isSplitByBlockIdx 为真，后者含 (b*n2) 偶 ∧ s1>=aicNum*128。

R2  否定项被显式记录：requirement.text 里出现「¬(rightDownBandCond ∧ isSplitByBlockIdx)」
    或等价表述（「提前返回」「保留 legacy」+ 指明它不等于排除 sparse_mode=3），
    表明抽的是**路径条件**而非某分支的正向合取式。

R3  token 门禁没漏：若 witness 用 sparse_mode=0(NO_MASK)，必须约束
    Pre_Tockens/Next_Tockens 使 token 不覆盖全长，否则 GetDeterSparseTilingKey 走
    DETER_DENSE，Target 恒 MISS。partition/constraints 里完全不出现
    Pre_Tockens/Next_Tockens ⇒ FAIL。

R4  没有把 legacy 分支的门当成新行为的前置约束：constraints 里不得出现
    「S1 >= aicNum*128」或「B 为偶数」并声称它们是 deterBandScheduleMode>0 的必要
    条件（它们是 177-180 legacy 那条 isSplitByBlockIdx 的门，对 hybridBandCond 无关，
    且会反过来杀死 sparse_mode=3 入口）。这两条只允许出现在
    G-rdc-legacy-early-return 那类 Guard 里。

R5  环境事实齐：environment 至少含 aicNum 与 coreNum（或等价写出 coreNum==2*aicNum）。
    只写 aicNum ⇒ FAIL，因为 hybridBandCond 有 params.coreNum == params.aicNum * NUM_TWO。

R6  **host 内部门不得写成 opaque**：canSplitByBlockIdx / hybridBandCond / useLowerCausal /
    denseK / bandBlocks / tailRound 都是有 `<name> =` 赋值的 host 局部量，
    coverage/probe.py 的 inject_probes 能自动插 TG_PROBE 并重编。把这组写进
    untestable(kind: opaque) ⇒ FAIL（这是 2026-08-24 那次真实产物的主要失分点：
    误把「不可预测」当成「不可观测」，导致 plan 只剩 4 行）。
    正确做法是让 classifier.requires 引用 probe.<name>。

R7  **三路 mode 必须建成独立 partition**：BAND/DENSE/CAUSAL 三值虽无法从 case 列预测，
    但 replay.deterBandScheduleMode 可回读，必须有一个 Dimension 以该字段为
    classifier、给出 3 个 partition（或至少 2 个）。只写 mode>0 就当多值已覆盖，
    并用 untestable(opaque) 交代「判别做不成」⇒ FAIL。覆盖靠观测，不靠预测。

R8  规模（INFO，不决定 PASS/FAIL）：本次改动判定点多，理想 dimensions≥8、
    partition≥20、L1 非空、L3.guards≥4。低于任一项只记 INFO。
    必过是路径正确 + Solve 能消费（R12）。

R9  oracle 非空且含 md5 逐位复现：本次改动重排累加顺序而声称逐位不变，不验 md5 等于
    没验。harness 仅在 is_deter=true 时算 Actual_dq/dk/dv_Md5sum，与本 plan 义务行
    定义域重合，无额外构造成本。另注意 products.py:603-606 的硬约束 —— 散文正文出现
    「精度」或「md5」而 oracle 为空会直接报错。

R10 两列 unresolved 被正确降级：Dtype 与 Atten_mask_shape 都是
    confidence: unresolved，必须写成 untestable(kind: control_gap) + needs_binding，
    且因它们挡住了 dtype 覆盖与 BAND 掩码入口，应有 test_harness_gap。
    把它们塞进 controls / construct_hint.columns ⇒ FAIL（违反 H1）。

R11 形式合规（H1–H7 与字面量规则）：
    - controls / construct_hint.columns 每列在 init.yaml 里 confirmed + active
      （可用：B N1 N2 S1 S2 D_V Input_Layout Pre_Tockens Next_Tockens sparse_mode is_deter）
    - 每个 Target 被某个 Dimension 的 target 指向（Guard 指向不算）
    - 同一 Dimension 各 partition 谓词引用的字段集合完全相同（H6）
    - 同一条 L1/L2 里各 Dimension 的谓词字段集合不相交（H7）
    - 所有 case.* / replay.* / probe.* 只有两段
    - 每个 Guard 有非空 negate_hint 且谓词根是 case 列
    - is_deter 字面量写 int（profile inferred_type: int），不写 'true'/'false'

加分（不影响 PASS/FAIL）:

B1  为 deterMaxRound 的覆写路径（:691）单独建 Target + Dimension —— 它是既有 TILING_FIELD
    新增覆写路径，容易被整个漏掉。
B2  L2 里给出 token → (p,q) → bandBlocks → argmin 的完整三元因果链。
B3  在 test_harness_gap.alternative_carrier 里指出三路 round 比较的边界条件
    （denseRound == maxRound、lowerWaste == (bandBlocks-1)/10）更适合 host UT 而非端到端行。
B4  指出 init.yaml 自身的 provenance 混用问题（defaults 来自 FASG_PSE_cases.csv、
    domains profile 来自 FASG.xls，导致 11 列 profile 为空），说明谓词字面量类型
    只能靠 defaults 推断。

===================================================================================== -->
