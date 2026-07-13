# 默认语言：中文（强制）

`understand-operator` / 全部 `/uo-*` 命令的**默认用户可见语言为中文（zh-CN）**。

## 必须用中文

- TodoWrite 任务标题（content）
- **闸门**对话进度块、阶段说明、STOP / 闸门提示、人工审阅摘要与菜单说明
- `/uo-query` 对用户的回答正文（引用段标题可用「引用 / KB / 源码核实 / 置信度」）
- `workflow_progress.yaml` 的 `notes` 与 todo `title` 字段
- 错误提示、下一步建议

非闸门 phase 默认不向对话倾倒审阅式长文；需要中文时也只保留极简状态（或仅 TodoWrite）。

## 允许保留英文

- 文件路径、符号名、API、宏、tiling_key 字段名
- todo id（`uo-p0`）、family_id（`TF007`）、task_id
- MCP 工具名（`search_graph`）、YAML key 名
- 源码引用行（`file:line`）

## 禁止

- 默认用英文写 todo / 进度 / 审阅摘要
- 「仅当用户要求中文时才用中文」——中文是默认，不是可选
- 中英混排的整句进度标题（如 `Phase 0 — Preflight and CBM`）

技术文档（README 英文段落、schema 字段名）可保留英文；**面向用户的 agent 输出一律中文。**
