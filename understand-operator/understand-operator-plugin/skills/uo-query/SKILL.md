---
name: uo-query
description: >-
  Answer questions from an existing AscendC operator knowledge base.
  Use when the user runs /uo-query, understand_operator_query, or asks about an
  operator using the KB. Classify the question first, resolve the real KB path,
  read route.md then typed artifacts; if KB is missing, ask init vs source-read.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] <question>"
---

# uo-query — KB-First Q&A

Answer from the **existing** operator KB. Do **not** rebuild unless the user chooses init.

## Variables

- `PROJECT_ROOT`: AscendC operator repo root (prefer the directory that contains `op_host/` / `op_kernel/`, or the path the user gave).
- `PLUGIN_ROOT`: two levels up from this skill directory (`.../understand-operator-plugin`).
- `PROMPT_DIR`: `$PLUGIN_ROOT/prompts`.
- `SCRIPT_DIR`: `$PLUGIN_ROOT/skills/understand-operator`.
- `OP_NAME`: `--op-name` if given; otherwise resolve from KB (see below). **Do not** blindly use a parent folder name like `FAG_test`.
- `UO_ROOT`: resolved KB root that contains `route.md`.

## Mandatory references (read these)

Before answering, load:

1. `references/question-taxonomy.md` — classify the question
2. `references/kb-file-map.md` — which KB files store what

Also follow `$PROMPT_DIR/00_cbm_first_rule.md` for any **source** lookup.

## Step 0 — Resolve KB path (fix the “找不到知识库” bug)

Real layout is:

```text
<operator_repo>/.understand-operator/<op_name>/route.md
```

Example that must work:

```text
D:\PR-review\TEST\FAG_test\flash_attention_score_grad\.understand-operator\flash_attention_score_grad\route.md
```

**Search order** (stop at first hit that has `route.md`):

1. If user passed `--op-name X`: `$PROJECT_ROOT/.understand-operator/X/route.md`
2. If `$PROJECT_ROOT/.understand-operator/*/route.md` exists (one or more child dirs): pick the best match
   - prefer directory name == current folder name
   - else prefer the only child that has `route.md`
   - else list candidates and ask the user which op
3. Walk up at most 3 parents looking for `.understand-operator/*/route.md` (workspace may be opened at `FAG_test` while KB lives under `flash_attention_score_grad/`)
4. Glob: `**/.understand-operator/*/route.md` under the workspace / given path

Set `UO_ROOT` to the directory that **contains** `route.md` (the `<op_name>` folder), and set `OP_NAME` from that folder name.

**Wrong** (do not do this):

- `$PROJECT_ROOT/.understand-operator/FAG_test/route.md` when the repo folder is `FAG_test` but the op KB is `flash_attention_score_grad`
- assuming `UO_ROOT = .understand-operator` without the `<op_name>` child

## Step 1 — If KB missing: user choice (mandatory)

If no `route.md` found after Step 0, **do not** only say “请先 /uo-init”.  
Present a choice and wait:

```text
未找到可用 KB（缺少 route.md）。请选择：
1) init — 运行 /uo-init 构建完整知识库后再问
2) source — 不建库，直接用 CBM→源码回答本次问题（答案不落 KB）
3) stop — 取消
```

Prefer asking in chat (do **not** open an interactive stdin popup):

```text
未找到可用 KB（缺少 route.md）。请在聊天回复：
1) init — 运行 /uo-init 构建完整知识库后再问
2) source — 不建库，直接用 CBM→源码回答本次问题（答案不落 KB）
3) stop — 取消
4) manual_supplement: <说明 KB 路径或 op-name>
```

Optional helper (prints menu only; does not block):

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate query_missing_kb --title "未找到 KB：请选择"
```

After the user replies in chat, record:

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate query_missing_kb --decision init
```

Never use `--interactive` / `--arrows` inside OpenCode agent shells.

- `init` → tell user to run `/uo-init <operator_repo> --op-name <op> --full`（或你代为启动 uo-init）
- `source` → skip KB; answer with CBM-first then source; state clearly this is source-only
- `stop` → end

## Step 2 — Classify the question

Using `references/question-taxonomy.md`, set:

- `question_type`: `io_boundary` | `host_tiling` | `compute_dataflow` | `kernel_path` | `evidence_quality` | `testing_hints` | `overview_route` | `mixed`
- optional `secondary_types`

Print one line: `问题类型: <type>`

Example: “哪种输入 shape 更容易命中 IsTndSwizzle” → `host_tiling`.

## Step 3 — KB read order

1. Read `route.md` (and `route.json` if useful) — use Fast Task Routes / maps as the jump table.
2. Open typed files from `references/kb-file-map.md` for `question_type`.
3. Answer from KB when enough; cite paths.
4. If KB has `unknown` / conflict / user wants code proof:
   - CBM first via `cbm_query.py`
   - only then source `Read` (whole file only after CBM failure)

Never open `.cpp/.h` before CBM for a source lookup.

## Answer style

- First line: `问题类型: ...`
- Then the direct answer
- Cite KB paths (e.g. `tiling/tiling_decision_tree.md`, `tiling/dispatch_variables.yaml`)
- If route pointed you somewhere, say so briefly
- If used CBM/source, say so + confidence
- If quality gate is red/yellow or conflicts exist, mention relevant Hot Risks from `route.md`

## CBM helper

```powershell
python "$SCRIPT_DIR/cbm_query.py" "$PROJECT_ROOT" search_graph --op-name "$OP_NAME" --name-pattern ".*IsTndSwizzle.*" --label Function --phase query
```

`PROJECT_ROOT` must be the **operator repo** that was indexed (the folder containing `op_host/`), not the plugin repo.
