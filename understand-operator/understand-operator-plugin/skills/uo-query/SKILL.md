---
name: uo-query
description: >-
  Answer questions from an existing AscendC operator knowledge base.
  Use when the user runs /uo-query, understand_operator_query, or asks about an
  operator using the KB. Workflow: KB draft fast, then CBM MCP verify when
  medium/unknown/conflict/needs_alignment before final answer. NEVER Read/Grep
  operator .cpp/.h before codebase-memory-mcp MCP tools. Do NOT use cbm_query.py.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] <question>"
---

# uo-query — KB 起草 + CBM MCP 校验

从**已有**算子 KB 回答。除非用户选择 init，否则不要重建。

**默认语言：中文。** 对用户的正文、引用段标题、置信度说明用中文；路径/符号/工具名可保留英文。

## Core workflow（强制）

```text
1) KB 快速起草（route → typed artifacts）
2) 判断置信度 / 是否有冲突
3a) KB 已 high-confidence 且无冲突 → 直接输出（可 KB-only）
3b) medium / low / unknown / needs_alignment / conflict / Caveat / 用户要源码证明
    → 必须用 codebase-memory-mcp MCP 校验关键符号（禁止此时以 KB-only 收尾）
4) 用 MCP 结果修正答案后再输出（含「引用」段）
```

**用户要的是：快答案 + 必要时源码校验后的结论。**  
**不要**输出「置信度=medium / needs_alignment + 源码查找: KB-only」这种未校验草稿。

## HARD GATE — 怎么碰源码

校验时：

1. 从 KB Caveat / `evidence_index.yaml` / evidence 取 **symbol / file / line**。
2. **先**调用 MCP 服务器 `codebase-memory-mcp` 的工具（见下）。
3. MCP 成功后：可选 **line-scoped** `Read`（≤80 行）核对片段。
4. 整文件 `Read` 或源码 `Grep`：**仅**在 MCP 失败（空/报错/未连接）且已说明之后。

### 禁止

- Shell 跑 `cbm_query.py` / `uo-cbm` / `codebase-memory-mcp cli ...` 做交互查询
- 未调 MCP 就 `Read`/`Grep` `op_host/**`、`op_kernel/**`、任意 `*.cpp` / `*.h`
- `Glob` 找 `*tiling*.cpp` 后立刻 `Read`

MCP 常驻服务负责建库（`index_repository`）与查询；`cbm_query.py` / CLI 索引对 agent 已废弃。

详情：`references/source-lookup-gate.md`。全局规则：`$PROMPT_DIR/00_cbm_first_rule.md`、`$PROMPT_DIR/00_cbm_on_demand.md`。

## Variables（禁止全盘搜索脚本）

- `THIS_SKILL`: 本 `SKILL.md` 所在目录（可为 `~/.config/opencode/skills/uo-query`）。
- `SCRIPT_DIR`: **优先** `THIS_SKILL/../understand-operator`（含 `review_checkpoint.py`）；见 `prompts/00_path_resolution.md`。
- `PLUGIN_ROOT` / `PROMPT_DIR`: 从 `SCRIPT_DIR/../..` 解析（须含 `prompts/00_cbm_first_rule.md`）。
- `PROJECT_ROOT`: 算子仓库根（含 `op_host/`）；**不是** opencode 配置目录。
- `OP_NAME`: `--op-name`；否则从 KB 解析。**不要**盲目用父目录名如 `FAG_test`。
- `UO_ROOT`: 含 `route.md` 的 KB 根。

