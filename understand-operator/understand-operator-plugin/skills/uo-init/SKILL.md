---
name: uo-init
description: >-
  End-to-end AscendC operator knowledge-base build for a target repo.
  Use when the user runs /uo-init, understand_operator_init, or asks to initialize
  / build a full operator KB in a new or existing AscendC repository.
  Phase 0 must MCP-index the repo into codebase-memory-mcp (graph DB) automatically.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>] [--full]"
---

# uo-init — End-to-End Operator KB Build

Build a complete evidence-backed operator KB under `.understand-operator/<op_name>/` for the target AscendC repo.

## Variables（先解析路径，禁止全盘搜索）

**必读** `$PROMPT_DIR` 解析前先读本 skill 旁的路径规则：打开  
`../understand-operator/SKILL.md` 同级的 prompts 可能不可达时，用下面硬规则。

完整规则：与本 skill 同安装树下的  
`understand-operator-plugin/prompts/00_path_resolution.md`  
（OpenCode：先解析 `SCRIPT_DIR`，再 `PROMPT_DIR=$SCRIPT_DIR/../../prompts`）。

| 变量 | 含义 |
|---|---|
| `THIS_SKILL` | 本文件所在目录（可为 `~/.config/opencode/skills/uo-init` junction） |
| `SCRIPT_DIR` | **优先** `THIS_SKILL/../understand-operator`（必须含 `prepare_operator.py`） |
| `PLUGIN_ROOT` | 含 `prompts/00_cbm_first_rule.md` 的 plugin 根 |
| `PROMPT_DIR` | `$PLUGIN_ROOT/prompts` |
| `PROJECT_ROOT` | 算子仓库根（含 `op_host/`），**不是** opencode 配置目录 |
| `OP_NAME` | `--op-name` 或仓库名 |
| `UO_ROOT` | `$PROJECT_ROOT/.understand-operator/$OP_NAME` |
| `CBM_MODE` | 用户传 `--full` → `full`，否则 `fast` |

OpenCode 已安装时脚本几乎总在：

```text
%USERPROFILE%\.config\opencode\skills\understand-operator\prepare_operator.py
```

**禁止**：`Get-ChildItem C:\ -Recurse`、全盘搜 `prepare_operator*`、因找不到脚本去扫算子 `op_kernel`。  
找不到 → 提示 `./install.ps1 opencode` 后停止。

解析后立刻跑（验证 SCRIPT_DIR）：

```powershell
Test-Path "$SCRIPT_DIR/prepare_operator.py"   # 必须为 True
```

## Global rule

Before any source-code lookup, follow `$PROMPT_DIR/00_cbm_first_rule.md`:
**MCP `codebase-memory-mcp` first; only on MCP failure may you read source.**

## What this command does

1. **Phase 0 — layout + MCP auto-index（强制）**
2. Phase 0.5 — Macro Scope Human Review → **STOP**
3. Phase 1 — Macro Boundary → `operator.yaml` + `index.yaml` + `route.md` + evidence indexes
4. Phase 2 — parallel Task: `uo-host-extraction` + `uo-flow-extraction` → barrier
5. Phase 3 — Kernel Path Task Builder
6. Phase 3.5 — Kernel Dispatch Human Review → **STOP**
7. Phase 4 — parallel `uo-kernel-path` × approved tasks → barrier
8. Phase 5–7 — alignment、evidence、route + test contract
9. Phase 8 — `quality_gate.py`

## Phase 0 — Layout + MCP index（自动，不要跳过）

CBM 的 graph DB **由 MCP `index_repository` 生成**（写入 MCP 本地 store，如 `~/.cache/codebase-memory-mcp/`）。  
**不要**用 `cbm_query.py` / `prepare_operator.py --cli-cbm` / `codebase-memory-mcp cli` 做索引。

### 0.1 KB 目录骨架

先读同目录 `PATHS.md`。OpenCode 可直接用：

