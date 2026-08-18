# 术语表

Agent 常驻词表（compose 进 invariant pack）：[`agents/CONTEXT.md`](../../agents/CONTEXT.md)。本页是人类全表。

| Term | 含义 |
| --- | --- |
| ACP | AscendC-Pilot CLI（`acp`）与其控制面入口。OpenCode 上用 `pilot_run` / 插件 `pilot_cli`，不要 bash `--help`；见 [ACP 工具使用](../getting-started/acp-tools.md)、[Agent Runtime](../architecture/agent-runtime.md)。 |
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
| Host Session Driver | Host 侧传输角色：消费 `host_step`、派发 Task / AskQuestion、调用 `dispatch-result`；不写 canonical、不 advance。**不驱动** `uo-query`（由主控向用户说明查询方式）。 |
| `host_step` | ACP drive 返回的结构化下一步：`dispatch_subagent` / `ask_human` / `done` / `failed` / `primary_router`（查询拒走 Driver）。 |
| L0 | TG 覆盖梯子的默认档：每维一次。写在 `plan.md` 义务的 `cover` 上，不是 `tg/plan/levels/L0/`。 |
| L2 | TG 覆盖梯子：有界笛卡尔。全量 tilingkey 只在意图点名时做，不是默认 T=D。 |
| L3 | TG 覆盖梯子：异常 / 分支结局。 |
| Local Extension | 算子本地的 replay / build / golden / decoder 接口实现。 |
| `OUTPUT_NOT_WRITABLE` | prepare 写闭合失败：合同产物路径不在 agent∩action 可写集合内。 |
| `pilot_run` | OpenCode 自定义工具：Host Session Driver 入口（start → auto → Task → dispatch-result）。`workflow=uo-query` 会立刻返回 `UO_QUERY_NOT_HOST_DRIVEN`。 |
| Referee | 审查 evidence 或 producer output 的 Agent role。 |
| `serve-authorize` | 常驻 authorize daemon（stdio / IPC）；热路径优先，失败回退 `acp authorize`。 |
| Scope 命名空间 | Agent YAML 路径前缀：`pilot:` / `method:` / `source:`（无前缀旧值兼容）。 |
| TG | Testcase Generation。 |
| UO | Understand Operator。 |
| Workflow Spec | `pilot/ascendc_pilot/workflows/specs.py`，workflow 权威。 |
| occupancy / occupancy_group | Spec 字段：`shared` 永不占锁；`exclusive` 按产物族（`uo` / `tg` / `ce-impact` / `ce-intent` / `ce-verify`）互斥。 |
| product lock | `.ascendc-pilot/control/product_locks.yaml`：family → 持有该族写锁的 run。 |
| session binding | `.ascendc-pilot/control/session_bindings.yaml`：Host session 钉住的 `.uo` 路径与 `canonical_graph_digest`。 |
| `UO_DIGEST_CHANGED` | 绑定/pinned digest 与当前 CodeMap digest 不一致；query/TG/CE 不得再标 high / fresh。 |

## 同名不可互换

这些词在 UO / TG / CE 里都出现，但**不是同一个合同对象**。跨域传递时必须带限定，不能按名字合并。

| 名字 | UO | TG | CE |
| --- | --- | --- | --- |
| TilingKey / TILING_KEY | CodeMap **维实体**（名字 + span + packing 位点） | 声明域来自 `product_uo.legal_key_rows`；不是默认 T | risk dispatch 的锚点 kind |
| legal_key | 模板可接纳的组合 | 声明域大小，供规划参考 | 基本不直接查 |
| obligation | `key_field_obligations`（legacy YAML） | `plan.md` YAML 义务 | `ce-{risk_class}-{digest}` / 账本 `O-V-X` |
| fingerprint | graph 直方图 digest | `init.yaml` 的 `uo_digest` | `cm_graph_fingerprint` 或 git revision。新鲜度比 **handle.digest**（`canonical_graph_digest`），禁止用当前图和自己比来宣称 fresh |
| kind | `EntityKind`（含 FIELD 与 TILING_FIELD） | 列 mapping | risk 路由；不认 FIELD/VARIABLE 当 TILING_FIELD |
