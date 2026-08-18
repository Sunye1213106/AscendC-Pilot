# 主控选下一步

读 `references/slash-io.md` 与 `references/product-pipelines.md`。看当前磁盘产物，缺哪项输入就跑那个上游 slash。

## 显式 slash

用户打了 `/uo-init` … `/handoff`：只 `pilot_run(workflow=该 id)`。不要改写成别的 slash，也不要串联。

## 自然语言

1. 点亮交付节点。黄金句「分析这个 PR 并生成对应测试用例」→ `/ce-review` + `/tg-plan` + `/tg-solve`。只要生成 case、没说 review → 不要加 `/ce-review`。
2. 对照 I/O 补当前缺的一步：无 `.uo` → `/uo-init`；有 `.uo` 且有 diff → `/uo-update`；要 TG 但无 `init.yaml` → 先问脚本仓再 `/tg-init`。
3. 一次只 `pilot_run` 一个非 query 节点。该步结束后再看图。
4. 语义问题一律 `/uo-query`（`pilot_cli` 或 Task）。
5. `/tg-init` 前 AskQuestion：有没有测试脚本仓。

## 禁止

- 离开本图手串 slash 或发明 id
- 第二轮意图 LLM / `workflow=auto` 解析原文
- Grep 算子仓代替 query
