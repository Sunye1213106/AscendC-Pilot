# TG：测试用例与覆盖闭环

TG（Testcase Generation）不是普通的 testcase generator。它将 UO 提供的算子模型转化为可审计的覆盖义务账本，并用 replay 观察和经审查的排除证据关闭账本。目标不是“模型认为覆盖了”，而是在约定的域内证明没有未处理义务。

## 覆盖义务模型

对一个目标域，TG 使用以下集合：

```text
D = declared / discovered target obligation domain
R = replay-confirmed reachable obligations
E = soundly excluded obligations
O = open obligations

O = D - R - E
R ∩ E = ∅
```

只有当 `O = ∅`，且 `R` 具备真实 replay evidence、`E` 具备足够的 source-backed exclusion evidence 并满足 gate contract 时，才可签发 closure certificate。候选输入、SAT 结果或静态目标声明都不是 coverage；它们只能帮助寻找需要 replay 的候选。

## 输入和前置条件

TG 只读消费 UO CodeMap、TG projection、契约和计划产物，并可使用 operator-local replay、golden provider、TilingData decoder 等扩展。UO 若缺失或因源码变化而过期，应先完成 `/uo-init` 或 `/uo-update`。

## 三条工作流

`/tg-init` 建立 TG contract 并执行初始化审计：`intent -> kb_ready -> contract -> bind -> gate -> confirm`。它确认 UO 输入可用、指纹新鲜、TilingKey binding 和审计条件成立。

`/tg-plan` 将目标域和层级转成可执行计划：`intent -> scope -> gate -> build -> filter -> review -> approve`。计划批准后才允许求解。

`/tg-solve` 执行证据闭环：`gate -> oracle -> ledger -> search -> residual -> construct -> lemma -> audit -> certify`。其中 residual 会被路由回 search、construct 或 lemma；证据不足时不能以“已尝试”关闭义务。

## Solve 的真实闭环

```text
                         obligation
                              |
               +--------------+--------------+
               |              |              |
             search       construct        lemma
               |              |              |
               +------ candidate -----------+
                              |
                          host replay
                          /          \
                   observed         mismatch
                      |
                      v
                      R

lemma -> producer -> source evidence -> referee
                                      |
                              deterministic apply
                                      |
                                      v
                                      E
```

Search 和 construct 的输出只是 candidate。只有 host replay 对目标义务作出真实观察，候选才进入 `R`。另一条路径中，producer 提出 lemma 和源证据，referee 审查，确定性逻辑应用通过的结果，才可能进入 `E`。producer 和 referee 均不能直接写 excluded set。

## L2 与 L3

**L2：TilingKey 闭环。** 对每个声明的 TilingKey，TG 要么通过 replay 证明它可达并记入 `R`，要么以源码证据证明它不可能并记入 `E`。目标是 declared keys 由 `R ∪ E` 覆盖。

**L3：运行时分支闭环。** L3 固定一个已确认可达的 TilingKey，改变可由运行时控制的输入，执行 Host replay，并观察 TilingData/状态与 Kernel branch outcome。它解决的是“同一 key 下的运行时结果”而不是再次枚举 key。

```text
reachable TilingKey
  -> same-key candidate
  -> change runtime-controllable inputs
  -> host replay
  -> observe TilingData / state
  -> kernel branch outcome
```

若 replay 重写了 TilingKey，该 candidate 不能被计作目标 key 的 L3 分支覆盖。没有 decoder 或 replay observation 时，也不能以静态猜测关闭 runtime obligation。

## 产物、失败与实现

TG 在 `<arch>/tg/` 下写入 `init`、`plan`、`contract`、`closure` 和 `replay` 产物；run 级 staging、bundle 和 receipt 位于 `<arch>/runs/`。详细归属见 [产物与权威](../architecture/artifacts-and-authority.md)。

oracle 或环境不可用会保留残留义务并可进入人工介入；审计失败会回到 lemma 或求解阶段；未完成的 ledger 不会签发 certificate。实现入口为 `engines/testcase-generation/testcase_agent/closure/`、`pilot/ascendc_pilot/actions/tg_primary.py` 和 `skills/testcase-generation/`、`skills/source-proof/`。
