# worklog 签发

**何时加载**：`solve_certify` 前。

签发前检查：

1. `worklog.md` 文首 `open: []`
2. cases 表存在且脚本可吃
3. replay 义务有 Host tiling 证据；derived 义务有公式代入
4. 没有把 `Replay reject` 写成不可达 `E`
5. `harness_intent` 已落地（否则根本进不了 solve）

Agent 不得自行宣布 PASS。gate `worklog_closed` 由 Host 判定。
