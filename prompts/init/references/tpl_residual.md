## Task

遵循 `agents/uo-semantic-resolve.md` 任务 B（可选 D）。残留 unresolved 与可选分支一致性。
只处理 `unresolved.yaml` 中已有 id。

## Target

简单 FP / host-only 抽样 ≤12 条代表诊断。复杂 KEY 缺口 → 写入 `escalate_keys`
（父代理派 **uo-key-resolve triage→分流**，勿本任务闭合）。禁止发明 id。

## Context

- UO_ROOT: `<UO_ROOT>`
- 只读：`<UO_ROOT>/ir/unresolved.yaml`（其中 snippet）
- 可选扫：`<UO_ROOT>/ir/kernel_subgraph.yaml` 分支行
- Schema：`agents/references/semantic-resolve-tasks.md` §B §D
- 需要时 CBM：`prompts/common/cbm.md`（一个符号）

## Authoritative Sources

unresolved.yaml ids · 内嵌 snippet · MCP snippet

非权威：记忆；对手点覆盖 unresolved。

## Required Procedure

1. 按模式分组；每模式取 1–3 代表（合计 ≤12）。
2. 标注 status：`resolved|accepted|false_positive|alias`，附中文 rationale。
3. 复杂 KEY/shape/input_derivable 断裂 → 列入 `escalate_keys`（禁止假 resolved）。
4. 可选 D：可疑分支行写 `consistency_diffs`。
5. 写 `resolution_patch.yaml` 后 stop。父代理：`apply_resolution.py --check`。

## Hard Constraints

- MUST NOT：`residuals:`/`resolutions:`/`decision:accept_warning`；发明 id
- MUST NOT：建库期建议改派 uo-query；静默留下复杂缺口
- MUST NOT：声称已手点覆盖全部 unresolved.yaml
- ONLY write：`<UO_ROOT>/ir/resolution_patch.yaml`
- Cap ~15 tool calls

## Output Schema

```yaml
version: 1
node_patches: []
unresolved_resolutions:
  - id: <id from unresolved.yaml>
    status: resolved | accepted | false_positive | alias
    rationale: <中文简述>
consistency_diffs: []
escalate_keys: []
```

## Acceptance Criteria

- 写出的每个 id 存在于 unresolved.yaml
- 复杂遗留出现在 escalate_keys，或注明未抽样
- check 脚本可校验 patch

## Failure Handling

证据不足 → 仅带理由的 accepted/false_positive，或跳过该 id。
已知复杂 KEY 缺口却空 `escalate_keys` → 禁止。
