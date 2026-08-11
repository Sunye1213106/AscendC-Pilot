# 结构化 IR 查询

## Purpose

用受控 `acp inspect` 查询 candidates / llm_tasks / YAML，禁止靠整文件手工扫 task_id。

## Method

1. 优先 `acp inspect candidates|tasks|yaml|duplicates|extract-plan-worklist|extract-plan-coverage`。
2. 覆盖检查用 `acp inspect validate --what extract-plan-staging`（或 `extract_plan`）。
3. 结果可写入 action scratch，不进正式 IR。

## Hard Constraints

- MUST NOT：用 Grep/offset-hunt 代替 inspect 枚举全量 task/candidate id。
- MUST NOT：把 inspect 输出当高置信源码证据。
