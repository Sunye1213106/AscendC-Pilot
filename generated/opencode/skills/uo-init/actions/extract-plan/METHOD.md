# extract_plan — 输入为根的 Relation Graph（领域方法）

> 勿在本文件推进 Pilot 阶段；只执行 `acp next` / `acp run-action` 给出的动作。  
> Agent 不得自行 advance；闭环由 Pilot engine + gate 托管。

## Purpose

确定性抽取 Observation；仅歧义 Relation 交 LLM；**最终 role/sink/条件由 Relation 确定性派生**。  
**根节点只能是 input_roots**（B/N/S/D、layout、dtype、attr…）；中间量不是根。  
从输入正向推导条件 / 分支 / 模板 / tiling 写入 / KEY。

**入口事实源唯一**：`ir/entrypoint_graph.yaml`。禁止 `roles.*.selected`。

## Pilot engine 闭环

```text
detect_score_pre
→ extract_plan (Relation Graph) → materialize slim IR + layered KB
→ detect_score_post
→ adjudicate_llm_tasks → apply_semantic_patch → rebuild_from_ledger
```

## extract_plan（本 Action）

**职责边界（硬）**：
- prepare：`propose_extract_plan` → observations → obligations →（仅歧义）分片
- Map workers：读 obligation batch → 写 `staging/relation_parts/part_NNN.yaml`（确认/拒绝/暂缓 **Relation**，禁止选 role）
- Reduce/finalize：合并 relations → materializer → slim `extract_plan.yaml` + sidecars + `semantic_relations.yaml`
- 确定性闭合：BINDS / WRITES / COMPOSES_KEY / EQUIVALENT_TO / GUARDS / SELECTS_TEMPLATE（证据唯一时不进 LLM）

**原子关系**：`BINDS|WRITES|READS|DERIVES|EQUIVALENT_TO|COMPOSES_KEY|CONTRIBUTES_TO_KEY|GUARDS|SELECTS_TEMPLATE|GROUNDED_IN|CALLS|REACHABLE`

**Gate**：
- 非 input_root 不得作为根
- 条件/分支/模板/KEY 维必须 `GROUNDED_IN` 到输入，否则 unsolved
- 冲突 fail-closed；单 shard ≤30

**产物**：
- `uo/ir/extract_plan.yaml`（含 input_roots / condition_nodes / template_nodes / tiling_field_sinks…）
- `uo/ir/semantic_relations.yaml`
- `uo/ir/extract_plan_aliases.yaml` / `receiver_bindings.yaml`

## Hard Constraints

- MUST NOT：LLM 直接写最终 role / finalize 正式 IR
- MUST NOT：把 `fBaseParams.*` / 局部 bool 当 input_root
- MUST NOT：GetTilingData 单独证明 WRITES；COMMON_ASSIGN 单独证明 writer
- MUST NOT：setter 单独证明 BINDS
- MUST：未 grounding 的条件不得进入可测 coverage

策略见 `policies/evidence`（Roles/sinks derive from relations; intermediate locals are never roots）。
