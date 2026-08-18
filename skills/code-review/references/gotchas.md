# Code Review — Gotchas

- **跨层合同优先于本地风格**：Host 改动必须对照 Tiling / Kernel 合同；只看 diff 行不够。
- **影响面用 uo-query，不是全文搜索**：标识符 / `--file --line`；禁止 `acp uo impact` / `explain-*`。
- **发现必须有 path:line**：无 span 的“可能有问题”降级或不报。
- **TilingData 来源 ≠ 已校验**：必须能 locate 到 `OP_CHECK_IF` 且变量同一。
- **PR 先有 diff**：没有可审查的代码改动则停。
- **快速检视不写长报告**：结论留在对话。
- **并发与 Buffer 冲突看 tposition + 调用点**：EnQue/DeQue 是 TQue（CANN 封装），看 QUEUE 方向；Set/Wait、CrossCore 看 `flag_paired`。happens-before 不是 UO。
- **CE 审查不落盘**：禁止 Write `ce/**`。不得修改 `.uo`。
- **建议测试走 /tg-plan**：TG 自己从计划 md 或审查对话总结义务。