OpenCode 常见脚本路径：`%USERPROFILE%\.config\opencode\skills\understand-operator\`。  
**禁止** `Get-ChildItem C:\ -Recurse` 找脚本。

## Mandatory references

回答前加载：

1. `references/question-taxonomy.md`
2. `references/kb-file-map.md`
3. `references/source-lookup-gate.md`

## Step 0 — Resolve KB path

```text
<operator_repo>/.understand-operator/<op_name>/route.md
```

搜索顺序（命中即停）：

1. `--op-name X` → `$PROJECT_ROOT/.understand-operator/X/route.md`
2. `$PROJECT_ROOT/.understand-operator/*/route.md`（优先同名目录 / 唯一候选 / 否则询问）
3. 向上最多 3 层找 `.understand-operator/*/route.md`
4. Glob `**/.understand-operator/*/route.md`

`UO_ROOT` = 含 `route.md` 的目录；`OP_NAME` = 该目录名。

## Step 1 — KB missing

无 `route.md` 时让用户选：`init` / `source` / `stop`（可用 AskQuestion）。  
`source` 路径同样：**MCP first**，禁止直接整文件 Read，禁止 `cbm_query.py`。

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate query_missing_kb --decision <choice> [--notes "..."]
```

## Step 2 — Classify

打印：`问题类型: <type>`  
类型见 `question-taxonomy.md`。

## Step 3 — KB draft（快）

1. 读 `route.md` / `route.json`。
2. Legacy tiling：若无 `tiling/index.yaml`+`key_space.yaml` 但有旧文件 → 提示 regenerate。
3. `host_tiling`：先 `tiling/index.yaml`，再按 `qa_routes` 读（不要默认读完所有 tiling YAML）。
4. 按 `kb-file-map.md` 打开对应文件，**起草**答案要点。

## Step 4 — Verify gate（强制，MCP）

对草稿做检查。出现任一信号 → **进入 MCP 校验，不得直接输出**：

- `confidence: medium` / `low`
- `needs_alignment`
- `unknown` / `conflicting`
- Caveat / Hot Risks / “张力” / “待确认” / “建议核对源码”
- KB 内部矛盾
- 用户明确要源码行 / 证明

校验步骤：

1. 从 KB 抽出要查的 symbol（如 `SetSplitAxis`、`CheckExceedL2Cache`）。
2. 调 MCP（见下方 helper）；优先 `search_graph` → `get_code_snippet`，不要整文件。
3. 用结果更新：命中条件、是否可达、置信度。
4. **禁止**输出未校验的 medium Caveat + `源码查找: KB-only`。

仅当草稿已 **high-confidence**、无冲突、用户也未要求源码时，才允许 `源码查找: KB-only`。

若 MCP 服务器未连接：停止并提示配置（见仓库 `docs/cbm-mcp-setup.md`），不要用 Grep/`cbm_query.py` 顶替。

### host_tiling 区分

- tiling 机制 / 变量清单 / 影响分类 → `variables.yaml`（`tiling_mechanism` / `variables` / `impact_classification`）
- family / 结构路径 → `families.yaml`
- tiling_key 字段（编码）→ `key_space.yaml`（`fields` / `fields_order` / `derived_fields`）
- tiling_key 逻辑关系（mutex/implies/合法组合）→ `constraints.yaml`（`relations` / `variable_constraints`）
- tiling_key 剪枝 / 合并 → `constraints.yaml`（`tiling_key_pruning` / `tiling_key_merging`）
- tiling_key → 输入构造 → `constraints.yaml`（`input_realization`）+ `operator.yaml`
- 关系覆盖债务 → `coverage_model.yaml`（`key_relation_obligations.must_cover` + `linked_relations`）
- tilingdata 数值 → `data_model.yaml`
- optional input → `variables.yaml` + `key_space.yaml` + `data_model.yaml`
- unreachable（family）→ `families.yaml`；unreachable（key 组合）→ `constraints.yaml`（`key_unreachable`）
- 覆盖债务总览 → `coverage_model.yaml`

## Answer style

- 首行：`问题类型: ...`
- 中间：直接结论（校验后）+ 必要表格/条件
- **结尾必须有「引用」段**（见下），缺这段视为回答未完成

### 强制结尾模板：引用

```markdown
## 引用

**KB**
- `tiling/families.yaml` TF007（或对应 family_id / 字段）
- `tiling/key_space.yaml`（相关 key field）
- `tiling/route.md` / `tiling/data_model.yaml` / `tiling/coverage_model.yaml`（用到的才列）
- `kernel/paths/K_TASK_xxx_kernel_path.yaml`（若相关）

**源码核实**
- `op_host/.../foo.cpp:440-463` — 作用一句话
- （若本次未做：写「未做 — 原因：KB high-confidence」或「MCP 失败/未连接：…」）

**置信度**
- 高 / 中 / 低 — 一句话理由
- 若有唯一不确定项：单独写清 + 建议如何确认

**源码查找**
- `KB-only（KB high-confidence，无需校验）` 或 `KB + MCP(search_graph/get_code_snippet) 已校验`
```

规则：

1. **KB** 至少 1 条真实读过的路径；优先 canonical tiling 文件。
2. **源码核实** 在做过 MCP / line-scoped Read 时必须带 `file:line-line`。
3. 答案含 `medium` / `needs_alignment` / Caveat 时，**源码核实** 不得写「未做」。
4. **源码查找** 行写 `MCP(...)`，不要写 `cbm_query.py`。

## MCP helper（唯一查询入口）

调用 MCP server **`codebase-memory-mcp`**：

| 目的 | tool | 参数 |
|---|---|---|
| 找符号 | `search_graph` | `name_pattern=".*SetSplitAxis.*"`, `label="Function"` |
| 找字符串 | `search_code` | `pattern="CheckExceedL2Cache"` |
| 函数片段 | `get_code_snippet` | 先 `search_graph` 得 qualified name，再查 `symbol` |
| 调用链 | `trace_path` | `function_name=...`, `depth=5` |
| 是否已索引 | `list_projects` / `index_status` | `repo_path=PROJECT_ROOT` |

`PROJECT_ROOT` = 已索引的算子仓库根（含 `op_host/`）。  
未索引 → 提示用户 Index / `/uo-init --full`，**不要**用全树 Grep 或 `cbm_query.py` 代替。

## KB Resolve Override

This section overrides the older Step 0 search order above.

1. Extract possible operator tokens from `--op-name` and from the user's question. Treat mixed Chinese/English tokens such as `fasg算子的...` as containing `fasg`.
2. Query must only read existing KB directories. Never create `.understand-operator/<token>/` during query path resolution.
3. Enumerate candidate KBs from `$PROJECT_ROOT/.understand-operator/*/route.md`, parent directories up to 3 levels, and finally `**/.understand-operator/*/route.md`.
4. For every candidate, read light metadata only: KB directory name, `index.yaml.op_name`, `operator.yaml.op_name`, `registry/aliases.yaml.aliases[].alias`, and `query/terminology.yaml.aliases[].alias`.
5. Match each user token against exact, lower-case, punctuation-stripped, and initialism aliases. Example: `flash_attention_score_grad` must derive `fasg`; `FAG_test` must derive `fag`.
6. If one candidate matches, use it. If several candidates match, ask the user to choose. If none match but there is exactly one candidate KB, use it and state that alias matching did not hit.
7. If no existing KB is found, go to the missing-KB gate; do not fall back to scanning source trees or making an empty KB.
