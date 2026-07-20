# Testcase Agent

TestAgent for Understand Operator contracts. Public commands:

- `tg-contract`: scan `--test-script-root` → `realization/` contract (headers + `VAR_CSV_*` map).
- `tg-plan`: requires 算子仓 + (**测试工具** auto-contract | **`--contract-root`** reuse); then L0–L3 plan filtered by CSV reachability.
- `tg-solve`: after approval, SMT on `VAR_CSV_*` free vars → project model to CSV rows.

`tg-init` is deprecated (intake is part of `tg-contract` / `tg-plan`).

Planning levels:

- `L0`: functional-attribute smoke — every independent feature attribute (families, paths, dtype/layout, optional inputs, tiling-key field values) gets at least one witness. Not a single minimal case.
- `L1`: reachable runtime branches / functional coverage / boundaries / rejects.
- `L2`: exhaustive reachable TilingKey coverage.
- `L3`: topic-scoped custom suite (e.g. `--topic determinism`).

Plan outputs:

- `plan/review.md` — human review with level design, test-point counts (覆盖什么/多少条)
- `plan/levels/<L0|L1|...>/` — per-level archive so L0/L1 do not overwrite each other
- `plan/human_supplement.yaml` — approve binding snapshot_hash + plan_hash

## 安装到 OpenCode（与 understand 相同方式）

在 **`testcase-agent/`** 目录下执行：

```powershell
./install.ps1 opencode
```

会创建：

- `~/.config/opencode/skills/tg-plan` / `tg-solve` / `tg-init` → 本目录 `skills/`
- `~/.config/opencode/testcase-agent-plugin` → **本目录（PLUGIN_ROOT）**
- 并 `pip install -e ".[solver]"`（可用 `-SkipPip` 跳过）

卸载：

```powershell
./install.ps1 -Uninstall opencode
```

Linux / macOS：

```bash
chmod +x ./install.sh
./install.sh opencode
# SKIP_PIP=1 ./install.sh opencode
```

在 `~/.config/opencode/opencode.json` 中允许人工确认：

```json
{
  "permission": {
    "question": "allow"
  }
}
```

路径说明见 [`skills/PATHS.md`](skills/PATHS.md)。

### 安装到 Cursor（可选）

```powershell
./install.ps1 cursor
```

或 Settings → Plugins → Add local plugin → 选择本目录。

## 使用

`<project_root>` 为算子包目录（含已构建的 `.understand-operator/<op_name>/`）。
也可传 KB 路径；`--test-script-root` 为测试工程（CSV consumer）。

`tg-plan` 输入：**算子仓 +（测试工具 | contract 产物）**。缺了就失败并要求补齐。

```powershell
# 测试工具 → 自动 contract + plan
tg-plan <project_root> --op-name <op_name> --level L0,L1 --test-script-root <test_tool_root>

# 或复用已有 contract 产物
tg-plan <project_root> --op-name <op_name> --level L0,L1 --contract-root <realization_dir>

# OpenCode AskQuestion: approve（立即 tg-solve）/ reject / suggest
tg-solve <project_root> --op-name <op_name> --level L1
```

仅刷新 contract（不要 plan）时：

```powershell
tg-contract <project_root> --op-name <op_name> --test-script-root <test_tool_root>
```

LLM 仅补全低置信 extract gaps（`extract/llm_patches.yaml`）。高置信路径零 LLM。

手动开发态安装：

```powershell
pip install -e ".[solver]"
```
