# 编排易错

- 不要 `pilot_run(workflow=auto)` 再理解一遍用户原文。对照 `slash-io.md` 选当前缺的那一步。
- 不要无 diff 就 `/uo-update`，也不要已有 `.uo` 还 `/uo-init`。
- 不要把 `/uo-query` 交给 `pilot_run`。
- 不要为自己扫本地仓猜算子、git 猜 PR、从 unresolved 反推 diff。问变更影响 = 带着 diff 做 `/uo-query`。
- `/tg-init` 先问脚本仓。没有仓时按输入 API 设计控制面，不要假装已有脚本仓。
- 专家 slash 只跑该节点；NL 才沿图补前置。
- 不要发明图上没有的工作流 id。
