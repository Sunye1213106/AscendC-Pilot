# 脚本在这里（给 agent 看）

本目录即 OpenCode / Cursor 安装后的 `SCRIPT_DIR`。

```text
prepare_operator.py
quality_gate.py
review_checkpoint.py
verify_required_subagents.py
prepare_fact_file.py
validate_candidate_batch.py
compile_candidate_facts.py
evaluate_review_trigger.py
validate_spec_consistency.py
validate_fact_stage.py
build_fact_registry.py
build_query_index.py
verify_required_scripts.py
build_compile_gate.py
source_graph_compiler.py
materialize_derived_graph.py
uo_query_readonly.py
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
