---
name: uo-query
description: >-
  基于定稿算子 KB 做语义问答或 TG 绑定。/uo-query 或 Task 内 Follow 本 skill。
  主路径 uo_kb_query.py 查 kb_graph.sqlite；未达 high 再 MCP 举证。
---

# Skill: uo-query

## Purpose

定稿 KB → **可消费的语义答案 / TG resolve YAML**（`confidence: high` 或显式 unresolved）。

## Trigger

- 适用：`/uo-query`、KB Q&A、TG bind、建库**完成后**的复杂 KEY 升级
- 不适用：`/uo-init` **建库期**断边（用 `uo-semantic-resolve` 任务 E）；无 KB / stale KB（先 init/update）

人读 Step 明细：`docs/uo-query-workflow.md`。

## Inputs

| 权威 | 说明 |
|---|---|
| `$UO_ROOT` | 定稿算子 KB（含 `indexes/kb_graph.sqlite`） |
| 用户问题 / 父代理 target | KEY、实体、约束、shape 等 |
| `question-taxonomy.md` | 问题类型 → `--pattern` |

辅助：`source-lookup-gate.md`、`kb-file-map.md`、`complex-unresolved-escalation.md`、`prompts/common/cbm.md`。

变量（禁止发明）：

| Name | Canonical |
|---|---|
| `PLUGIN_ROOT` | `~/.config/opencode/understand-operator-plugin` |
| `QUERY_CLI` | `$PLUGIN_ROOT/uo/scripts/uo_kb_query.py` |
| `PROJECT_ROOT` / `OP_NAME` / `UO_ROOT` | 算子包与 KB 根 |

## Outputs

| 形态 | 路径 / 内容 |
|---|---|
| 人读短答 | 结论 + `query_backend` + 引用 |
| TG 绑定（MUST，只写 OUT_ROOT） | `$OUT_ROOT/realization/uo_query_resolve/<KEY_ID>.yaml` |
| UO staging（可选，非 TG） | `$UO_ROOT/ir/key_shape_resolve/<KEY_ID>.yaml` → 父代理 `apply_resolution` |

**禁止生成：** 改 TG lexicon；把 `VAR_CSV_*` 写入 UO 图 / `key_shape_resolve`；`medium\|low` 标 resolved；TG Task 写入 `$UO_ROOT/**`。

## Invariants

- 主事实源：`indexes/kb_graph.sqlite` + CLI JSON；YAML 仅经 `detail_ref` 小窗展开
- resolved **仅** `confidence: high`（TG 交付覆盖 fast）
- **人读 / UO staging：** 叶子 ⊆ 算子接口面（`HOST_ATTR_*` 等）或 compile-time / `not_input_derivable`
- **TG Task：** CSV↔HOST 映射与 `VAR_CSV_*` 叶子细则见 testcase-agent  
  `skills/tg-init/references/tg-uo-query-escalation.md`（只写 `$OUT_ROOT`，不改 UO 定稿图）
- TG YAML 须含：`key_id`、`status`、`shape_expr`、`key_derivation.expr`、`shape_determined`、`derivation_chain`
- 幂等：同 KB 同问题应语义等价；TG 模式不改 `$UO_ROOT` 定稿文件

## Tool Policy

### MUST use

- 先 `--status-only`，再至少一次 `--pattern …`
- 未达 high（默认/TG）：按 `source-lookup-gate.md` 走 MCP
- TG：只写 `$OUT_ROOT/realization/uo_query_resolve/<KEY>.yaml`

### MAY use

- `detail_ref` 指向的 YAML 片段 Read
- 用户明确 `fast`（非 TG）时 medium 收尾并列出未校验项
- 非 TG 的 UO 复杂 KEY 升级：可选写 `key_shape_resolve/`

### MUST NOT

- 未跑 `--pattern` 就 Grep/Read `ir/**` 或历史 `tiling/key_cards/**`（非默认产物）
- 用 Grep / 本地 CBM CLI 代替图查询
- 父代理对每个 KEY 直接循环 CLI、不 Follow 本 skill
- stale 时硬查；发明 `SCRIPT_DIR` / `--entity` / `--uo-root`
- TG 绑定任务写 `$UO_ROOT/**` 或把 `VAR_CSV_*` 塞进 UO staging/图叶子
- `/uo-init` 建库期派本 skill 修 `input_derivable`（用 sen 任务 E）

