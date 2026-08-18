# 结构化 IR 查询

## Purpose

用受控 `pilot_cli inspect` 查询当前 run 的 tasks / YAML 计数 / 重复项 / 证据窗口，禁止靠整文件手工扫 id。

## Method

1. 优先 `pilot_cli` `inspect tasks|yaml|duplicates|evidence-window --project <算子绝对路径>`。
2. `tasks` 枚举 `llm_tasks.yaml` 的 task_id；`yaml` 对指定相对路径做键计数；`duplicates` 查重复 target；源码窗用 `evidence-window --path <rel> --lines A-B`。
3. 结果留在命令 stdout，不进正式 IR。

已删除的 `extract_plan` / `adjudicate` / `candidates` / `extract-plan-*` inspect 子命令不得再调用。

## Hard Constraints

- MUST NOT：用 Grep/offset-hunt 代替 inspect 枚举全量 task id。
- MUST NOT：把 inspect 输出当高置信源码证据。
