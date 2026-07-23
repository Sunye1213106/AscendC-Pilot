# `/uo-code-review` 工作流

`/uo-code-review` 用于在已有 KB 上做双路审查：Bug（CBM 主、KB 补）与 Functional / 语义（KB 主、CBM 补），并写出 `review/**`。

实现方式可概括为：

> 先打包审查上下文，再按双路主图分别取证：缺陷路径以代码图冲击为主，功能路径以知识图谱语义为主，最终汇总为可定位到 `file:line` 的审查报告。

整体原则是：

* Bug 与 Functional 主图不可对调；
* 结论必须有证据，不得只靠单图或命名直觉；
* 只写 `review/**`，不改 `diff/**` 与 `ir/**`；
* `ready=false` 时停止，不得静默单图降级。

---

## 使用条件

| 使用 `/uo-code-review` | 不使用 `/uo-code-review` |
| --- | --- |
| 缺陷 / 需求完整性审查 | 建库 → `/uo-init` |
| | KB 问答 → `/uo-query` |
| | 只生成 `diff/` → `/uo-update` |

编排入口为 `skills/uo-code-review/SKILL.md`，阶段合同为 `prompts/review/workflow.md`。

变量：`SCRIPT_DIR=$PLUGIN_ROOT/engines/uo/uo/scripts`；`UO_ROOT=$PROJECT_ROOT/.ascendc-agent/uo`。

### 双路主图（不可对调）

| 路 | 主图 | 补图 |
| --- | --- | --- |
| Bug | CBM | `kb_graph` |
| Functional | `kb_graph` | CBM |

---

## 核心功能文件入口

| 角色 | 路径 |
| --- | --- |
| Skill | `skills/uo-code-review/SKILL.md` |
| 阶段合同 | `prompts/review/workflow.md` |
| Bug | `prompts/review/bug_review.md` |
| Functional | `prompts/review/functional_review.md` |
| 红线 | `prompts/review/clauses/ascendc_redlines.md` |
| 打包脚本 | `uo/scripts/prepare_review_context.py` |
| 子代理 | `agents/uo-code-reviewer.md` |

---

# Phase 1：就绪校验与上下文打包

## Step 1：校验 KB / 图就绪

**关键文件**

* Skill：`skills/uo-code-review/SKILL.md`
* Manifest：`$UO_ROOT/manifest.yaml`
* 图库：`indexes/kb_graph.sqlite`
* CBM 元数据：`cbm/index_meta.json`

**执行内容**

检查：

* `manifest.yaml` 存在；
* `kb_graph.sqlite` fresh；
* `indexed_via: mcp`；
* 建议已有 `diff/` 或传入 `--base`；
* 可选 `--requirements`。

`ready=false` → **STOP**（提示 `export_kb_graph` / Phase0 索引）。不得安装 code-review-graph。

---

## Step 2：打包审查上下文

**关键文件**

* 脚本：`uo/scripts/prepare_review_context.py`

**执行命令**

```powershell
python -X utf8 "$SCRIPT_DIR/prepare_review_context.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --mode both
# 可选：--requirements <path> --base <rev>
```

**执行内容**

汇总 kb_graph 与 CBM 摘要，生成 `runs/<id>/review/context_pack.yaml`。不重抽 IR。  
读门禁：overview / kb_graph → Grep 热卡 → 小窗 Read → CBM。不得 dump 大 YAML。

**输入 / 输出**

输入为 KB、CBM 与可选需求 / base；输出为 context pack。

---

# Phase 2：双路审查

## Step 3：Bug 审查（CBM 主）

**关键文件**

* Prompt：`prompts/review/bug_review.md`
* 红线：`prompts/review/clauses/ascendc_redlines.md`
* 子代理：`agents/uo-code-reviewer.md`

**执行内容**

以 CBM 调用 / 符号冲击为主，KB 补语义。深挖使用 MCP `trace_path` / `search_graph` / `get_code_snippet`。  
每条 finding 须含 severity、`file:line` 与证据。结论不得只靠 KB。

可与 Step 4 在 Step 2 之后并行。`--mode bug` 时可只跑本路。

**输入 / 输出**

输入为 context pack；输出为 `review/bug_report.yaml` + `.md`。

---

## Step 4：Functional / 语义审查（KB 主）

**关键文件**

* Prompt：`prompts/review/functional_review.md`
* 子代理：`agents/uo-code-reviewer.md`

**执行内容**

以 `kb_graph`（KTPL / KEY 边 + `detail_ref`）为主，CBM 补冲击与旁证。有 requirements 时做需求矩阵，否则做语义完整性。  
结论不得只靠 CBM 调用图。`--mode functional` 时可只跑本路。

**输入 / 输出**

输入为 context pack；输出为 `review/functional_report.yaml` + `.md`。

---

# Phase 3：汇总报告

## Step 5：汇总报告

**关键文件**

* 阶段合同：`prompts/review/workflow.md`

**执行内容**

1. 写 `review/index.yaml`；
2. 写 `review/summary.md`；
3. 可选保留中间态 `runs/<id>/review/**`。

写权限仅限 `review/**`、`runs/*/review/**`。不得写 `diff/**`，不得改 `ir/**`。

**退出条件**

* index 指向对应报告；
* 每条 finding 有证据或显式 skip reason。

---

# 正式产物

```text
$UO_ROOT/review/
  bug_report.yaml / .md
  functional_report.yaml / .md
  index.yaml
  summary.md
```

---

# 禁止事项

* 覆盖 `diff/**` 或修改 `ir/**`；
* `ready=false` 时强行审查；
* 无 context_pack 全仓扫描；
* 无依据给出 critical；
* 安装 / 依赖 code-review-graph；
* 静默单图降级。

---

# 质量标准

一次合格审查应能说明：

1. Bug 路是否以 CBM 为主、Functional 路是否以 kb_graph 为主；
2. 每条 finding 是否可定位到 `file:line`；
3. 是否完成 index / summary；
4. 是否未改动 `diff/**` 与定稿 IR。

失败码见 `skills/uo-code-review/SKILL.md`。
