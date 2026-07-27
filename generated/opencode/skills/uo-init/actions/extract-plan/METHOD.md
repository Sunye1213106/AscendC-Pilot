# extract_plan — 结构抽取（领域方法）

> 勿在本文件推进 Pilot 阶段；只执行 `acp next` / `acp run-action` 给出的动作。  
> Agent 不得自行 advance；闭环由 Pilot engine + gate 托管。

## Purpose

脚本只做事实发现与**分对象评分**；复杂语义交给受 Pilot 约束的 LLM。  
**candidate 边不得假闭合**；Patch 只写 `semantic_resolution_ledger`，再确定性重建派生图。

**入口事实源唯一**：`ir/entrypoint_graph.yaml`。禁止 `roles.*.selected`。

## Pilot engine 闭环（同一 extract 阶段内）

```text
detect_score_pre          # extract.pre_semantic：入口/注册/boundary → llm_tasks
→ extract_plan / build    # extract.plan_and_graph：仅 writers/receivers/aliases
→ detect_score_post       # extract.post_semantic：bridge/KEY/provenance（禁止提前跑）
→ adjudicate_llm_tasks    # producer: open blocking -> ir/semantic_patches.yaml
→ apply_semantic_patch    # deterministic: patches / auto mark_missing -> ledger
→ rebuild_from_ledger     # 重建派生图
→ recheck_closure         # 不递增 attempts
```

Gate：`detect_score_pre` / `extract_plan_subagent` / `semantic_closure` / `detect_score_post`。  
blocking LLM 未清且预算未尽 → 不可 advance。

## Actions

### 1. pre_semantic：入口图 + 评分

- engine：`acp run-action detect_score_pre`
  - 先 `build_layered_kb(layers=entrypoints)` → `ir/entrypoint_graph.yaml`
  - 再评分 → `ir/score_report_pre.yaml` + `ir/llm_tasks.yaml`
- **禁止**直调 `resolve_entrypoints.py` / `build_layered_kb.py`

### 2. 评分 ≠ 严重级别

- 评分 + `required_evidence` → 能否 `source_verified` 自动接受
- 必要性（主链）独立决定 blocking / degraded / informational
- **低分主链缺口仍为 blocking**（`mark_missing` / `inspect_candidates`）
- per-type `score_profile`；禁止跨 object_type 统一 0.85 当真值（alias 可用独立 profile）
- finalize 确定性：高置信 alias auto-fill；冲突进 `deferred_candidates`；三态覆盖 Gate
- producer 只写 staging；canonical `extract_plan.yaml` 由 finalizer 写入

### 3. extract_plan（本 Action · 仅 plan）

**职责边界（硬）**：
- **只做**：确认 prepare 产出的 `decision_worklist` → 写出 staging `decision_report.yaml`
- Finalizer 物化紧凑 `ir/extract_plan.yaml` + sidecar（`extract_plan_aliases.yaml` / `receiver_bindings.yaml`）
- **禁止**：裁决 `ir/llm_tasks.yaml` 里的 `mark_missing` / `dispatches_to` / `entrypoint_dispatch_bind`
- **禁止**：把 call_edge 裁决 / 完整 candidate 列表 / evidence_snippet 写入 canonical `extract_plan.yaml`
- **禁止**：自造 `semantic_groups` / essay 结构代替 decision_report
- 空候选 / 证据不足的 **边** → **留给**后续 `adjudicate_llm_tasks` → `apply_semantic_patch`（写 ledger），本步不要 ACCEPT

**证据（硬 · 公共策略，禁止本 Action 另立例外）**：
- 服从 `evidence` / `code-access` / `source-authority`（`DEFAULT_POLICY_IDS`；compose 已注入 Agent）。
- 能力路径：`structured-ir-query` / `action-scratch` / `cbm-navigation` / `source-reading`。
- Gate 同时校验 **真实性**（磁盘窗口）与 **充分性**（`validate_role_evidence`）；不足 → rework_hints。
- prepare 写 `decision_worklist` + `extract_plan_candidates.summary.yaml`。读序服从 `code-access` 大 IR 模式。
- 用 `acp inspect extract-plan-worklist|extract-plan-coverage|validate --what extract-plan-staging` 自检；禁止手工扫全量 candidates 计数。

**Producer 产出（硬）**：
- 唯一语义裁决文件：`runs/{run_id}/actions/extract_plan/staging/decision_report.yaml`
- 字段：`accepted` / `rejected` / `deferred` / `receiver_binding_confirmations`（含 `candidate_id`）
- `candidates_sha256` 从 prepare stub 原样复制
- **禁止**写：`uo/ir/extract_plan.yaml`、`extract_plan_aliases.yaml`、`receiver_bindings.yaml`、ledger、workflow state
- **禁止**：finalize / next / advance / complete

流程：
1. prepare：`propose_extract_plan` → candidates + **decision_worklist**
2. 派发 **`uo-semantic-resolve`**（不得由 primary 代写 IR）
3. Producer：worklist → `decision_report.yaml` + staging validate
4. `acp run-action extract_plan --finalize`：coverage / role evidence / architecture Gate → slim IR + sidecars + host/kernel/tilingkey/bridge

Writer/receiver 身份：`candidate_id`（禁止短名唯一键）。  
`non_sink_roots` **无**身份字段要求——只认候选名字字符串。

### 4. llm_tasks / mark_missing（后续 Action · 非本步）

- `detect_score_pre` 产出的 blocking `llm_tasks`（含 7×`mark_missing` 等）**不属于 extract_plan**
- Primary 派发 extract_plan 时 **禁止**把整份 `llm_tasks.yaml` 塞进子代理 prompt
- 边裁决 / patch：等 plan+分层 IR 就绪后，经 `adjudicate_llm_tasks` → `apply_semantic_patch` → `rebuild_from_ledger`
- 空候选不得假 ACCEPT；证据不足保留 unresolved

### 5. 分层完整性

- 每个 `input_derivable=true` KEY、verified TilingData、CSV determinant、主 extraction unit
- `operator_capabilities` 显式声明；禁止「没找到 KEY 就当简单算子」
- def-use：仅 verified 边证明 reachability；candidate/structurally_inferred 可展示不可证明

## Hard Constraints

- MUST NOT：直调 `python …/build_layered_kb.py` / `propose_extract_plan.py` / `apply_extract_plan.py`
- MUST NOT：恢复 `selected`；candidate 边闭合主链；patch 直改派生图
- MUST NOT：在 extract_plan 中消化 `llm_tasks` / `mark_missing`
- MUST NOT：recheck/detect/gate 递增 attempts；算子特化正则
- MUST NOT：以 multi-schema 本身触发 LLM；以 `file_contains=op_name` 硬过滤闭包文件
- MUST：证据不足保留分级 unresolved；Agent 不得推进 Pilot 完成态
- MUST：只经 `acp run-action …`；正式 IR 仅由声明 actor（`uo-semantic-resolve`）带 `action_id=extract_plan` 写入
- MUST：Primary 派发 Task 时 `subagent_type`/`agent` = `uo-semantic-resolve`，禁止 primary 自己 Write `uo/ir/**`

## Stop Conditions

- verified-closed + 分层覆盖通过；或 blocking 已入账且 batch 预算耗尽 → fail / 显式 degradation
