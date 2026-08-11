# Code Review — Gotchas

- **跨层合同优先于本地风格**：Host 改动必须对照 Tiling / Kernel 合同；只看 diff 行不够。
- **影响面用 CodeMap，不是全文搜索**：优先 `impact_of` / entities_in_files；避免把无关文件拉进审查。
- **发现必须有源码证据**：无 span / 无 KB 节点的“可能有问题”降级或不报。
- **并发与 Buffer 冲突看流水**：EnQue/DeQue、double buffer 冲突不能只靠命名判断。
- **CE 审查不改产品 IR**：只写 `ce/review/**`；不得修改 `.uo` 或 TG closure 账本。
- **回归建议要对齐 affected keys**：空泛的“加个单测”不如列出受影响 Key / 分支。
