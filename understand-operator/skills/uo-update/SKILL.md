---
name: uo-update
description: >-
  Incremental AscendC operator KB update: git diff vs last KB revision, selective
  layered IR rebuild (syntax-first + bounded LLM), emit isomorphic KB plus
  dedicated diff/ product for PR test generation.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--base <rev>] [--head <rev>]"
---

# uo-update — 新 KB + 专用 diff 产物

在已有 `.understand-operator/<op_name>/` 上增量刷新：

1. **新 KB**：与 `/uo-init` **同构**的完整知识库（当前 HEAD 快照）
2. **专用 `diff/` 产物**：给后续 PR 测试例生成优先消费；不确定再回查 KB

本期**不实现** testcase-agent / Z3 / 真实用例生成。

## 进度 Todo（必须用中文，且只用下面这 7 条）

```text
1. 校验已有 KB 与 revision
2. 计算 git diff → diff/change_set.yaml
3. 生成 update_plan 并展示影响面
4. 必要时 Phase0 复审 / CBM 重索引
5. 按层重抽并写出新 KB
6. 有界语义补全
7. 写出专用 diff 产物并校验 KB
```

## Variables

- `SCRIPT_DIR`: `$PLUGIN_ROOT/uo/scripts`
- `PLUGIN_ROOT` / `PROMPT_DIR`: 同 uo-init
- `PROJECT_ROOT`: 算子仓库根
- `OP_NAME` / `UO_ROOT`: `$PROJECT_ROOT/.understand-operator/$OP_NAME`

Always pass `PLUGIN_ROOT`, `PROMPT_DIR`, `SCRIPT_DIR` in dispatch context.
Read `$PROMPT_DIR/01b_update_orchestrator.md` and `$PROMPT_DIR/00_language.md`.

## Preconditions

- `$UO_ROOT/manifest.yaml` 存在且 `source.revision` ≠ `unknown`
- `$UO_ROOT/ir/operator_graph.yaml` 存在（曾跑过 extract）

否则停止并提示用户先跑 `/uo-init`。

## Pipeline

### 1–3 Detect + plan

```powershell
python -X utf8 "$SCRIPT_DIR/detect_kb_changes.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
python -X utf8 "$SCRIPT_DIR/plan_kb_update.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

向用户展示 `summary/update_plan.yaml` 的 `mode` / `affected_layers` / `needs_phase0_review`。

### 4 Phase0 gate

若 `needs_phase0_review`（scope 外疑似算子源码，或 spec hash 变化）：

- **停止**，用 AskQuestion / review 菜单：`continue` | `revise` | `stop`
- 仅 `continue` 后可带 `--confirm-phase0` 继续；必要时先重跑 scope 确认与 CBM 窄索引（同 uo-init Phase0 后半段）

scope 不变则不要打断。

### 5–7 Rebuild + diff product + validate

优先一键编排：

```powershell
python -X utf8 "$SCRIPT_DIR/update_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

可选：`--base` / `--head`（PR）、`--confirm-phase0`、`--architecture arch35`。

或分步：

```powershell
python -X utf8 "$SCRIPT_DIR/build_layered_kb.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --layers "<from update_plan>"
# 若有新增 unresolved entrypoint / residual →
#   dispatch uo-semantic-resolve（用 prompts/00_subagent_dispatch.md 强制模板，抽样 ≤12）
#   → apply_resolution.py --check → apply_resolution.py
python -X utf8 "$SCRIPT_DIR/export_diff_product.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

最终校验用 `validate_kb(..., phase="final", write_outputs=True)`。

## 产物

### KB（同构）

`manifest.yaml`、`ir/**`、`contracts/testcase.yaml`（lean：hashes 在 `checks/artifact_hashes.yaml`）、`tiling/`、`kernel/`、`cross_layer/`、`checks/`、`summary/human_overview.md` 等与 init 一致（默认 lean）。

### 专用 diff（PR 主入口）

```text
diff/index.yaml
diff/change_set.yaml
diff/impact.yaml
diff/unresolved.yaml
```

PR 测试生成：**先读 `diff/`**；`confidence=low` / `layer_only` / `unresolved` → 按 `kb_refs` / `kb_lookup` 回查 KB。

成功更新后脚本会导出 `indexes/kb_graph.sqlite` 与 `summary/human_overview.md`。
Bug 审查复用已有 CBM 索引（`/uo-init` Phase0），**不**需要 code-review-graph。

旧库仅补导 overview（不删文件）：

```powershell
python -X utf8 "$SCRIPT_DIR/export_human_views.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

内部编排（非 PR 主入口）：`summary/update_plan.yaml`、`runs/<id>/update/receipt.yaml`。

## Integrity

- 语法解析为主；仅入口/残留用 `uo-semantic-resolve`（只写 `ir/entrypoint_confirm.yaml` / `ir/resolution_patch.yaml`）
- 不得静默吞入 scope 外源文件
- 用户可见语言默认中文
- 代码审查请用 `/uo-code-review`（不要占用本 skill）
