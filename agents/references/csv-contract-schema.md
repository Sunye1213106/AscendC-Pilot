# tg-csv-contract — lexicon schema 与 atom 表

路径：`$PLUGIN_ROOT/agents/references/csv-contract-schema.md`

## Primary: `binding_lexicon.yaml`

```yaml
version: 1
source: llm
key_tokens:
  IS_FOO: {var: VAR_KEY_FOO, true_value: 1}
csv_field_aliases:
  this.constinfo.bar: {column: bar, value: 1}
arith_constants:
  NUM_TWO: 2
key_derivations:
  - id: VAR_KEY_FOO
    type: int
    domain: [0, 1]
    expr: {op: if_then_else, condition: {op: eq, var: VAR_CSV_SomeColumn, value: "X"}, then: 1, else: 0}
    rationale: ...
    # proposed 允许 medium；进入 merge 真值 / status=resolved|confirmed 时 MUST high
    confidence: high | medium
    locked: false
    status: proposed   # proposed | reviewed | confirmed | locked | unresolved
    source_refs: [{path: ..., line: ...}]
warnings: []
```

### confidence 规则

| status | confidence |
|--------|------------|
| `proposed` | 允许 `high` 或 `medium`（供人审） |
| `confirmed` / merge 后可执行真值 | **仅** `high` |
| `resolved`（uo_query_resolve） | **仅** `high` |

禁止用 medium/low 冒充 resolved 进 `--merge-uo-resolve`。

## Atom resolvability

| llm_plus_source | 原因码 | 动作 |
|---|---|---|
| likely | UNBOUND_ATOM / UNBOUND_CMP / UNBOUND_DTYPE / UNBOUND_CALL / SUBSTITUTE_FAIL | 查源码补 lexicon + atom_bindings |
| partial | PARSE_FAIL / UNBOUND_TEMPLATE / UNBOUND_KVAR / BRANCH_SIDE_NOT_IN_IMAGE | 有证据才补 |
| unlikely | NO_HOST_PRODUCER | 通常不补 |
| impossible | LOOP_LOCAL / PLATFORM_MACRO | **禁止绑定** |

分支：`abstract_branches[].unbound_atoms` 全 bound 后移入 `branch_mappings`。
