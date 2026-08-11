# TG - Testcase Generation

## 定位

TG 把 UO 知识转换为 testcase obligations，通过搜索、replay evidence 和被审查的 exclusion 完成覆盖闭环。

## 职责

- 从 UO 构建 TG contracts。
- 规划 coverage obligations。
- 求解 TilingKey 与 runtime branch obligations。
- 在 consumer overlay 需要时执行 semantic binding。
- 执行确定性 search、construct、replay、ledger update。
- 让 producer / referee agents 执行 bounded lemma 与 audit 工作。
- 只有 gate 通过后才签发 closure certificate。

## 非职责

- 不在 UO 已经拥有 CodeMap 时重新理解完整源码。
- 不把静态 set-cover claim 当作 runtime coverage。
- 不允许 lemma producer 写 excluded set。

## 入口

- Slash：`/tg-init`、`/tg-plan`、`/tg-solve`
- CLI：`tg-init`、`tg-plan`、`tg-solve`、`tg-closure`
- Pilot：`acp start tg-init`、`acp start tg-plan`、`acp start tg-solve`

## 输入

- UO CodeMap 与 TG projections
- TG contract 与 plan products
- 可选 replay / oracle 配置
- Local extensions：case building、replay parsing、golden provider、TilingData decoder

## 处理流程

```text
tg-init  -> contract and initialization audit
tg-plan  -> intent, scope, precheck, build, approval
tg-solve -> precheck, oracle, ledger, search, residual, construct, lemma, audit, certify
```

L2 用于 TilingKey closure。L3 复用同一 solve state machine，目标换成 plan level 选出的 runtime branch outcome obligations。

Closure 使用：

- `D`：declared 或 discovered target domain
- `R`：replay-confirmed reachable set
- `E`：soundly excluded set
- `open`：残留 obligations

只有 replay evidence 和 exclusions 满足当前 gate contract，closure certificate 才有效。

## 输出

- `.ascendc-pilot/<arch>/tg/init/**`
- `.ascendc-pilot/<arch>/tg/plan/**`
- `.ascendc-pilot/<arch>/tg/contract/**`
- `.ascendc-pilot/<arch>/tg/closure/**`
- `.ascendc-pilot/<arch>/tg/replay/**`
- `.ascendc-pilot/<arch>/runs/**/actions/**`

## 不变量

- TG 对 UO 只读。
- Runtime branch coverage 必须有真实 replay evidence。
- Producer output 先 staging，再 review 或 deterministic finalization。
- Referee report 不写 canonical excluded set。

## 失败与恢复

`tg-solve` 会把 residual 路由回 search、construct 或 lemma phase。Audit rework 会在 proof 或 exclusion evidence 不足时回到 lemma。环境或 oracle 失败可进入 human intervention。

## 集成关系

TG 消费 UO，也可以给 CE 提供 regression 和 coverage context。Local extensions 连接项目特定的 replay、golden 和 TilingData decoder 逻辑，而不改变 TG core。

## 实现锚点

- `engines/testcase-generation/testcase_agent/`
- `engines/testcase-generation/testcase_agent/closure/`
- `pilot/ascendc_pilot/actions/tg_primary.py`
- `pilot/ascendc_pilot/actions/tg_plan_targets.py`
- `skills/testcase-generation/`
- `skills/source-proof/`
- `agents/deterministic-tg-engine.yaml`
- `agents/tg-lemma-producer.yaml`
- `agents/tg-closure-referee.yaml`
- `agents/tg-init-audit.yaml`

## 测试

- `engines/testcase-generation/tests/`
- `pilot/tests/test_tg_engines_real.py`
- `pilot/tests/test_synthetic_tg_e2e.py`
- `evals/skills/testcase-generation/`
- `evals/skills/source-proof/`
