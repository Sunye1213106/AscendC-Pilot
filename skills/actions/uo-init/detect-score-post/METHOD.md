# 抽取后评分 (extract.post_semantic)

## Goal

在 extract_plan / host / kernel 已存在后，对 TilingData bridge、TilingKey binding、provenance 评分。

## Domain Procedure

1. Pilot `run-action detect_score_post`。
2. 若缺 plan/host 产物则失败（禁止与 pre_semantic 循环依赖）。
3. 不得递增 semantic attempts。

## Output

- 合同 id：`detect-score-post-v1`
- `ir/score_report_post.yaml`、更新 `ir/llm_tasks.yaml`