```powershell
$SCRIPT_DIR = "$env:USERPROFILE\.config\opencode\skills\understand-operator"
if (-not (Test-Path "$SCRIPT_DIR\prepare_operator.py")) {
  throw "缺少 prepare_operator.py。请在 understand-operator 仓库运行 ./install.ps1 opencode。禁止全盘搜索。"
}
python "$SCRIPT_DIR\prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

只创建 `.understand-operator/<op>/` 布局，**不**建 CBM DB。

### 0.2 MCP 自动索引（强制）

调用 MCP server **`codebase-memory-mcp`**：

1. `index_repository`
   - `repo_path`: `$PROJECT_ROOT`（算子仓库根，含 `op_host/`）
   - `mode`: `$CBM_MODE`（用户 `--full` → `full`，否则 `fast`）
2. `list_projects` 或 `index_status`
   - 确认该 `repo_path` 已出现，记下 `project` / `name`
3. 把 project 名写回 KB：

```powershell
python "$SCRIPT_DIR/prepare_operator.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --write-index-meta --cbm-project "<MCP_PROJECT_NAME>" --cbm-mode "$CBM_MODE"
```

若 MCP 未连接：

- **停止** Phase 0，提示用户按 `docs/cbm-mcp-setup.md` 配置并重启 agent
- **禁止**用 CLI 偷偷索引后假装 MCP 已就绪（除非用户明确要求 `--cli-cbm` 应急）

索引成功后再进入 Phase 0.5。后续所有查代码一律 MCP，不再跑 CLI。

## Hard rules

- Subagents only at the two parallel points. Never background `uo-*` Tasks.
- After parallel Tasks return, run `verify_subagent_barrier.py` before reading subagent artifacts.
- Do not invent IO / branches / kernel paths without evidence.
- `route.md` is a map, not a long report.
- uo does **not** generate real tests, CSV, or golden code.
- Do not cross human review gates (**only 0.5 and 3.5**) without explicit user approval.
- After Phase 1 Macro Boundary: update todos and **immediately** start Phase 2 parallel Tasks. Do **not** dump Boundary/IO/open_questions text into the chat; judgment briefs belong only at gates 0.5 / 3.5.
- **Tiling depth（防偷懒）**：Phase 2 host extraction 必须先写满 `tiling/archive/` 五个中间文件（`frontier` / `dispatch_variables` / `predicate_space` / `compile_time_bindings` / `decision_tree`），再合并进 7 个 canonical。禁止只写薄摘要、跳过宏/`constexpr`/模板分析。barrier 与 `quality_gate.py` 会检查。
- **禁止**宿主手工填 `tiling/*` / `flow/*` 冒充 subagent 完成。

## 默认语言

面向用户一律**中文**。见 `$PROMPT_DIR/00_language.md` 与 `$PROMPT_DIR/00_progress_visibility.md`。  
TodoWrite 的 content **必须用中文标题**（禁止英文 Phase 标题）。

## Startup checklist

1. 解析路径：`SCRIPT_DIR`（先试 `../understand-operator`）→ 确认 `Test-Path prepare_operator.py`；再解析 `PROJECT_ROOT` / `OP_NAME` / `CBM_MODE`。  
   **禁止**因找不到脚本去扫 `C:\` 或算子 `op_kernel`。
2. **TodoWrite（merge=false）** 创建完整中文任务列表（**不要**创建 `uo-p15`），标题固定为：
   - `uo-p0` 阶段 0 — 预检布局与 MCP 自动索引
   - `uo-p05` 阶段 0.5 — 宏观执行范围人工审阅（闸门）
   - `uo-p1` 阶段 1 — 宏观边界分析
   - `uo-p2a` 阶段 2a — 并行下发 host 与 flow 子代理
   - `uo-p2b` 阶段 2b — 屏障校验并读取 tiling/flow
   - `uo-p3` 阶段 3 — Kernel 任务规划
   - `uo-p35` 阶段 3.5 — Kernel 分发人工审阅（闸门，含全量 tiling/family）
   - `uo-p4a` 阶段 4a — 并行下发 kernel path 子代理
   - `uo-p4b` 阶段 4b — 屏障校验并读取 kernel paths
   - `uo-p5` 阶段 5 — Kernel 对齐矩阵
   - `uo-p6` 阶段 6 — 证据一致性审计
   - `uo-p7` 阶段 7 — 路由与知识库地图
   - `uo-p8` 阶段 8 — 质量门禁
3. 阶段 0.1 布局 → 阶段 0.2 MCP `index_repository` → 写入 `cbm/index_meta.json`。
4. **阶段 0.5 宏观范围审阅（闸门）** — 见下节，**必须**用 OpenCode `question` 按钮 UI，禁止退回纯文字输入。

## Phase 0.5 — Macro Scope Human Review（闸门 · 必须 question UI）

读完 `$PROMPT_DIR/01a_macro_scope_human_review.md` 与 `$PROMPT_DIR/00_review_menu.md`。

流程：

1. 用中文展示 include / exclude / branch_skip / uncertain_scope 摘要（不要把 3 个「关键确认」当成最终交互）。
2. **立刻调用 OpenCode 内置 `question` 工具**（`opencode.json` 里 `permission.question: "allow"`）。**禁止**只写「请确认上述范围」然后等聊天框打字。
3. `question` 结构示例：

```json
{
  "questions": [{
    "header": "Phase 0.5 Macro Scope",
    "question": "请确认 Phase 1 探索范围后如何继续？",
    "options": [
      {"label": "continue", "description": "按当前范围进入 Phase 1"},
      {"label": "revise", "description": "调整 include/exclude/skip 后重审"},
      {"label": "stop", "description": "停止 workflow"},
      {"label": "manual_supplement", "description": "手工补充（选后可在输入框写补充）"}
    ],
    "custom": true
  }]
}
```

4. **STOP**，等 `question` UI 返回（↑/↓ 或点击；最后一项可输入）。
5. 落盘：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision <choice> [--notes "..."]
```

6. 仅当 `decision=continue` 才进入 Phase 1。`revise` / `manual_supplement` 吸收 notes 后重新展示并再次 `question`。

**禁止**：贴静态「关键确认 1/2/3」列表替代 `question`；禁止默认 `continue`；禁止 `--interactive` / `--arrows` 抢 stdin。

## Report when done

- `$UO_ROOT` path
- MCP project name / index mode
- review decisions
- `quality.yaml` decision
- point user to `route.md` then `operator.yaml` / `index.yaml`
## Canonical v2 additions

- Initialize and maintain `registry/`, `cross_layer/`, `query/`, and `contracts/`.
- Phase 5 must build cross-layer alignment (`input_to_tiling`, `tiling_to_kernel`, `variable_lineage`, `behavior_graph`, `impact_graph`), not only a kernel alignment matrix.
- Phase 7 must refresh `query/routes.yaml` and `contracts/{query,code_change,pr_review,testcase}.yaml`.
- Phase 8 must run `quality_gate.py`; the gate calls the deterministic KB compiler and writes `archive/runs/kb_compile_report.yaml`.
- Only validator/compiler logic may promote proposals/intermediate artifacts into canonical v2 files.
- Preserve `test/contract.yaml` as a derived compatibility view; `contracts/testcase.yaml` (version 2) is the TestAgent machine source of truth and must not be independently maintained.
- `contracts/testcase.yaml` (version 2) is the TestAgent machine SoT; `test/contract.yaml` is a derived compatibility view only.

## Canonical v2 command checkpoints

After Phase 2 subagents finish and the barrier passes:

```powershell
uo-kb-compile promote "$UO_ROOT" --op-name "$OP_NAME" --phase phase2 --run-id "$RUN_ID"
uo-kb-compile validate "$UO_ROOT" --op-name "$OP_NAME" --phase phase2
```

After Phase 4 kernel raw agents finish and host alignment writes kernel canonical files:

```powershell
uo-kb-compile promote "$UO_ROOT" --op-name "$OP_NAME" --phase phase4 --run-id "$RUN_ID"
uo-kb-compile validate "$UO_ROOT" --op-name "$OP_NAME" --phase phase4
```

After Phase 5 and Phase 7:

```powershell
uo-kb-compile validate "$UO_ROOT" --op-name "$OP_NAME" --phase phase5
uo-kb-compile validate "$UO_ROOT" --op-name "$OP_NAME" --phase phase7
```

Phase 8 runs `quality_gate.py` for final validation. Treat `archive/proposals/*`, `archive/raw_agents/*`, and draft canonical slices as untrusted until these commands pass.
