---
name: tg-init
description: >-
  Initialize testcase-generator context from understand-operator KB.
  Use when the user runs /tg-init or asks to start test generation for an operator.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# tg-init — 初始化测试生成上下文

对齐 ST「输入文件校准」：校验 understand KB，而不是 aclnn 文档。

## Variables

见 `prompts/00_path_resolution.md`。`SCRIPT_DIR` = 同级 `testcase-generator` skill。

## 必须存在的 KB 文件

```text
quality.yaml
tiling/key_space.yaml
tiling/families.yaml
tiling/data_model.yaml
tiling/coverage_model.yaml
```

缺文件 → 停止，提示先 `/uo-init` 或 `/uo-update`。不要自行读源码猜测。

## 流程

```powershell
python "$SCRIPT_DIR/tg_init.py" "$PROJECT_ROOT" --op-name "$OP_NAME"
```

输出 `kb_snapshot.yaml`、`route.md`。

映射说明见 `references/st-alignment.md`、`references/artifact-map.md`。
