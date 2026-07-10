# Audit Contract

Inputs:

- `plan/coverage_obligations.yaml`
- `generate/realized_cases.yaml`
- `probe/observed_keys.jsonl`

Outputs:

- `audit/coverage_audit.yaml`
- `audit/coverage_matrix.md`

Summary fields:

```yaml
summary:
  verified: true | false
  mock_probe: true | false
  family_coverage: ""
  key_field_value_coverage: ""
  key_relation_coverage: ""
  tilingdata_coverage: ""
  expected_observed_match_rate: ""
```

Only `observed_key` counts toward coverage. `expected_key` mismatch goes to `mismatches` only.
