# `/uo-query` 工作流

`/uo-query` 用于在**定稿**算子 KB 上做语义问答，或为 TG 绑定生成可消费的 resolve YAML。

实现方式可概括为：

> 以 `indexes/kb_graph.sqlite` 图查询为主路径，结合有界 YAML 展开与 MCP 源码举证，回答实体、约束、TilingKey 分支与 shape 等问题，输出高置信结论或显式 unresolved。

整体原则是：

* 主事实源是图数据库与 CLI JSON，不是整仓扫 YAML；
* 未达 `confidence: high` 时再走 MCP 举证，不得用 Grep 代替图查询；
* TG 绑定只写 `$OUT_ROOT`，不得回写定稿 UO KB；
* 建库期不得用本流程代替 `uo-key-resolve`（KEY triage→分流）。

---

## 使用条件

| 使用 `/uo-query` | 不使用 `/uo-query` |
| --- | --- |
| 定稿 KB 上的问答 / TG bind | `/uo-init` 建库期 KEY 闭合（用 `uo-key-resolve`） |
| 建库完成后的复杂 KEY 升级 | 无 KB / stale KB（先 `/uo-init` 或 `/uo-update`） |

编排入口为 `skills/uo-query/SKILL.md`。

变量：

```powershell
$PLUGIN_ROOT = Join-Path $env:USERPROFILE ".config\opencode\understand-operator-plugin"
$QUERY_CLI   = Join-Path $PLUGIN_ROOT "uo\scripts\uo_kb_query.py"
```

`UO_ROOT=$PROJECT_ROOT/.ascendc-agent/uo`；TG 交付根为 `$OUT_ROOT=$PROJECT_ROOT/.ascendc-agent/tg`。

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill 入口 | `skills/uo-query/SKILL.md` |
| 问题类型 → pattern | `skills/uo-query/references/question-taxonomy.md` |
| 查找门禁 | `skills/uo-query/references/source-lookup-gate.md` |
| 热/冷文件 | `skills/uo-query/references/kb-file-map.md` |
| 复杂 KEY | `skills/uo-query/references/complex-unresolved-escalation.md` |
| CBM | `prompts/common/cbm.md` |
| CLI | `uo/scripts/uo_kb_query.py` |

---

# Phase 1：映射问题并检查图就绪

## Step 1：映射问题类型

**关键文件**

* 分类表：`skills/uo-query/references/question-taxonomy.md`
* Skill：`skills/uo-query/SKILL.md`

**执行内容**

父代理根据用户问题（实体 / 约束 / KEY 分支 / shape 等）选定推荐 `--pattern` 与 `target`。无法分类时应停并澄清，不得猜测 pattern。

**输入 / 输出**

输入为用户问题或父代理任务；输出为明确的 `pattern` + `target`。

---

## Step 2：检查 sqlite 状态

**关键文件**

* CLI：`uo/scripts/uo_kb_query.py`
* 图库：`indexes/kb_graph.sqlite`

**执行命令**

```powershell
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --status-only
```

**执行内容**

| 结果 | 动作 |
| --- | --- |
| `sqlite_ready=true` 且 `freshness=fresh` | 继续；后续标注 `query_backend: kb_graph` |
| stale | **STOP**，提示 `/uo-update` |
| missing / not ready | 仅允许声明原因后的 `yaml_fallback` |

**输入 / 输出**

输入为 `$UO_ROOT` 与图元数据；输出为就绪状态与 freshness。

---

# Phase 2：图查询与证据展开

## Step 3：执行图查询（主路径）

**关键文件**

* CLI：`uo/scripts/uo_kb_query.py`
* 文件地图：`skills/uo-query/references/kb-file-map.md`

**执行命令**

```powershell
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" `
  --pattern neighbors_of --target "<ENTITY_OR_SYM>"
