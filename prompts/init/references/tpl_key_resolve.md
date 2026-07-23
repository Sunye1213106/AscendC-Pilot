## Task

Follow `agents/uo-key-resolve.md`。按宿主 `mode` 闭合 KEY 的 input_derivable / shape 语义。
**CBM 仅 MAY**（辅助定位）；主路径为 Host 源码定向阅读 +（定稿）`uo_kb_query`。

## Mode

- `mode`: `<single|batch>`
- `single`：恰好 1 个 **complex** KEY
- `batch`：多个 **simple** KEY（≤6）；**禁止**混入 complex

## Target

KEY ids: `<KEY_IDS>`

## Context

- UO_ROOT: `<UO_ROOT>`
- 读：`<UO_ROOT>/ir/input_derivable_gaps.yaml`（子集）
- 读：`<UO_ROOT>/ir/key_triage.yaml`（确认本批档位）
- 定稿可选：`uo_kb_query` 的 `branches_for_key` / `affected_shapes` / `neighbors_of`
- 细节：`skills/uo-init/references/uo-input-derivable-resolve.md`
- CBM（MAY）：`prompts/common/cbm.md`

## Authoritative Sources

1. gaps + Host `file_path` / graph 邻接
2. 源码行级证据
3. 下方 schema

非权威：记忆、命名猜测、宽 Grep；**不以 CBM 空结果作为「不可解」唯一依据**。

## Required Procedure

1. 核对 mode：`single` 仅 1 KEY；`batch` 全为 triage=simple
2. 对每个 KEY：读 host_parent / gap_kind / tried_frontier / set_by
3. **主路径**：按 `file_path` 打开 Host 相关函数，提取谓词 / shape 条件 / 开关含义
4. 需要时（MAY）用 CBM `search_graph`→`get_code_snippet` 旁证；失败则继续源码路径，勿直接放弃
5. 分类并写入 patch：
   - 接到 Attr/Input/Optional/Shape/DType/Layout → `input_derivable: true` + roots
   - kernel-local / 批索引 → `not_input_derivable`
   - 证据不足 → **不写 true**；可写 `needs_human` 说明
6. 若产出 shape 语义：另写 `ir/key_shape_resolve/<KEY_ID>.yaml`（每 KEY 一文件）
7. 汇报后 stop；父代理跑 `classify_input_derivable` / apply

## Hard Constraints

- MUST：思考过程简体中文；仅 high 可闭合
- MUST NOT：把 complex 放进 batch；伪造 high；dump 完整 host_derivation_chain
- MUST NOT：用「仅静态图一跳结论」替代 shape 语义阅读
- ONLY write：
  - `<UO_ROOT>/ir/input_derivable_patch.yaml`
  - 可选 `<UO_ROOT>/ir/key_shape_resolve/<KEY_ID>.yaml`
- Cap ~12 tool calls / Task（batch 内共享上限，宁拆批勿超）

## Output Schema（input_derivable_patch）

```yaml
version: 1
keys:
  - key_id: KEY_...
    confidence: high
    input_derivable: true | false | not_input_derivable
    host_parent: SYM::...
    derivation_roots: [HOST_ATTR_..., HOST_START_...]
    reason: <中文>
    evidence: ["path:line"]
```

## Output Schema（key_shape_resolve，可选）

```yaml
version: 1
key_id: KEY_EXAMPLE
status: resolved | unresolved | needs_human
shape_expr: "<谓词/shape 条件>"
shape_determined: []
set_by:
  symbol: ...
  file_path: ...
  start_line: ...
  expr_raw: ...
confidence: high
reason: <中文>
mcp_checked: []   # 可选；空数组合法
```

## Acceptance Criteria

- 列表内每个 KEY 已尝试
- high 闭合项有 path:line
- batch 无 complex；single 仅 1 KEY

## Failure Handling

不能证明 → 省略 true 闭合；对话说明。禁止假 high。
