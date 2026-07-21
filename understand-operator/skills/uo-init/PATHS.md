# uo-init 脚本路径（禁止全盘搜索）

```text
PLUGIN_ROOT = .../understand-operator          （仓库根 = 插件根）
SCRIPT_DIR  = $PLUGIN_ROOT/uo/scripts
# Query CLI (uo-query): $SCRIPT_DIR/uo_kb_query.py
# Do not use skills/uo-query/scripts/ as primary (forwarder only).
PROMPT_DIR  = $PLUGIN_ROOT/prompts
```

OpenCode 安装后：

```text
%USERPROFILE%\.config\opencode\understand-operator-plugin\   → PLUGIN_ROOT
%USERPROFILE%\.config\opencode\skills\uo-init\               → skills/uo-init
```

推荐：

```powershell
$PLUGIN_ROOT = "$env:USERPROFILE\.config\opencode\understand-operator-plugin"
$SCRIPT_DIR  = "$PLUGIN_ROOT\uo\scripts"
Test-Path "$SCRIPT_DIR\prepare_operator.py"   # True
python "$SCRIPT_DIR\prepare_operator.py" "<PROJECT_ROOT>" --op-name "<OP_NAME>"
```

若 `Test-Path` 为 False：在仓库根执行 `./install.ps1 opencode`，**不要**全盘搜索。

详见 `../../prompts/00_path_resolution.md`。
