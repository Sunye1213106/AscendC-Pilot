# 产物布局

所有算子级产物都位于目标算子仓中。

```text
<operator-repo>/.ascendc-pilot/
  uo/
    <op_name>.<arch>.uo
  <arch>/
    uo/
    tg/
    ce/
    state/
    runs/
    context/
    memory/
    local/
    cache/
```

## 说明

- `.ascendc-pilot/uo/*.uo` 是 canonical UO products 的 arch-neutral 位置。
- `.ascendc-pilot/<arch>/state/` 是 Pilot-owned workflow state。
- `.ascendc-pilot/<arch>/runs/` 存放 action bundles、staging、dispatch、handoff 和 receipts。
- `.ascendc-pilot/<arch>/local/` 存放 local extension implementations。
- `.ascendc-pilot/<arch>/cache/` 可重建。

归属和 staleness 规则见 [状态与产物](../architecture/state-and-artifacts.md)。
