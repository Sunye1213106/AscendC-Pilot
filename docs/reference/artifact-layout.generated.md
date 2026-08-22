# 产物布局 Reference

本文件从 `pilot/ascendc_pilot/paths/` 的路径约定生成，请不要手工编辑。

```text
<operator-repo>/.ascendc-pilot/
  <arch>/uo/<op>.<arch>.uo     UO canonical product (uo_codemap_path)
  <arch>/uo/               UO projections and receipts
  <arch>/tg/               TG init.yaml, plan.md, worklog.md, cases
  <arch>/ce/plan/          CE named plans ({slug}_plan.md)
  <arch>/session_handoff.md         /handoff conversation summary
  <arch>/state/            Pilot state and leases
  <arch>/runs/             action bundles, staging and receipts
  <arch>/context/          pilot_params and run projections
  <arch>/local/            operator-local extensions
  <arch>/cache/            rebuildable caches
```

路径的归属、canonical 语义与 freshness 规则见 [产物与权威](../architecture/artifacts-and-authority.md)。
