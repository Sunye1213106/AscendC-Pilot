# extract_plan — 输入为根的 Relation Graph（领域方法）

> 勿在本文件推进 Pilot 阶段；只执行 `acp next` / `acp run-action` 给出的动作。  
> Agent 不得自行 advance；闭环由 Pilot engine + gate 托管。

## Purpose

确定性抽取 Observation；仅歧义 Relation 交 LLM；**最终 role/sink/条件由 Relation 确定性派生**。  
**根节点只能是真实算子边界 input_roots**（来自 `operator_boundary.yaml` / confirmed Host inputs）；中间量不是根。  
从输入正向推导条件 / 分支 / 模板 / tiling 写入 / KEY。

**入口事实源唯一**：`ir/entrypoint_graph.yaml`。禁止 `roles.*.selected`。

## Pilot engine 闭环

```text
detect_score_pre
→ extract_plan prepare →（可选 Map workers）→ extract_plan --finalize
→ detect_score_post
→ adjudicate_llm_tasks → apply_semantic_patch → rebuild_from_ledger
```

## extract_plan（本 Action）— 严格两阶段

**prepare（`acp run-action extract_plan`）只做：**
1. `propose_extract_plan` → candidates
2. observations → obligations → immutable base relation graph
3. relation batches（仅有 LLM obligations 时）
4. 写 `inputs/extract_plan_snapshot.yaml` 等权威产物并**立即返回**

即使 `deterministic_only: true`，prepare **也不得**调用 finalize。必须返回：

```yaml
finalize_required: true
recommended_command: acp run-action extract_plan --finalize
```

**Map workers（仅存在 LLM obligations 时）：**
读 obligation batch → 写 `staging/relation_parts/part_NNN.yaml`（确认/拒绝/暂缓 **Relation**，禁止选 role）

**finalize（`acp run-action extract_plan --finalize`）只做：**
1. 校验 prepare snapshot SHA（不匹配 → `EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE`，禁止静默重算）
2. reduce relation parts（或 promote base graph）
3. materialize → hydrate（只补证据/身份）→ slim IR + sidecars
4. 仅构建 missing/stale layered KB（entrypoints fresh 则 reuse）
5. 原子提交 canonical artifacts

**语义权威**：`uo/ir/semantic_relations.yaml`  
**原子关系**：`BINDS|WRITES|READS|DERIVES|EQUIVALENT_TO|COMPOSES_KEY|CONTRIBUTES_TO_KEY|GUARDS|SELECTS_TEMPLATE|GROUNDED_IN|CALLS|REACHABLE`

**Gate**：
- 非 input_root 不得作为根
- 条件/分支/模板/KEY 维必须 `GROUNDED_IN` 到真实输入，否则 unresolved
- 冲突 fail-closed；单 shard ≤30；同 pool 可多 shard（conflict_group 细粒度）

**产物**：
- `uo/ir/extract_plan.yaml`（slim：writers/receivers/counts + sidecar refs）
- `uo/ir/semantic_relations.yaml`（唯一语义权威）
- `uo/ir/extract_plan_aliases.yaml` / `receiver_bindings.yaml`

## Hard Constraints

- MUST NOT：prepare 内调用 finalize / 构建 Host/Kernel/Bridge
- MUST NOT：finalize 重建 observations / obligations / base graph
- MUST NOT：LLM 直接写最终 role / 产品 role
- MUST NOT：把 `fBaseParams.*` / 局部 bool / 合成 layout|dtype|B|N|S|D 当 input_root
- MUST NOT：GetTilingData 单独证明 WRITES；COMMON_ASSIGN 单独证明 writer；setter 单独证明 BINDS
- MUST：未 grounding 的条件不得进入可测 coverage

策略见 `policies/evidence`（Roles/sinks derive from relations; intermediate locals are never roots）。
