# 由账本重建派生图

## Goal

源码抽取事实 + `semantic_resolution_ledger` → 确定性重建 entrypoint_graph / bridge / operator_graph。过期 snapshot 的 patch 标记 stale。

## Output

- 合同 id：`rebuild-ledger-v1`
- 更新 `ir/entrypoint_graph.yaml`、`ir/operator_graph.yaml`
