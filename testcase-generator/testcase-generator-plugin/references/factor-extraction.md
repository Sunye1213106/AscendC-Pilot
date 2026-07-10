# Factor Extraction

对齐 ST「从参数定义提取测试因子」，但因子来自 understand KB，不是 aclnn 文档。

## 因子来源优先级

1. `tiling/key_space.yaml` → tiling_key fields / domain / bits / constants / derived
2. `tiling/families.yaml` → family_id、guard、reachability、struct_signature
3. `tiling/data_model.yaml` → tilingdata structs、present_when、numeric_overlay、varlen
4. `operator.yaml` io → required/optional inputs、outputs、attrs、dtype/shape/layout hints
5. `tiling/coverage_model.yaml` → obligations（覆盖目标，不是因子域本身）

## factor_space.yaml schema

```yaml
version: 1
op_name: ""

# ST-like factor catalog
factors:
  key:
    SplitAxis:
      kind: tiling_key_field
      type: enum
      domain: [0, 1, 2]
      bits: [0, 1, 2]
      io_impact: [shape_split]
    InputDType:
      kind: tiling_key_field
      type: enum
      domain: [0, 1, 2]
      bits: [3, 4]
      io_impact: [query.dtype, key.dtype, value.dtype]
  family:
    TF001:
      kind: family
      reachability: reachable
      guard: {IsTnd: 0}
  tilingdata:
    BaseParams:
      kind: tilingdata_block
      present_when: {IsTnd: 0}
  io:
    query:
      kind: tensor
      required: true
      dtype_domain: [float16, bfloat16]

solver:
  strategy: topological
  anchors: []          # 入度 0 的 key fields / attrs
  derivation_order: {} # level_0 / level_1 ...

family_guards: {}
constants: {}
input_realization: {}
```

## 提取规则

### tiling_key field

- `domain` 缺失 → 尝试从 bits 宽度推断 `0..(2^w-1)`，否则标 `unknown`
- `constant` 字段不进 pairwise
- `derived_from` 字段不作为 anchor

### family

- 每个 family 成为一个离散因子 `family_id`
- `unreachable|excluded` 只进 L2 / unreachable_proof，不进 L0/L1 正向采样

### tilingdata

- `present_when` → existential 因子
- `numeric_overlay`（如 has_varlen）→ 额外覆盖点，**不是**伪造的 tiling_key bit

### operator_io

- required → `exist: true`
- optional → `exist: [true, false]`（由 key 字段驱动，如 IsPse）
- output 不生成输入采样域

## 与 ST generate_test_factors 的差异

| ST | TG |
|---|---|
| 从 `03_参数定义.yaml` 自动抽 | 从 KB snapshot 抽 |
| 因子含 value_range / special_value | 因子含 bits / family guard / tilingdata |
| 面向 CSV ST | 面向 tilingkey probe |

## 禁止

- 不要把 archive/branch_matrix 当因子全量枚举
- 不要把 family 数当成 tiling_key 覆盖完成
- 不要 LLM 手填 domain；缺失则标 unknown 并写入 review suggestion
