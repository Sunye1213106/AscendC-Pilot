# 路径解析（强制）— 禁止全盘搜索

OpenCode / Cursor 把 skill 装成 junction 后，agent 常误判「本机没有 prepare_operator」，然后去扫 `C:\` —— **绝对禁止**。

## 禁止

```text
Get-ChildItem C:\ -Recurse -Filter prepare_operator*
在整个磁盘 / 整个 PR-review 树里盲搜 understand-operator-plugin
因为「找不到脚本」就去读算子 op_kernel 目录猜结构
```

脚本**一定在** skill 旁，不在算子仓库里，也不在 `C:\` 根下。

## 变量怎么算（按顺序，命中即停）

设本 skill 目录为 `THIS_SKILL`（含当前 `SKILL.md` 的目录，可为 junction）。

### 1) SCRIPT_DIR（共享脚本，含 prepare_operator.py）

按顺序试，**第一个存在 `prepare_operator.py` 的目录**即为 `SCRIPT_DIR`：

1. `THIS_SKILL/../understand-operator`  
   （OpenCode：`~/.config/opencode/skills/uo-init` → `~/.config/opencode/skills/understand-operator`）
2. `THIS_SKILL/../../skills/understand-operator`  
   （源码树：`.../understand-operator-plugin/skills/uo-init` → `.../skills/understand-operator`）
3. 若 `THIS_SKILL` 本身就是 `understand-operator` skill：`THIS_SKILL`

PowerShell 一行校验（**只查这几处，禁止 Recurse 全盘**）：

```powershell
$skill = "<THIS_SKILL 绝对路径>"   # 含 SKILL.md 的目录
$candidates = @(
  (Join-Path $skill "..\understand-operator"),
  (Join-Path $skill "..\..\skills\understand-operator"),
  $skill
) | ForEach-Object { (Resolve-Path $_ -ErrorAction SilentlyContinue).Path }
foreach ($d in $candidates) {
  if ($d -and (Test-Path (Join-Path $d "prepare_operator.py"))) {
    Write-Host "SCRIPT_DIR=$d"
    break
  }
}
```

OpenCode 已正确安装时，通常直接是：

```text
C:\Users\<you>\.config\opencode\skills\understand-operator\prepare_operator.py
```

### 2) PLUGIN_ROOT / PROMPT_DIR

按顺序试，**第一个存在 `prompts/00_cbm_first_rule.md` 的目录**即为 `PLUGIN_ROOT`：

1. `~/.config/opencode/understand-operator-plugin`（OpenCode 安装后 plugin junction）
2. `~/.cursor/understand-operator-plugin`（Cursor skills 安装后）
3. `~/.agents/understand-operator-plugin`（Codex 安装后）
4. `SCRIPT_DIR/../..` 若存在 `prompts/00_cbm_first_rule.md`（源码树：`understand-operator-plugin`）
5. 否则 `THIS_SKILL/../..`（源码树 `skills/uo-init` 的上两级）

`PROMPT_DIR` = `$PLUGIN_ROOT/prompts`

### 3) PROJECT_ROOT

用户参数路径，或含 `op_host/` / `op_kernel/` 的算子仓库根。  
**不是** `~/.config/opencode`，**不是** understand-operator 插件目录。

### 4) UO_ROOT

`$PROJECT_ROOT/.understand-operator/$OP_NAME`

## 找不到时怎么办

1. 只检查上面 3 个 candidate，打印它们是否存在  
2. 提示用户在 understand-operator 仓库根执行：`./install.ps1 opencode`  
3. **停止**，不要 `Get-ChildItem C:\ -Recurse`

## 安装后应有的布局

```text
~/.config/opencode/
  opencode.json            # permission.question: "allow"（human review 按钮 UI）
  understand-operator-plugin/   → junction → .../understand-operator-plugin
    prompts/00_review_menu.md
    prompts/01a_macro_scope_human_review.md
    agents/uo-*.md
  skills/
    uo-init/                 → junction → .../skills/uo-init
    uo-query/
    uo-update/
    uo-diff/
    understand-operator/     → junction → .../skills/understand-operator
      prepare_operator.py
      quality_gate.py
      review_checkpoint.py
      verify_subagent_barrier.py
      update_operator.py
```
