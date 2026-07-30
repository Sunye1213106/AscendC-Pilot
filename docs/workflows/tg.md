# TG 工作流

`/tg-init` → `/tg-plan` → `/tg-solve` 消费 UO 分层 KB（`uo_init` 产物），不依赖旧 `uo.scripts`。

入口包：`engines/testcase-generation`（`testcase_agent`）。  
就绪门禁：`gate_uo_ready`（新契约）。
