# `/uo-code-review` 编排

## Purpose

默认 `mode=both`：Bug（CBM 主）+ Functional（kb_graph 主）。不用 code-review-graph。

## Required reads

`common/language.md` · `common/cbm.md` · `review/bug_review.md` ·
`review/functional_review.md` · `skills/uo-code-review/SKILL.md` ·
`docs/uo-code-review-workflow.md`

## Todo（中文 6 条）

1. 校验 KB / kb_graph / CBM 就绪  
2. 打包双图审查上下文  
3. Bug 审查（CBM 主 / KB 补）  
4. 功能或语义完整性审查（KB 主 / CBM 补）  
5. 写 review 报告  
6. 汇总 index 与 summary  

## Procedure（与 docs Step 对齐）

### Step 1 — 校验就绪

缺 fresh kb_graph 或 CBM meta → STOP（禁静默单图降级；禁装 CRG）。

### Step 2 — 脚本打包 context

```powershell
python -X utf8 "$SCRIPT_DIR/prepare_review_context.py" "$PROJECT_ROOT" `
  --op-name "$OP_NAME" --mode both
```

`ready=false` → 停并提示建图/索引。

### Step 3 — Bug 审查

Follow `bug_review.md` → `review/bug_report.*`。主 CBM，KB 补。  
可派发 `agents/uo-code-reviewer.md`（≤15 tools）。可与 Step 4 并行。

### Step 4 — Functional 审查

Follow `functional_review.md` → `review/functional_report.*`。主 kb_graph，CBM 补。

### Step 5 — 写报告并汇总

写 `review/index.yaml` + `review/summary.md`；**禁写** `diff/**`。  
读门禁：overview / kb_graph → Grep 热卡 → 小窗 Read → CBM；禁 dump 大 YAML。

## Hard rules

- Bug 结论不得只靠 KB；功能结论不得只靠 CBM
- 证据 file:line；条例见 `review/clauses/`
- 思考/报告中文

## Stop

缺 fresh kb_graph 或 CBM meta → STOP。
