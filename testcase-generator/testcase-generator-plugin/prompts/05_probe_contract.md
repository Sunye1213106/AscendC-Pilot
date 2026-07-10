# Probe Contract

Input: `generate/probe_cases.jsonl`

Output:

- `probe/probe_results.jsonl`
- `probe/observed_keys.jsonl`

Each observed row:

```json
{
  "case_id": "TK_001",
  "status": "success",
  "tiling_key": 123456,
  "decoded_key": {},
  "family_guess": "TF002",
  "mock_probe": true,
  "coverage_verified": false
}
```

Backends:

- `MockTilingProbe` — MVP; echoes expected_key
- `ExternalTilingProbe` — reserved for UO_TILING_PROBE host dry-run

Future: macro at SetTilingKey/GetTilingKey with `-DUO_TILING_PROBE`.
