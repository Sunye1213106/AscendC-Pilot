# Code Review — Gotchas

- **跨层合同优先于本地风格**：Host 改动必须对照 Tiling / Kernel 合同；只看 diff 行不够。
- **影响面用 CodeMap，不是全文搜索**：优先 `impact` / `locate` / `check_sites`；避免把无关文件拉进审查。
- **发现必须有 path:line**：无 span 的“可能有问题”降级或不报。
- **TilingData 来源 ≠ 已校验**：必须能 locate 到 `OP_CHECK_IF` 且变量同一。
- **PR 先有 diff**：没有 change capture 不要假装在做 PR 检视。
- **快速检视不写长报告**：index summary 几行即可。
- **并发与 Buffer 冲突看 tposition + 调用点**：EnQue/DeQue 是 TQue（CANN 封装），看 QUEUE 方向；Set/Wait、CrossCore 看 `flag_paired`。happens-before 不是 UO。
- **CE 审查不改产品 IR**：`/ce-review` 只写 `ce/review/**`；`/ce-verify` 的义务回执才写 `ce/verify/code_review.yaml`。不得修改 `.uo` 或 TG closure 账本。
- **回归建议要对齐 affected keys**：空泛的“加个单测”不如列出受影响 Key / 分支。
