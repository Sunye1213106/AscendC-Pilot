# 产物模型与权威边界

AscendC-Pilot 在目标算子仓中维护运行状态和分析产物。UO、TG、CE 与 Pilot Runtime 共用 `.ascendc-pilot/`，下游只消费已通过检查的正式结果。空的 OpenCode 打开目录只做 PR clone 锚点，不建 `.ascendc-pilot`。

```text
Source → UO CodeMap → TG / CE
              │
              └→ Pilot state / run records
```

精确路径表见 [产物布局 Reference](../reference/artifact-layout.generated.md)。写入权限与 Lease 见 [Agent Runtime](agent-runtime.md)。

## 工作区布局

```text
<operator-repo>/.ascendc-pilot/
├── control/                       # arch-neutral control plane
│   ├── active_run.yaml            # last exclusive pointer (not the mutex)
│   ├── product_locks.yaml         # family → holder run
│   └── session_bindings.yaml      # session_id → .uo path + digest
└── <arch>/                        # arch35 / arch22 / …，或无 arch* 时的 default
    ├── uo/
    │   ├── <op_name>.<arch>.uo    # Canonical Operator CodeMap (durable)
    │   ├── checks/                # verify receipts (work tree)
    │   └── ir/ …                  # transient UO work (compacted after review)
    ├── tg/                        # init.yaml / plan.md / worklog.md / cases.*
    ├── ce/plan/                   # {slug}_plan.md
    ├── session_handoff.md         # /handoff 对话总结
    ├── state/
    │   ├── slots/<family>/workflow.yaml   # exclusive live state (uo / tg / ce-*)
    │   ├── workflow.yaml          # legacy / last-exclusive mirror
    │   └── action_lease.yaml      # one lease per arch
    ├── runs/
    │   └── {run_id}/live_state.yaml       # shared / query ephemeral
    ├── context/                   # pilot_params and other run projections
    ├── local/                     # operator-local extensions
    └── cache/                     # rebuildable cache
```

`<arch>/uo/<op_name>.<arch>.uo` 是对外 CodeMap 产品，与同目录工作树共存（多架构时各占一个 `<arch>/`）。`control/` 与 `state/` / `runs/` 属 Pilot；`context/` / `cache/` 可重建；`local/` 属于算子仓扩展，不进入 Pilot 通用实现。

对话绑定一份 `.uo`（算子 + arch + `canonical_graph_digest`）。同一产物上多 session 可并行读；写按产物族互斥（`uo-init/update` 与 `tg-*` / `ce-*` 可同时跑）。`complete` 或 `abort` 后把当时状态归档到 `runs/{run_id}/final_state.yaml` 并释放**本族**锁（或 ephemeral query 的 `live_state.yaml`）。`uo-init` / `uo-update` commit 后 digest 变了，已绑定旧 digest 的 session 与下游 TG/CE 标 STALE，答案置信度不得再标 high。正式产物仍在 `<arch>/uo/` 等目录。

## 产物分层

### Canonical

系统当前认可的正式结果：已验证 CodeMap、TG `init.yaml` / `plan.md` / `worklog.md`、CE `{slug}_plan.md` / `session_handoff.md`、workflow state。须有明确 producer 与写入路径；LLM 不能因“认为正确”直接修改。CE 不写 yaml。

### Staging / Evidence

尚未被系统接受的候选：worklog 草稿、testcase 行草稿、review draft、source evidence。只说明“有人产出了这个结果”，不说明已成立。

```text
Producer → Staging → Check / Review → Finalize → Canonical
```

### Receipt

记录一次 Action 如何完成（身份、输入输出、检查结果），用于审计与恢复。Receipt ≠ 领域结论。

### Cache / Derived

为效率保存，可从源码与 CodeMap 重建，不作为事实来源。

### Local（非 canonical）

`local/` 保存算子仓提供的本地扩展实现或配置（例如 replay adapter、testcase builder、`tilingdata_decoder`、construction metadata）。其代码/配置本身可作为**执行输入**，但不得直接声明 UO/TG canonical 领域事实；覆盖结论仍须经 Host Replay 或正式 gate。

## 写入权威（摘要）

| 区域 | 主要写入者 | 消费者 |
| --- | --- | --- |
| `<arch>/uo/<op>.<arch>.uo` | UO deterministic commit | Query / TG / CE |
| `<arch>/tg/init.yaml` `plan.md` `worklog.md` `cases.*` | TG promote / 人确认 | TG（`/tg-plan` 自己从 CE md / 对话总结） |
| `<arch>/ce/plan/{slug}_plan.md` | `/ce-plan`（LLM）；`/ce-apply` 可勾 todo | apply / tg-plan |
| `<arch>/session_handoff.md` | `/handoff` | 下一会话 / tg-plan |
| `<arch>/state/**` | Pilot Runtime | Pilot |
| `<arch>/runs/**` | 当前 Action | Checker / recovery |
| `<arch>/cache/**` | Engine / Pilot | Runtime（可重建） |

TG / CE 可读 UO，不可改 UO。领域 Agent 不应手工改 `state/` 跳过流程。

## 新鲜度与失效

CodeMap 绑定 Source Scope、BuildVariant、架构与编译环境 fingerprint。源码或构建变化后：

```text
Source / Build Change → /uo-update or /uo-init → Fresh CodeMap → TG / CE
```

### Projection freshness（view_blob）

Semantic authority 是已 commit 的 `.uo` canonical 表。`view_blob/*` 是可重建投影，提交顺序为：

```text
semantic change → canonical finalize → digest → build projections
  → validate provenance → atomic write
```

每个投影应携带 provenance：`canonical_revision` / `canonical_graph_digest` / `entity_count` / `relation_count` / `schema_version` / `projection_builder(+version)`。

**仅 fingerprint 不够**：kind 直方图相同但边被 drop 后，summary 与 `ir/operator_graph` 的 edge 计数仍可能漂移。Query 路径在 mismatch 时返回 `VIEW_STALE`，由 engine fallback 到 canonical 重投影（不进 LLM）。

TG / CE 不应在 UO 过期时自行从源码推导正式语义。上游变化后，旧 coverage / review 结论不能无条件沿用。新鲜度比的是会话/run **钉住的** `canonical_graph_digest`（handle.digest）与当前 `.uo`，禁止用当前图和自己比来宣称 fresh。digest 变化时 reason_code 为 `UO_DIGEST_CHANGED`。

## 失败与恢复

失败信息落在 `state/` 与对应 `runs/`。恢复沿 Workflow 声明的边进行（rework / abort / start），不要靠手工改正式产物“修好状态”。细节见 [Agent Runtime](agent-runtime.md)。
