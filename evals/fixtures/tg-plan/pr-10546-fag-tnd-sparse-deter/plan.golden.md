## 测什么

PR 10546 让 TND + `g==1` 的确定性计算在 `sparse_mode∈{2,3,4}` 走上新的 host 参数与 kernel index 路径。Golden 正文由引擎 narrate；下面 YAML 是 Coverage IR。

```yaml
schema: tg-plan/v3
requirement:
  id: R-tnd-sparse-deter
  text: >
    新增 CalcleTNDSparseDeterParam（tiling_varlen_regbase.cpp），在
    CalcleTNDDeterParam 里当 g==1 且 sparseMode∈{LEFT_UP_CAUSAL,
    RIGHT_DOWN_CAUSAL, BAND} 且 deterSparseType∈{DETER_CAUSAL, DETER_BAND}
    时调用并 return，跳过旧 CalcleTNDDense/Causal/Band。
    GetDeterSparseTilingKey 对 RIGHT_DOWN_CAUSAL 在
    (isS1S2Same || (layout==TND && g==1)) 时返回 DETER_CAUSAL，因此 TND∧g==1
    即使 ¬isS1S2Same 也不再掉进 DETER_BAND。
    Kernel CalTNDCausalIndex 增加 sparseMode 形参：RIGHT_DOWN_CAUSAL 走
    CalTNDRightDownIndex，否则 CalTNDLeftUpIndex；
    flash_attention_score_grad_kernel_deter.h 传入 constInfo.sparseMode。
    deterMaxRound / deterPrefix* 仅新增写入路径，有兄弟写点，Target 观测
    本次 helper 的 rLine。
    路径条件：is_deter==1 ∧ layout==TND ∧ g==1 ∧ sparse_mode∈{2,3,4}
    ∧ deterSparseType∈{DETER_CAUSAL, DETER_BAND}。
    否定项：is_deter==0 不进确定性；非 TND 在 CalcleTNDDeterParam 早退；
    g>1 走旧 GQA 路径；sm∉{2,3,4} 不进新 helper。

targets:
  - id: T-tnd-sparse-deter-param
    evidence:
      kind: derived
      predicate: {op: ge, field: probe.rLine, value: 0}

dimensions:
  - id: D-sparse-mode
    target: T-tnd-sparse-deter-param
    controls: [sparse_mode]
    classifier: {requires: [case.sparse_mode]}
    partitions:
      - {id: p-sm-left-up, predicate: {op: eq, field: case.sparse_mode, value: 2}}
      - {id: p-sm-right-down, predicate: {op: eq, field: case.sparse_mode, value: 3}}
      - {id: p-sm-band, predicate: {op: eq, field: case.sparse_mode, value: 4}}

  - id: D-seq-equal
    target: T-tnd-sparse-deter-param
    controls: [seqlens_list_q, seqlens_list_kv]
    classifier: {requires: [case.seqlens_list_q, case.seqlens_list_kv]}
    partitions:
      - id: p-s1s2-same
        predicate:
          op: and
          args:
            - {op: eq, field: case.seqlens_list_q, value: "[256,256]"}
            - {op: eq, field: case.seqlens_list_kv, value: "[256,256]"}
      - id: p-s1s2-diff
        predicate:
          op: and
          args:
            - {op: eq, field: case.seqlens_list_q, value: "[128,256]"}
            - {op: eq, field: case.seqlens_list_kv, value: "[256,128]"}

  - id: D-n2-parity
    target: T-tnd-sparse-deter-param
    controls: [N2]
    classifier: {requires: [case.N2]}
    partitions:
      - {id: p-n2-even, predicate: {op: mod_eq, left: case.N2, divisor: 2, value: 0}}
      - {id: p-n2-odd, predicate: {op: mod_eq, left: case.N2, divisor: 2, value: 1}}

  - id: D-is-small
    target: T-tnd-sparse-deter-param
    controls: [S1, S2]
    classifier: {requires: [probe.isSmall]}
    partitions:
      - {id: p-small, predicate: {op: eq, field: probe.isSmall, value: 1}}
      - {id: p-not-small, predicate: {op: eq, field: probe.isSmall, value: 0}}

  - id: D-use-line
    target: T-tnd-sparse-deter-param
    controls: [S1, S2]
    classifier: {requires: [probe.useLine]}
    partitions:
      - {id: p-line, predicate: {op: eq, field: probe.useLine, value: 1}}
      - {id: p-cols, predicate: {op: eq, field: probe.useLine, value: 0}}

  - id: D-run-kind
    target: T-tnd-sparse-deter-param
    controls: [sparse_mode]
    classifier: {requires: [probe.shapeKind]}
    partitions:
      - {id: p-kind-causal, predicate: {op: in, field: probe.shapeKind, values: [2, 3]}}
      - {id: p-kind-band, predicate: {op: in, field: probe.shapeKind, values: [4, 43]}}

guards:
  - id: G-is-deter-off
    target: T-tnd-sparse-deter-param
    controls: [is_deter]
    predicate: {op: eq, field: case.is_deter, value: 0}
    negate_hint: {is_deter: 1}
  - id: G-layout-not-tnd
    target: T-tnd-sparse-deter-param
    controls: [Input_Layout]
    predicate: {op: ne, field: case.Input_Layout, value: TND}
    negate_hint: {Input_Layout: TND}
  - id: G-g-gt1
    target: T-tnd-sparse-deter-param
    controls: [N1, N2]
    predicate:
      op: and
      args:
        - {op: eq, field: case.N1, value: 8}
        - {op: eq, field: case.N2, value: 2}
    negate_hint: {N1: 1, N2: 1}
  - id: G-sparse-not-234
    target: T-tnd-sparse-deter-param
    controls: [sparse_mode]
    predicate: {op: in, field: case.sparse_mode, values: [0, 1, 5]}
    negate_hint: {sparse_mode: 2}

coverage:
  L0:
    dimensions: [D-sparse-mode, D-seq-equal, D-n2-parity, D-is-small, D-use-line, D-run-kind]
  L1:
    combinations:
      - {dims: [D-sparse-mode, D-seq-equal], reason: "sm=3 的 DETER_CAUSAL 放宽依赖 TND∧g==1，与 isS1S2Same 解耦"}
      - {dims: [D-sparse-mode, D-n2-parity], reason: "n2 奇偶决定 pairCount / runHasSingle，因果与 BAND 公式都读它"}
      - {dims: [D-seq-equal, D-n2-parity], reason: "run-shape 与 pair 切分独立"}
      - {dims: [D-n2-parity, D-is-small], reason: "奇偶决定 single 路径，isSmall 决定是否进 pool"}
  L2:
    mode: full_cross
    exclusions:
      - partitions: {D-sparse-mode: p-sm-left-up, D-run-kind: p-kind-band}
        reason: "LEFT_UP_CAUSAL 的 MakeTNDCausalRunShape.kind 为 2，走不到 BAND kind 4/43"
      - partitions: {D-sparse-mode: p-sm-right-down, D-run-kind: p-kind-band}
        reason: "RIGHT_DOWN_CAUSAL 的 kind 为 3，不是 BAND"
      - partitions: {D-sparse-mode: p-sm-band, D-run-kind: p-kind-causal}
        reason: "BAND 走 MakeTNDBandRunShape.kind 4 或 43，不是 causal 2/3"
      - partitions: {D-is-small: p-small, D-use-line: p-line}
        reason: "ClassifyTNDPairCols 在 isSmall 时不会再走 useLine 分列路径"

  L3:
    guards: [G-is-deter-off, G-layout-not-tnd, G-g-gt1, G-sparse-not-234]

oracle:
  - id: O-tnd-sparse-md5
    kind: md5
    fields: [Actual_dq_Md5sum, Actual_dk_Md5sum, Actual_dv_Md5sum]
    reason: 新 index 重排累加顺序但声称逐位不变。
  - id: O-golden-precision
    kind: precision
    fields: [Actual_dq_pricision, Actual_dk_pricision, Actual_dv_pricision]
    reason: 比对 golden。

constraints: []

environment:
  aicNum: 32
  coreNum: 64

untestable:
  - id: u-Dtype
    kind: control_gap
    reason: Dtype unresolved，不进 controls。
    needs_binding:
      - {column: Dtype, want: "confirmed+active"}
  - id: u-Atten_mask_shape
    kind: control_gap
    reason: Atten_mask_shape unresolved；sm=4 构造可能需要 mask，本轮由 token/sparse 列承载。
    needs_binding:
      - {column: Atten_mask_shape, want: "confirmed+active"}
```
