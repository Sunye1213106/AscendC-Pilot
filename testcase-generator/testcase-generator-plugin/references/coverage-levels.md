# Coverage Levels (L0 / L1 / L2)

对齐 `ascendc-st-design` 的级别语义，但覆盖对象是 **tiling_key / family / tilingdata**。

| 级别 | 定义 | 覆盖目标 | 候选来源 | 规模建议 |
| ---- | ---- | -------- | -------- | -------- |
| L0 | 门槛用例 | 核心 family + seed + 关键单字段直通 | `seed_cases` + 每 family 1 条代表 + 关键 field 单值 | ≤ 家族数×2 + seed |
| L1 | 功能组合用例 | obligation 全覆盖 + 关键 key field pairwise | targeted obligations + pairwise | 由 set cover 压缩 |
| L2 | 异常 / 不可达证明 | illegal / unreachable / 负例 | unreachable + legal 违反的负例（仅文档化或 dry-run 期望失败） | ≤ 20 |

## L0 细则

必须覆盖：

1. 每个 `reachability=reachable*` family 至少 1 条代表 case
2. `coverage_model.seed_cases` 全部纳入（representative / boundary / risk / manual_keep）
3. 高风险单字段：`DeterType`、`IsTnd`、`has_varlen` 等（若存在于 key_space）

禁止：

- 全量笛卡尔积
- 把 L0 当完整 tilingkey 枚举

## L1 细则

必须覆盖：

1. `family_obligations`（可达）
2. `key_field_obligations` 每个 field-value
3. `key_relation_obligations` 每个组合
4. `tilingdata_obligations` 每个 block
5. 关键字段 pairwise（默认 top-N 字段，受 family guard 局部化）

算法：

```text
targeted candidates
  -> optional pairwise within family-local domains
  -> prune by rule_model
  -> greedy set cover
  -> realize inputs
```

## L2 细则

L2 **不是** pairwise。L2 是异常/不可达：

1. `key_space.unreachable` 约束证明
2. `families` 中 `unreachable|excluded` 的证明记录
3. 故意违反 `legal_constraints` 的负例（标记 `expect_reject: true`，不计入正向覆盖）

审计：

- L2 正向覆盖不要求 observed success
- `unreachable_proof` 以 KB 声明 + 无成功 observed 命中为准

## CLI

```bash
tg-generate --level L0
tg-generate --level L0,L1
tg-generate --level L0,L1,L2
```

默认：`L0,L1`。
