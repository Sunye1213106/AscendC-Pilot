# Rule Model

规则从 KB 编译，语义对齐 ST 约束模型（见 `references/constraint-types.md`）。

## 编译来源

| 来源 | 产出规则类型 |
|---|---|
| `key_space.constants` | `constant` |
| `key_space.legal_constraints` | `legal` (if-then / forbid) |
| `key_space.unreachable` | `reachability` |
| `families.*.guard/reachability` | `family_guard` / `reachability` |
| `data_model.structs.present_when` | `tilingdata_present` |
| `data_model.numeric_overlay` | `numeric_overlay` |
| `key_space.input_realization` | realization map（非 prune 规则，供 realize） |

## 执行顺序（prune）

```text
1. inject constants
2. reject legal conflicts
3. reject unreachable hits
4. apply/check family_guard（仅校验已出现字段；缺失 guard 字段可回填）
5. check input_realization 可实现性（缺失 → review suggestion，不直接当事实）
```

## 示例

```yaml
constraints:
  - id: C-LEGAL-001
    type: legal
    if: {IsTndSwizzle: 1}
    then: {IsTnd: 1, DeterType: 0, SplitAxis: 5}
    forbid: {deterministic: true}

  - id: C-LEGAL-002
    type: legal
    if: {IsBn2MultiBlk: 1}
    then: {SplitAxis: 1, IsRope: 0}

  - id: C-OVERLAY-VARLEN
    type: numeric_overlay
    if: {has_varlen: true}
    then:
      actualSeqQLen.exist: true
      actualSeqKvLen.exist: true
    note: "has_varlen does not create a dedicated tiling_key bit"
```

## LLM 边界

- 可建议缺失 rule → `review/rule_patch_suggestion.yaml`
- 不可直接改 `coverage_audit.yaml`
- 不可把 expected 当 observed
