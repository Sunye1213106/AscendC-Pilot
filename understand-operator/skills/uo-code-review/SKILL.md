---
name: uo-code-review
description: >-
  Ascend C dual-path code review on an operator KB: bug path (CBM primary, KB
  supplement) and functional/semantic path (KB primary, CBM supplement). Default
  mode=both runs both complete analyses. No code-review-graph dependency.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--mode both|functional|bug] [--requirements <path>] [--base <rev>]"
---

# uo-code-review — Ascend C 双路审查

在已有 `.understand-operator/<op_name>/` 上做代码审查。**两图混用，不装 CRG**：

| 审查路 | 主图 | 补充 |
|--------|------|------|
| Bug / 缺陷 | **CBM**（Phase0 已索引） | **kb_graph** |
| 需求 / 语义完整性 | **kb_graph** | **CBM**（调用冲击 / hotspot） |

默认 `--mode both`：两路都完整跑完。不修改 `diff/**`；报告只写 `review/**`。

## 进度 Todo（必须用中文，且只用下面这 6 条）

```text
1. 校验 KB / kb_graph / CBM 就绪
2. 打包双图审查上下文
3. Bug 审查（CBM 主 / KB 补）
4. 功能或语义完整性审查（KB 主 / CBM 补）
5. 写 review 报告
6. 汇总 index 与 summary
```

## Variables

- `SCRIPT_DIR`: `$PLUGIN_ROOT/uo/scripts`
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`
- `PROJECT_ROOT`: 算子包目录
- `OP_NAME` / `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`

Read `$PROMPT_DIR/01c_code_review_orchestrator.md` and `$PROMPT_DIR/00_language.md`.

## Preconditions

- `$UO_ROOT/manifest.yaml` 存在
- 建议已跑 `/uo-update`（有 `diff/`）；否则用 `--base` 对比
- **复用已有 CBM**（`/uo-init` Phase0 `index_repository` + `cbm/index_meta.json`）；见 `docs/cbm-mcp-setup.md`
- 缺 kb_graph fresh 或 CBM：**停止**并提示建图/索引（不静默单图降级；**不要**安装 code-review-graph）

## Pipeline

### 1–2 上下文

```powershell
python -X utf8 "$SCRIPT_DIR/prepare_review_context.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --mode both
# 可选：--requirements <DESIGN.md|issue-url> --base <rev>
```

若 `ready=false`：展示 errors，指导 `export_kb_graph` / `/uo-init` CBM 索引，然后停止。

### 读门禁（两路共用）

```text
1. summary/human_overview.md 或 kb_graph 查询
2. Grep 热文件（key_cards / runtime_conditions / coverage）
3. 小窗 Read
4. CBM 源码
禁止整读：operator_graph / impact_graph 全文 / testcase 全文 / exhaustive 全文
```

### 3 Bug 路（mode=both|bug）

Read `$PROMPT_DIR/review/bug_review.md`。

- 主：context_pack.cbm.impact（变更符号、callers、priority）+ MCP `trace_path` / `search_graph` / `get_architecture`
- 补：kb_graph `entities_in_files`、侧别、约束旁证
- Ascend 精简条例：`$PROMPT_DIR/review/clauses/`
- 可派发 `uo-code-reviewer` subagent（有界）
- 写出 `$UO_ROOT/review/bug_report.yaml` + `bug_report.md`

### 4 功能 / 语义路（mode=both|functional）

Read `$PROMPT_DIR/review/functional_review.md`。

- 有 `--requirements`：需求矩阵（KB 主 + CBM 补）
- 无 requirements：基于 KB 义务 / `affected_shapes` / 变更实体做**语义完整性**完整检查
- 写出 `$UO_ROOT/review/functional_report.yaml` + `functional_report.md`

### 5–6 汇总

写 `$UO_ROOT/review/index.yaml` + `summary.md`。

## Hard rules

- 禁止覆盖 `diff/**`
- 禁止安装或依赖 code-review-graph
- Bug 结论不得只靠 KB；功能/语义结论不得只靠 CBM 调用图
- 证据需可定位到 file:line（优先 CBM MCP）
