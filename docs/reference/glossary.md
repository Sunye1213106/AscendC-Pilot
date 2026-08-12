# 术语表

| Term | 含义 |
| --- | --- |
| ACP | AscendC-Pilot CLI（`acp`）与其控制面入口；见 [Agent Runtime](../architecture/agent-runtime.md)。 |
| Action | 一个 workflow step，带 contract、actor、gates 和 scoped permissions。 |
| Action Bundle | 为 action 准备的 runtime packet。 |
| Action Lease | 单个 action 的 runtime authorization token。 |
| CE | Code Engineering。 |
| CodeMap | UO 生成的结构化算子知识产物。 |
| Deterministic engine | 生产 canonical 或 checked artifacts 的 Python 实现。 |
| Gate | 推进状态前的确定性 pass/fail 条件。 |
| Harness | Pilot + authorize 钩子 + Lease 组成的软控制面；见 [Agent Runtime](../architecture/agent-runtime.md)。 |
| Host adapter | OpenCode、Cursor、Codex 的 host-specific runtime 投影。 |
| L2 | TG TilingKey closure level。 |
| L3 | TG runtime branch outcome coverage level。 |
| Local Extension | 算子本地的 replay / build / golden / decoder 接口实现。 |
| Referee | 审查 evidence 或 producer output 的 Agent role。 |
| TG | Testcase Generation。 |
| UO | Understand Operator。 |
| Workflow Spec | `pilot/ascendc_pilot/workflows/specs.py`，workflow 权威。 |
