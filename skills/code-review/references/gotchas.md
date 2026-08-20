# Code Review — Gotchas

- **跨层合同优先于本地风格**：Host 改动必须对照 Tiling / Kernel 合同；只看 diff 行不够。
- **最快正确用法**：index 的 Added identifiers → **并行查标识符**。不要把 format hunk 当第一跳（空卡不是文件未索引）。卡片给出 `file:line` 后 **必须** `--file --line`，不要改去 Read 整文件。
- **snippet 截断不得下「枚举未用」**：截断 + 未覆盖 WRITES 行时继续查字段卡 `write_sites` / readers。
- **Kernel 以字段 readers 行为准**：不要把 `kernel_call_boundary` 调用点当成定义。
- **每个 changed file**：finding / format-only / UNREVIEWED。未审 `op_kernel` 禁止「无 high/medium」。
- **UT 不在图里**：只读 `tests/**` 搜新字段名；`--file --line` 打 test 文件空是预期。
- **影响面用 uo-query，不是全文搜索**：形态见 code-access 不变量。
- **发现必须有 path:line**：无 span 的“可能有问题”降级或不报。
- **TilingData 来源 ≠ 已校验**：必须能 locate 到 `OP_CHECK_IF` 且变量同一。
- **PR 先有 diff**：没有可审查的代码改动则停。
- **快速检视不写长报告**：结论留在对话。
- **并发与 Buffer 冲突看 tposition + 调用点**：EnQue/DeQue 是 TQue（CANN 封装），看 QUEUE 方向；Set/Wait、CrossCore 看 `flag_paired`。happens-before 不是 UO。
- **CE 审查不落盘**：禁止 Write `ce/**`。不得修改 `.uo`。
- **建议测试走 /tg-plan**：TG 自己从计划 md 或审查对话总结义务。
- **收齐两轴后合并**：用字段卡裁定矛盾，写 `parts/merged.md`；禁止再派相同 spec/standards。
