# KB 查询

## Purpose

在已 commit 的 `.uo` CodeMap 上做有界查询，返回可引用节点与缺口。

## Use When

- `/uo-query` 回答问题
- KEY / 合同 / 审查需要邻接、字段或约束
- TG 绑定缺口分析

## Method

1. 确认 `kb_ready` / `uo_ready`（由 Pilot gate 判定）。没有 `.uo` 则停止，先 `/uo-init`。
2. 用 `acp uo-query --project <op> --mode <mode> --pattern <needle>`（或本能力脚本 `uo_kb_query.py`，它只转发到该 CLI）。
3. 按问题选 mode（`locate` / `field` / `tiling_key` / `neighbors` / `constraints` / `kernel_api` / …），先查图再开最小源码窗。
4. 记录每个命中的 CodeMap reference。缺口显式列出，不猜测填补。

## Hard Constraints

- MUST NOT：在未就绪产品上宣称答案完整。
- MUST NOT：把候选记忆、分层 YAML、`kb_graph.sqlite` 当定稿权威。
- MUST：超出只读写面时停止。

## Stop Conditions

- 已回答或已列出充分缺口；工具预算耗尽。
