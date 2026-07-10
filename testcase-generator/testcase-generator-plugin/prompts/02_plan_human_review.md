# Plan Human Review

After `tg-plan`, present summary and STOP.

## 摘要必须包含

- obligation 计数：family / key_field_value / key_relation / tilingdata / unreachable_proof
- 建议默认 level：`L0,L1`
- 提醒：family ≠ tiling_key；L2 是异常不是 pairwise

## 选项

- `approve` — 继续 tg-generate（默认 `--level L0,L1`）
- `approve_with_extra_constraints` — 用户追加约束后可重跑 tg-plan 或直接带约束进 generate
- `add_obligation` — 手工追加 obligation 后校验
- `remove_obligation` — 删除后校验
- `stop` — 结束

未批准前不要 generate（除非用户明确 skip review）。