## Workflow

```powershell
$PLUGIN_ROOT = Join-Path $env:USERPROFILE ".config\opencode\understand-operator-plugin"
$QUERY_CLI   = Join-Path $PLUGIN_ROOT "uo\scripts\uo_kb_query.py"
```

### Phase 1: 映射问题类型

- **Entry：** 收到问题 / KEY 任务
- **Actions：** 读 `references/question-taxonomy.md` → 选定 `pattern` + `target`
- **Exit：** pattern/target 明确
- **Failure：** 无法分类 → 停并澄清

### Phase 2: 检查 sqlite

- **Actions：** `uo_kb_query.py … --status-only`
- **Exit：** `sqlite_ready=true` 且 `freshness=fresh`（否则见 Failure）
- **Failure：** stale → **STOP** 提示 `/uo-update`；missing 才允许 `yaml_fallback` 并声明

### Phase 3: 图查询（主路径）

- **Actions：** ≥1 次 `--pattern`（`entity_of` / `neighbors_of` / `constraints_for` / `branches_for_key` / `affected_shapes` …）
- **Artifacts：** graph JSON
- **Exit：** 有可引用的实体/邻接/约束
- **Failure：** CLI 路径错误 → 用 `$PLUGIN_ROOT/uo/scripts` 重试一次；仍失败 → `TOOL_FAILURE`（禁静默 Grep）

### Phase 4: 展开 YAML（次级）

- **Entry：** JSON 含 `detail_ref` 或需展开 `set_by`
- **Actions：** 小窗 Read；遵守 `kb-file-map.md`
- **Exit：** 所需字段已展开

### Phase 5: MCP 举证抬到 high

- **Entry：** 默认模式且结论未 high
- **Actions：** `cbm/index_meta` → `search_graph` / `get_code_snippet` / 需要时 `trace_path`
- **Exit：** high 或显式 unresolved + reason
- **Failure：** 证据不足 → `status: unresolved` + reason（禁 medium resolved）

### Phase 6: 落盘 / 作答

- **Actions：** 人读短答；**TG MUST** 只写 `$OUT_ROOT/.../uo_query_resolve/`；非 TG 的 UO staging 可选 `key_shape_resolve/`
- **Exit：** 答案含 `query_backend`；TG schema 完整

### 复杂 KEY 升级（定稿后）

父代理按 KEY 并行 Task（cap≈8），每个 Follow 本 skill Phase 2–6。  
**合并路径分叉（勿混用）：**
- TG bind → 只写 `uo_query_resolve/` → 父代理 `tg-init --merge-uo-resolve`（**不读** `key_shape_resolve`）
- UO staging → `key_shape_resolve/` → `apply_resolution`  
详见 `references/complex-unresolved-escalation.md`。

## Semantic Escalation

- 语义结论未 high → **必须** MCP（非 Grep）
- 合法 skip 仅：`empty_tensor` / `phantom_key*` / compile-time platform / `not_input_derivable`
- 依赖链停在中间量 → 继续 chain / 再开 Task（TG：细则见 TG mid-symbol nesting）
- 定稿后 TG 可读 `input_derivable_gaps` 作证据，闭合写 OUT_ROOT；**建库期** gaps 不得改派本 skill（用 sen 任务 E）

## Failure Taxonomy

`INVALID_INPUT` · `KB_STALE` · `TOOL_FAILURE` · `UNRESOLVED_SEMANTICS` ·
`NOT_INPUT_DERIVABLE` · `VALIDATION_FAILURE`

## Quality Gate

- [ ] 至少一次 `--pattern`（除非 status 已判定不可查）
- [ ] 答案含 `query_backend`
- [ ] resolved ⇒ `confidence: high` + 证据
- [ ] TG YAML schema 完整；无 `op: call` / 未展开 Host API 叶
- [ ] TG 模式未写入 `$UO_ROOT/**`；未伪造行号
- [ ] 人读/UO staging 未把 `VAR_CSV_*` 当 UO 图叶子

## Stop Conditions

- `Test-Path $QUERY_CLI` 为 False → **STOP**
- stale → **STOP**（`/uo-update`）
- 允许查询次数内仍无 producer path → unresolved + 稳定 reason，禁止猜测闭合
