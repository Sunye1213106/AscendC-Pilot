# 产物模型与权威边界

AscendC-Pilot 在目标算子仓中维护运行状态和分析产物。UO、TG、CE 与 Pilot Runtime 共用 `.ascendc-pilot/`，下游只消费已通过检查的正式结果。

```text
Source → UO CodeMap → TG / CE
              │
              └→ Pilot state / run records
```

精确路径表见 [产物布局 Reference](../reference/artifact-layout.generated.md)。写入权限与 Lease 见 [Agent Runtime](agent-runtime.md)。

## 工作区布局

```text
<operator-repo>/.ascendc-pilot/
├── uo/
│   └── <op_name>.<arch>.uo        # Canonical Operator CodeMap
└── <arch>/
    ├── uo/                        # UO projections / receipts
    ├── tg/                        # contract / plan / closure / replay
    ├── ce/                        # review / impact
    ├── state/                     # workflow state / lease
    ├── runs/                      # bundle / staging / receipt
    ├── context/                   # rebuildable context packs
    ├── memory/                    # reusable runtime memory
    ├── local/                     # operator-local extensions
    └── cache/                     # rebuildable cache
```

顶层 `uo/<op_name>.<arch>.uo` 是对外 CodeMap 产品。`state/` / `runs/` 属 Pilot；`context/` / `cache/` 可重建；`local/` 属于算子仓扩展，不进入 Pilot 通用实现。

## 产物分层

### Canonical

系统当前认可的正式结果：已验证 CodeMap、TG contract / closure、workflow state。须有明确 producer 与写入路径；LLM 不能因“认为正确”直接修改。

### Staging / Evidence

尚未被系统接受的候选：lemma proposal、testcase candidate、review draft、source evidence。只说明“有人产出了这个结果”，不说明已成立。

```text
Producer → Staging → Check / Review → Finalize → Canonical
```

### Receipt

记录一次 Action 如何完成（身份、输入输出、检查结果），用于审计与恢复。Receipt ≠ 领域结论。

### Cache / Derived

为效率保存，可从源码与 CodeMap 重建，不作为事实来源。

## 写入权威（摘要）

| 区域 | 主要写入者 | 消费者 |
| --- | --- | --- |
| `uo/<op>.<arch>.uo` | UO deterministic commit | Query / TG / CE |
| `<arch>/tg/closure/**` | TG finalizer | TG / regression |
| `<arch>/state/**` | Pilot Runtime | Pilot |
| `<arch>/runs/**` | 当前 Action | Checker / recovery |
| `<arch>/cache/**` | Engine / Pilot | Runtime（可重建） |

TG / CE 可读 UO，不可改 UO。领域 Agent 不应手工改 `state/` 跳过流程。

## 新鲜度与失效

CodeMap 绑定 Source Scope、BuildVariant、架构与编译环境 fingerprint。源码或构建变化后：

```text
Source / Build Change → /uo-update or /uo-init → Fresh CodeMap → TG / CE
```

TG / CE 不应在 UO 过期时自行从源码推导正式语义。上游变化后，旧 coverage / review 结论不能无条件沿用。

## 失败与恢复

失败信息落在 `state/` 与对应 `runs/`。恢复沿 Workflow 声明的边进行（rework / abort / start），不要靠手工改正式产物“修好状态”。细节见 [Agent Runtime](agent-runtime.md)。
