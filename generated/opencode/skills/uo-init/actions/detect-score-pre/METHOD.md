# 抽取前评分 (extract.pre_semantic)

## Goal

对 entrypoint / registration / operator boundary 做分对象评分，写出 `score_report_pre` 与 `llm_tasks`。禁止评 Bridge（须等 plan_and_graph）。

## Domain Procedure

1. 由 Pilot `run-action detect_score_pre` 调用确定性引擎。
2. 引擎先跑 entrypoints 层：写出 `ir/entrypoint_graph.yaml`（+ 尽量写 `operator_boundary.yaml`）。
3. 再对图中节点/边与 boundary 做分对象评分。
4. 不得自行 advance 阶段。

## Output

- 合同 id：`detect-score-pre-v1`
- `ir/entrypoint_graph.yaml`、`ir/score_report_pre.yaml`、`ir/llm_tasks.yaml`

## Stop Conditions

- 评分完成；blocking 任务已入账待 resolve。
