# KB 查询

## Purpose

在已就绪的 KB 上做有界查询，返回可引用节点与缺口。

## Use When

- `/uo-query` 回答问题
- KEY / 合同 / 审查需要 KB 邻接或字段
- TG 绑定缺口分析

## Method

1. 确认 `kb_ready` / `uo_ready`（由 Harness gate 判定）。
2. 按问题类型选择 graph / YAML 查询面（先 graph，再按需展开 YAML）。
3. 记录每个命中的 KB reference。
4. 缺口显式列出，不猜测填补。

## Hard Constraints

- MUST NOT：在未就绪 KB 上宣称答案完整。
- MUST NOT：把候选记忆当定稿 KB。
- MUST：超出只读写面时停止。

## Stop Conditions

- 已回答或已列出充分缺口；工具预算耗尽。
