# Tilingkey Coverage Rules

1. **Family coverage ≠ tiling_key coverage**
2. **seed_cases 只是代表样本，不是全量枚举**
3. **expected_key 是目标；observed_key 是证据**
4. **mock probe => verified=false / coverage_verified=false**
5. 不要读 `tiling/archive/` 或 legacy branch_matrix 做全量枚举
6. **L0/L1/L2 语义对齐 ST**：
   - L0 = 门槛（seed + family 代表 + 关键单字段）
   - L1 = 功能组合（obligations + pairwise）
   - L2 = 异常/不可达证明（**不是** pairwise）
7. 先按 family guard 限制局部空间，再 targeted / pairwise；禁止全输入笛卡尔积
8. 覆盖审计只统计 `observed_keys.jsonl`

详见 `references/coverage-levels.md`。