```

常用 pattern：`entity_of` · `neighbors_of` · `constraints_for` · `branches_for_key` · `affected_shapes` 等。至少执行一次 `--pattern`。

**执行内容**

在 sqlite 上查询邻接、约束与 `detail_ref`。机制是图数据库查询，不是 YAML 扫仓，也不是 AST。

不得在未跑 `--pattern` 前 Read/Grep `tiling/key_cards/` 或完整读取 `ir/**`。

**输入 / 输出**

输入为 pattern / target；输出为 graph JSON。

---

## Step 4：按需展开 YAML（次级）

**关键文件**

* 热/冷规则：`skills/uo-query/references/kb-file-map.md`

**执行条件**

JSON 含 `detail_ref`，或需要展开 `set_by`。

**执行内容**

父代理仅小窗 Read `detail_ref` 指向的路径片段，遵守冷热文件规则。

**输入 / 输出**

输入为 graph JSON；输出为展开后的字段片段。

---

## Step 5：未达 high 时 MCP 源码举证

**关键文件**

* 门禁：`skills/uo-query/references/source-lookup-gate.md`
* CBM：`prompts/common/cbm.md`
* 索引元数据：`cbm/index_meta.json`

**执行条件**

默认模式且结论尚未 `confidence: high`。

**执行内容**

1. 读取 `cbm/index_meta.json` 得到 `cbm_project`；
2. `search_graph` / `search_code`；
3. `get_code_snippet`；
4. 需要调用关系时使用 `trace_path`。

不得用 Grep 或本地 CBM CLI 代替 Step 3。用户明确 `fast`（非 TG）时可以 medium 收尾并列出未校验项。

**输入 / 输出**

输入为未达 high 的结论与候选证据；输出为 high 结论或显式 unresolved + reason。

---

# Phase 3：输出结果与复杂 KEY 升级

## Step 6：输出结果

**关键文件**

* TG 细则：`skills/tg-init/references/tg-uo-query-escalation.md`（TG Task）
* UO 回流：`engines/uo/uo/scripts/apply_resolution.py`（仅 UO staging）

**输出形态**

| 形态 | 内容 |
| --- | --- |
| 人读短答 | 结论 + `query_backend: kb_graph` + 引用段 |
| TG 仓外（MUST） | `$OUT_ROOT/realization/uo_query_resolve/<KEY_ID>.yaml` |
| UO staging（可选） | `$UO_ROOT/ir/key_shape_resolve/<KEY_ID>.yaml` |

resolved 仅允许 `confidence: high`。叶子应落在算子接口面，或 compile-time / `not_input_derivable`。

不得改 TG lexicon；不得把 `medium|low` 标为 resolved；不得把 `VAR_CSV_*` 当作 UO 图叶子。

---

## Step 7：复杂 KEY 升级（定稿后）

**关键文件**

* 升级说明：`skills/uo-query/references/complex-unresolved-escalation.md`
* Agent：`uo-key-resolve`（可与 query CLI pattern 组合）

**执行内容**

1. 父代理先派 **一次 triage**，再按复杂度分流（complex 单 KEY / simple 打包，Tasks cap≈8）；
2. 各 resolve Task 仍可走 Step 2→6（先 sqlite / Host 源码；CBM=MAY）；
3. 父代理合并：
   * TG → `--merge-uo-resolve`（只读 `uo_query_resolve/`）；
   * UO staging → `apply_resolution`。

不得与建库期 `input_derivable` 分类文件混写。

合法 skip 仅：`empty_tensor` / `phantom_key*` / compile-time platform / `not_input_derivable`。

---

# 正式产物

* 人读结论（含 `query_backend`）；
* TG：`$OUT_ROOT/realization/uo_query_resolve/<KEY_ID>.yaml`；
* 可选 UO staging：`$UO_ROOT/ir/key_shape_resolve/<KEY_ID>.yaml`。

---

# 禁止事项

* 未跑 `--pattern` 就 Grep/Read 大段 IR；
* 用 Grep / 本地 CBM CLI 代替图查询；
* stale 时强行查询；
* 父代理对每个 KEY 直接循环 CLI、不 Follow 本 skill；
* TG 绑定任务写入 `$UO_ROOT/**`；
* 将 `VAR_CSV_*` 写入 UO staging / 图叶子；
* 建库期用本 skill 修复 `input_derivable`。

---

# 质量标准

一次合格查询应能说明：

1. 使用了哪个 pattern / target；
2. `query_backend` 是否为 `kb_graph`；
3. 结论为何是 high，或为何 unresolved；
4. TG 交付是否只落在 `$OUT_ROOT`；
5. 证据是否可回溯到图边或源码片段。

失败与门禁细则见 `skills/uo-query/SKILL.md`。
