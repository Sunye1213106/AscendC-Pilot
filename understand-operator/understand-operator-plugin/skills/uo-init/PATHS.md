# uo-init 脚本路径（禁止全盘搜索）

共享脚本不在本目录，在**同级** `understand-operator` skill：

```text
THIS_SKILL = .../skills/uo-init          （本 skill）
SCRIPT_DIR = .../skills/understand-operator
脚本       = SCRIPT_DIR/prepare_operator.py
```

OpenCode 安装后（junction）：

```text
%USERPROFILE%\.config\opencode\skills\uo-init\
%USERPROFILE%\.config\opencode\skills\understand-operator\prepare_operator.py
```

Phase 0 推荐直接跑（把 `<USER>` / 算子路径换成实际值）：

```powershell
$SCRIPT_DIR = "$env:USERPROFILE\.config\opencode\skills\understand-operator"
Test-Path "$SCRIPT_DIR\prepare_operator.py"   # True
python "$SCRIPT_DIR\prepare_operator.py" "<PROJECT_ROOT>" --op-name "<OP_NAME>"
```

若 `Test-Path` 为 False：在 understand-operator 仓库执行 `./install.ps1 opencode`，**不要** `Get-ChildItem C:\ -Recurse`。

详见 `../../prompts/00_path_resolution.md`（源码树）或安装后 `SCRIPT_DIR\..\..\prompts\00_path_resolution.md`。
