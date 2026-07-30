# /uo-update

增量刷新已有 UO KB（新分层契约）。

## 阶段

detect → plan → apply → resolve → export（或 diff_only → diff）

## 引擎

| Action | 入口 |
|--------|------|
| detect_changes / plan_update / apply_update / diff_* | `uo_init.update` |
| confidence_report / export_integrity | `quality.yaml` + `uo_init.pilot_engines.export_integrity` |
| key_triage / key_resolution / confidence_review | **确定性 stub**（见 [open-problems](../debug/open-problems.md)） |

输入：`manifest.yaml`、分层 YAML、`ir/operator_graph.yaml`、`quality.yaml`、sqlite。  
输出：`uo/diff/*`、`uo/summary/update_plan.yaml`、receipt（对齐既有 OUTPUT_CONTRACT）。

**禁止**消费 `extract_plan.yaml` 或旧 semantic ledger。
