# 状态与产物

AscendC-Pilot 把算子级产物写到目标算子仓中。Pilot checkout 本身不保存具体算子的知识库。

## 布局

```text
<operator-repo>/.ascendc-pilot/
  uo/                         arch-neutral canonical CodeMap products
  <arch>/
    uo/                       UO workflow receipts and projections
    tg/                       TG contracts, plans, closure, replay products
    ce/                       CE review and impact products
    state/                    active workflow state and leases
    runs/                     action sessions, bundles, receipts, staging
    context/                  compiled context and pilot parameters
    memory/                   candidate and stable memory
    local/                    local extension implementations
    cache/                    rebuildable caches
    config.local.yaml
```

## 归属

| 路径 | 创建者 | 可写者 | Canonical |
| --- | --- | --- | --- |
| `.ascendc-pilot/uo/*.uo` | UO commit | deterministic UO engine | 是 |
| `<arch>/uo/**` | UO workflow | UO actions | receipts / projections 混合 |
| `<arch>/tg/**` | TG workflows | deterministic TG engine 和 scoped TG agents | TG product 是 |
| `<arch>/ce/**` | CE workflow | CE reviewer 和 finalizers | CE product 是 |
| `<arch>/state/**` | Pilot | Pilot only | 是 |
| `<arch>/runs/**` | Pilot 和 scoped actions | 当前 leased action | receipt / staging |
| `<arch>/context/**` | Pilot | Pilot 和部分 action | 可重建 context |
| `<arch>/memory/**` | Pilot memory layer | scoped actions | 混合 |
| `<arch>/local/**` | user / local extension | user 和 local extension tools | 本地权威 |
| `<arch>/cache/**` | engines | engines | 可重建 |

## Staleness

UO CodeMap 的 freshness 绑定 source scope、architecture 和 fingerprints。TG 与 CE 应消费 CodeMap，而不是重新建立 source authority。源码变化后，先运行 `/uo-update` 或重建 UO，再信任下游 TG/CE 产物。

## 实现锚点

- `pilot/ascendc_pilot/paths/__init__.py`
- `pilot/ascendc_pilot/workspace.py`
- `pilot/ascendc_pilot/uo_artifacts.py`
- `pilot/ascendc_pilot/local_extension.py`
- `pilot/tests/test_product_only_compaction.py`
- `pilot/tests/test_tg_uo_codemap_contract.py`
