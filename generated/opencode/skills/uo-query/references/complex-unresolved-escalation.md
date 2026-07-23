# Complex Unresolved → KEY triage + 按复杂度派发

当 residual resolve / KEY bind 碰到**复杂**缺口时，不要停在
`unsolved` / 空白 `binding_gaps` / 没有 shape 表达式的薄 `accepted`。

## What counts as complex

任何与 **KEY 或 shape 条件**相关的 unresolved / bind gap，包括：

- Tiling KEY 谓词 / `set_by` / 命中条件未知或 `needs_alignment`
- 与 KEY 路由绑定且表达式依赖 shape 的字段
- 一次弱 MCP miss 后仍会标 “unknown” / “needs host proof” 的 residual
- TestAgent `UNBOUND_KEY` / `MISSING_CSV_REF` 需要真实 expr 的 KEY↔CSV

简单分析器误报（嵌套 `set_*` 已证明）可留在抽样路径。**KEY shape expr 必须升级。**

## Forbidden

| Forbidden | Why |
|---|---|
| 薄 residual 后直接 `unsolved` / 留下 KEY gap | 未产出 shape expr |
| **默认每个 KEY 一个 subagent** | 过细；simple KEY 应打包 |
| 把 complex（IsNzOut / 分轴等）打进 batch | 上下文稀释与漏解 |
| 发明 `then==else` / 假 domain 清 gap | 门禁绕过 |
| 跳过 Host 阅读、只用 CBM 一跳硬断 | 解法错误；CBM 仅 MAY |
| TG Task 写 `$UO_ROOT/**` 或 `key_shape_resolve/` | 硬隔离：TG → OUT_ROOT only |

## Parent orchestration (required)

1. 收集复杂项 → 按 **KEY id** 分组。
2. 派发 **一次** triage（`tpl_key_triage` / `uo-key-resolve` mode=triage）→ `ir/key_triage.yaml`（或 TG 侧等价清单）。
3. 按 triage 分流并行派发 `uo-key-resolve` + `tpl_key_resolve`（总 Tasks cap≈8）：
   - **complex** → `mode=single`，身份 `<run_id>:resolve:key:<KEY_ID>`
   - **simple** → `mode=batch`（≤6），身份 `<run_id>:resolve:key-batch:<batch_id>`
4. 每个 resolve Task **主路径**：
   - 定稿后：可跑 `/uo-query` 同款 CLI pattern（`branches_for_key` / `affected_shapes` / `neighbors_of`）
   - 建库期：gaps + Host `file_path` 定向 Read（尚无 fresh sqlite 时勿强依赖 query CLI）
   - CBM：MAY 旁证，非闭合必要条件
5. 每个 Task 只写自己的产物（避免写冲突）— **选一种 mode**：

### Mode A — TG bind (testcase-agent parent)

```text
<OUT_ROOT>/realization/uo_query_resolve/<KEY_ID>.yaml
```

- `confidence: high` only when `status: resolved`
- CSV↔HOST / `VAR_CSV_*` / mid nesting: follow
  `skills/tg-init/references/tg-uo-query-escalation.md`
- Parent merges with **`tg-init --merge-uo-resolve` only**
- **Never** read or write `$UO_ROOT/ir/key_shape_resolve/**`

### Mode B — UO staging (understand-operator parent, non-TG)

```text
<UO_ROOT>/ir/key_shape_resolve/<KEY_ID>.yaml
```

- Leaves stay on operator interface / compile-time / `not_input_derivable`
- **Do not** put `VAR_CSV_*` in UO graph staging
- Parent merges into `ir/resolution_patch.yaml` via `apply_resolution.py --check` then apply
- 建库期同时可写 `ir/input_derivable_patch.yaml`（由 classify 消费）

Schema (shared fields; TG fills CSV leaves per TG skill):

```yaml
version: 1
key_id: KEY_EXAMPLE
status: resolved | unresolved | needs_human
shape_expr: "<normalized predicate / shape condition>"
shape_determined: [...]
derivation_chain:
  - {id: ..., deps: [...], via: set_by}
set_by:
  symbol: ...
  file_path: ...
  start_line: ...
  expr_raw: ...
related_unresolved_ids: [DIAG_..., ...]
resolutions:
  - id: DIAG_...
    status: resolved | accepted | false_positive | alias
    rationale: <中文>
    resolution: {kind: shape_expr, label: ..., evidence: "path:line"}
query_backend: kb_graph | host_source
confidence: high
mcp_checked: [SYM::..., ...]   # 可选；可为空
```

6. 仅当 KEY Task 返回 `needs_human` / `unresolved` **且**已列出缺失证据时，父代理可保持该 KEY open —
   仍不得静默 unsolved。非空 TG keys 未解则拦 confirm（empty-tensor allowlist 除外）。

## Dispatch identity

```text
<run_id>:resolve:key-triage
<run_id>:resolve:key:<KEY_ID>
<run_id>:resolve:key-batch:<batch_id>
```

同身份续跑修正；同一 KEY/batch 已 open 时勿再新开。

## Residual sample path vs escalation

| Path | Use when |
|---|---|
| Pattern sample ≤12 + propagate | Clear false_positive / host-only intermediate with shared evidence |
| **triage → complex single / simple batch** | Complex KEY / shape expression / bind expr still missing |

## Build-time note

`/uo-init` 与定稿后均使用 **`uo-key-resolve`**（triage→分流）。  
建库期不派 `/uo-query` 做 KEY 闭合；定稿后可在 key-resolve 内调用 query CLI pattern。

## TestAgent (TG) consumers

When gaps surface on the TestAgent side (`binding_gaps`, abstract `UNBOUND_*`,
`KEY_DERIVATION_MISSING`, `RUNTIME_DOMAIN_NOT_PARTITIONED`, KEY-related
`REALIZE_EMPTY`), follow:

`skills/tg-init/references/tg-uo-query-escalation.md`

Same rule: triage first, then parallel complex-single / simple-batch, write **OUT_ROOT only**, no bare unsolved.
