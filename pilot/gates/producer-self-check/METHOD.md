# Producer 自检

## Purpose

提交前自检本 shard：覆盖完整、无越权 id、无空 candidate_id。

## Method

1. `pilot_cli` `inspect validate --what extract-plan-staging --project <算子绝对路径>`（或对应 Action）。
2. 结果写入 `scratch/{shard_id}/self_check.yaml`。
3. 失败则修本 part，禁止改其他 shard。

## Hard Constraints

- MUST NOT：用自检结果代替 Gate。
- MUST NOT：为通过自检而改正式 IR。
