# 产物与权威

Pilot checkout 不保存某个算子的知识库。所有算子级状态写入目标算子仓的 `.ascendc-pilot/`，这样 UO、TG 和 CE 可以围绕同一份本地产物协作，也能在源码变化后明确判断哪些结果已过期。

```text
<operator-repo>/.ascendc-pilot/
  uo/                         UO CodeMap 产品命名空间
    <op_name>.<arch>.uo       规范 CodeMap
  <arch>/
    uo/                       UO projections 与 receipts
    tg/                       contract、plan、closure、replay
    ce/                       review 与 impact 结果
    state/                    workflow state、lease
    runs/                     bundle、staging、receipt、handoff
    context/                  可重建的 context pack
    memory/                   候选或稳定记忆
    local/                    用户提供的本地扩展
    cache/                    可重建缓存
```

顶层 `uo/` 是产品布局，不表示其中的 CodeMap 与架构无关。`<op_name>.<arch>.uo` 的可信度依赖其源码范围、构建上下文、architecture 和相关 fingerprint；源码或构建条件改变后，应先执行 `/uo-update` 或重新运行 `/uo-init`。

## 谁产生、谁消费、谁可以写

| Artifact | Producer | Consumer | Canonical | 可重建 |
| --- | --- | --- | --- |
| `uo/<op>.<arch>.uo` | UO deterministic commit | UO query、TG、CE | 是 | 从源码重建 |
| `<arch>/uo/**` | UO workflow | UO/TG/CE | projection 或 receipt | 多数可重建 |
| `<arch>/tg/contract/**`、`plan/**`、`closure/**` | TG engines 与 finalizer | TG、CE regression | 是 | 取决于 UO 和 replay 输入 |
| `<arch>/tg/replay/**` | replay adapter | TG ledger / audit | evidence | 可按相同输入重放 |
| `<arch>/ce/review/**` | CE review workflow | 开发者 | 当前审查结果 | 可重新审查 |
| `<arch>/state/**` | Pilot | Pilot | 是 | 不应由 Agent 手工改写 |
| `<arch>/runs/**` | Pilot 与当前 leased action | checker、debug、recovery | receipt/staging | run 级临时记录 |
| `<arch>/context/**`、`cache/**` | Pilot 或 engine | 当前 action | 否 | 是 |
| `<arch>/local/**` | 用户或本地扩展 | UO/TG/CE | 本地权威 | 由用户维护 |

## Canonical、staging 与 receipt

Canonical 是下游可依赖的正式结果，只能由拥有该合同的确定性 action 或 finalizer 写入。staging 是 producer 的候选输出，尚未取得下游信任。receipt 记录动作在何种身份、合同和输入下完成，用于 gate、恢复和追溯；它不是新的领域事实来源。

所有权边界的原因很直接：LLM 可以帮助调查和提议，但不能为了让图“闭合”而把猜测写回 CodeMap，也不能把未审查的 exclusion 直接写进 TG ledger。精确路径表由代码生成，见 [产物布局 Reference](../reference/artifact-layout.generated.md)。

## 过期处理

UO 是下游语义输入。发现源码、architecture 或 build context 改变时，先更新 UO；TG 和 CE 不应自行重新建立源码权威。若状态或 gate 表示需要人工介入，保留已知产物和 failure 信息，沿 workflow 的 recovery edge 处理，而不要手工修改 canonical 文件绕过合同。
