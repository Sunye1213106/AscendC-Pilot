# P2 KB chain break

- gate_pass: True
- blocking_count: 0
- legal_instances: 8705
- encode_sample_ok: 50/50

| id | severity | script_fixable | detail |
|----|----------|-----------------|--------|
| (none) | | | |

根因：此前 assemble/export 未 materialize KEY/template_blocks/coverage → 空壳 extracted。
修复手段：script（materialize_tiling + kb_export 契约视图）。
验证：`python scripts/uo_tg_rebuild_and_probe.py` → chain_break_report.yaml
结果：gate_pass=True
