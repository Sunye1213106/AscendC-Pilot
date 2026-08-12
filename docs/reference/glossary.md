# 术语表

| Term | 含义 |
| --- | --- |
| ACP | AscendC-Pilot CLI（`acp`）与其控制面入口；见 [Agent Runtime](../architecture/agent-runtime.md)。 |
| Action | 一个 workflow step，带 contract、actor、gates 和 scoped permissions。 |
| Action Bundle | 为 action 准备的 runtime packet（含 stub、method 物化、context）。 |
| Action Lease | 单个 action 的 runtime authorization token。 |
| `BUNDLE_NOT_READABLE` | prepare 读闭合失败：stub 引用路径不存在或不在 lease 可读集合内。 |
| CE | Code Engineering。 |
| CodeMap | UO 生成的结构化算子知识产物。 |
| Deterministic engine | 生产 canonical 或 checked artifacts 的 Python 实现。 |
| `dispatch_ticket` | Host Session Driver 一次性票据；`acp dispatch-result` 凭此 finalize 并继续 drive。 |
| Gate | 推进状态前的确定性 pass/fail 条件。 |
| Harness | Pilot + authorize 钩子 + Lease 组成的软控制面；见 [Agent Runtime](../architecture/agent-runtime.md)。 |
| Host adapter | OpenCode、Cursor、Codex 的 host-specific 投影：**安装期** compose + **运行时** Session Driver。 |
| Host Session Driver | Host 侧传输角色：消费 `host_step`、派发 Task / AskQuestion、调用 `dispatch-result`；不写 canonical、不 advance。 |
| `host_step` | ACP drive 返回的结构化下一步：`dispatch_subagent` / `ask_human` / `done` / `failed`。 |
| L2 | TG TilingKey closure level。 |
| L3 | TG runtime branch outcome coverage level。 |
| Local Extension | 算子本地的 replay / build / golden / decoder 接口实现。 |
| `OUTPUT_NOT_WRITABLE` | prepare 写闭合失败：合同产物路径不在 agent∩action 可写集合内。 |
| `pilot_run` | OpenCode 自定义工具：Host Session Driver 入口（start → auto → Task → dispatch-result）。 |
| Referee | 审查 evidence 或 producer output 的 Agent role。 |
| `serve-authorize` | 常驻 authorize daemon（stdio / IPC）；热路径优先，失败回退 `acp authorize`。 |
| Scope 命名空间 | Agent YAML 路径前缀：`pilot:` / `method:` / `source:`（无前缀旧值兼容）。 |
| TG | Testcase Generation。 |
| UO | Understand Operator。 |
| Workflow Spec | `pilot/ascendc_pilot/workflows/specs.py`，workflow 权威。 |
