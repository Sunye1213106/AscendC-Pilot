# 脚本在这里（给 agent 看）

本目录即 OpenCode / Cursor 安装后的 `SCRIPT_DIR`。

```text
prepare_operator.py
quality_gate.py
review_checkpoint.py
verify_subagent_barrier.py
update_operator.py
```

从任意 `uo-*` skill 解析：

```text
SCRIPT_DIR = <uo-init|uo-query|...>/../understand-operator
```

OpenCode 绝对路径示例：

```text
C:\Users\<you>\.config\opencode\skills\understand-operator\prepare_operator.py
```

**不要**在 `C:\` 上 Recurse 搜索这些文件。详见 `../../prompts/00_path_resolution.md`。
