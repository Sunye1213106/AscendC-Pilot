# Constraint Types (Rule Model)

对齐 ST `dependency-yaml-spec` 的约束分层，映射到 tiling 域。

## 约束优先级（分析顺序）

1. **常量 / 编码约束**：`constants`、固定 bits
2. **类型 / dtype 依赖**：`InputDType` ↔ query/key/value dtype
3. **布局 / 存在性依赖**：`IsTnd`/`IsPse`/`IsAttenMask`/`has_varlen`
4. **数值 / 枚举依赖**：`DeterType`、`SplitAxis`、template num
5. **Family guard / reachability**
6. **Tilingdata present_when / numeric_overlay**
7. **Unreachable / illegal**

## TG 约束类型

| type | 语义 | 来源 | ST 类比 |
|---|---|---|---|
| `constant` | 字段必须等于常量 | `key_space.constants` | 固定枚举（因子域，非动态约束） |
| `legal` | if-then / forbid | `key_space.legal_constraints` | `conditional` |
| `family_guard` | family 可达前提 | `families.*.guard` | `conditional` + reachability |
| `reachability` | unreachable/excluded | `families` / `unreachable` | L2 / 负例 |
| `tilingdata_present` | struct 出现条件 | `data_model.structs.present_when` | `existential` |
| `numeric_overlay` | 同 key 不同 numeric | `data_model.numeric_overlay` | 额外覆盖点 |
| `input_realization` | key→真实输入映射 | `key_space.input_realization` | 参数定义 + calculate |
| `pairwise_scope` | 组合范围限制 | family-local domains | L1 BC 范围 |

## rule_model.yaml schema

```yaml
version: 1
op_name: ""
metadata:
  source: kb_snapshot
  constraint_priority:
    - constant
    - legal
    - family_guard
    - reachability
    - tilingdata_present
    - numeric_overlay

constants: {}
input_realization: {}

factors:
  # ST-like factor nodes
  SplitAxis: {type: enum, domain: [0,1,2], bits: [0,1,2]}
  IsTnd: {type: enum, domain: [0,1], bits: [7]}

constraints:
  - id: C-LEGAL-001
    type: legal
    if: {IsTnd: 1}
    then: {DeterType: 0}
    description: "TND requires DeterType=0"

  - id: C-GUARD-TF002
    type: family_guard
    family_id: TF002
    if: {IsTnd: 1}
    then: {family_id: TF002}

  - id: C-UNR-001
    type: reachability
    if: {SplitAxis: 7}
    forbid: true
    description: "SplitAxis=7 unused"

  - id: C-TD-TndParam
    type: tilingdata_present
    if: {IsTnd: 1}
    then: {TndParam.exist: true}
```

## 设计原则（来自 ST）

1. **可计算**：规则由 Python prune 执行，不靠 LLM 判断
2. **静态域不写约束**：domain 已在 factor_space，不必再写 “SplitAxis∈{0,1,2}” 约束
3. **sources 不可空**：若表达自引用，if/then 必须含具体字段
4. **legal 是单向 if-then**；family_guard 是可达前提，勿混为一谈
5. **拒绝候选必须带 reason**

## 检查清单

- [ ] constants 已注入 expected_key
- [ ] legal if-then 冲突会 reject
- [ ] unreachable family 不进正向 L0/L1
- [ ] tilingdata present_when 已编译
- [ ] input_realization 缺失只写 `review/` suggestion，不伪造事实
