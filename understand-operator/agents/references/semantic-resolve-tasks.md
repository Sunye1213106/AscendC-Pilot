# semantic-resolve 任务 schema（A–E）

供 `agents/uo-semantic-resolve.md` 引用。宿主一次只派一个任务字母。

## A) 入口确认

只读 `ir/entrypoint_candidates.yaml`。对 `llm_required_roles` / `needs_llm` 每角色恰选一个候选，或 missing。

`kernel_entry` 优先 `op_kernel/<arch>/` 下以 `Kernel` / `Regbase*` / `*Entry` 结尾的名字。

```yaml
version: 1
roles:
  host_tiling_entry:
    qualified_name: ...
    name: ...
    file_path: ...
    start_line: ...
    confirmed_by: llm
    rationale: ...
```

禁止发明候选外符号（除非全部明显错误 → missing + 说明）。

## B) 残留 unresolved

只读 `ir/unresolved.yaml`（及内嵌 snippet）。简单 FP/host-only：每轮 ≤12，按模式抽样代表。

复杂 KEY/形状/可推导断边：**不要**含糊 resolved；写入 `escalate_keys` 交任务 E。

```yaml
version: 1
node_patches: []
unresolved_resolutions:
  - id: DIAG_UNUSED_...          # 必须存在于 unresolved.yaml
    status: resolved | accepted | false_positive | alias
    rationale: ...
    resolution:                  # 可选
      kind: label
      label: ...
      evidence: "path:line"
consistency_diffs: []
escalate_keys: []
```

| 意图 | status |
|---|---|
| 真实 / 已找到 producer | `resolved` |
| 已知告警（host-only） | `accepted` |
| 分析器误报 | `false_positive` |
| 另一 id 别名 | `alias` |

**禁止：** `residuals:` / `resolutions:` / `decision: accept_warning` / 发明 id /
手写全量覆盖 / 复杂项 silent 且 `escalate_keys` 为空 / 建议 init 改派 uo-query。

父代理：`apply_resolution.py --check` → apply（覆盖由脚本验证，禁止手点 1:1）。

## C) Extract plan

只读 `ir/extract_plan_candidates.yaml`（可一次 MCP snippet）。确认 writers/sinks/aliases。

```yaml
version: 1
confirmed_by: llm
writers:
  - name: ...
    file_path: ...
    start_line: ...
    role: tiling_writer   # tiling_writer|key_writer|workspace_writer|provenance_helper|ignore
receivers:
  - name: ...
    is_tiling_sink: true
aliases:
  - local: ...
    tdf_leaf: ...
non_sink_roots: []
extra_host_entries: []
derived_roots: []
```

角色：

- `tiling_writer`：`set_*` / `tilingData->` 写块；evidence 含 `has_set_field`/`recv_set_call`/`sink_set_writer` 时必须用
- `key_writer`：tiling key / block dim 路由
- `workspace_writer`：workspace 尺寸
- `provenance_helper`：链上一跳辅助，不写 sink；有 set_field 证据时勿用
- `ignore`：对溯源无用

父代理：`apply_extract_plan.py --check` 后再抽 Host/Kernel。

## D) 批量一致性

从 kernel 分支行抽查：id / binding_time / determinant_source / condition（短）/
file_path:start_line。可疑 → `consistency_diffs`；一致则 `[]`。通常附在 B 的 patch。

## E) input_derivable 断边

只读：`ir/input_derivable_gaps.yaml`（子集）、kb_graph KEY 邻接（`writes`/`derives`/
`determined_by`）与 Host `file_path`、CBM 一跳片段。

只写：`ir/input_derivable_patch.yaml`（合并追加；勿删其他 KEY 高置信项）。

目标：一跳 `host_parent` + 可接上的 `derivation_roots`，或高置信 `not_input_derivable`。

```yaml
version: 1
keys:
  - key_id: KEY_ISNZOUT
    confidence: high
    input_derivable: true    # 或 false / not_input_derivable
    host_parent: SYM::enableSwizzle
    derivation_roots: [HOST_ATTR_sparseMode, HOST_START_INPUTSHAPE]
    reason: "中文说明"
    evidence: ["path:line"]
```

**禁止：** init 改派 uo-query；低置信标 true；整链 dump；无证据造边。

写完汇报：本批 KEY 数、high 闭合数、仍 open、patch 路径。父代理：
`classify_input_derivable` → `check_final_confidence`。
