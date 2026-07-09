# Boundary Human Review (retired gate)

**Phase 1.5 已取消。** 本文件仅保留作参考，workflow **不得**再在 Phase 1 后强制 STOP 等待 Boundary Review。

Phase 1（Macro Boundary）完成后应：

1. 写好 `summary/operator_io.yaml` / `operator_boundary.md` / `analysis_plan.yaml` 等
2. 在进度块里用 3–6 行摘要 IO/边界结果（信息性，不等人）
3. **直接进入 Phase 2** 并行 `uo-host-extraction` + `uo-flow-extraction`

人工决策集中在：

- Phase 0.5 Macro Scope（探索范围）
- Phase 3.5 Kernel Dispatch（必须带全量 tiling/family 信息，见 `05a_kernel_dispatch_human_review.md`）

若用户在对话里主动要求修订边界，可临时按旧字段写 `summary/boundary_review.yaml`，但默认流水线不经过此闸门。
