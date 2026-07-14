---
name: uo-update
description: >-
  Recognize /uo-update and explain that incremental updates are currently disabled.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# uo-update

当前 Facts / Raw Graph / Derived Graph 结构尚未实现可靠的增量更新。

禁止执行旧 canonical v2 更新流程，禁止创建、读取或刷新：

- `index.yaml`
- `route.md`
- `archive/runs`
- `tiling/*`
- `flow/*`
- `kernel/paths.yaml`
- `test/contract.yaml`
- `cross_layer/*`
- `impact_graph`
- `contracts/*`
- `uo-kb-compile promote`

当用户运行 `/uo-update` 时，只返回：

```text
当前版本不支持增量更新，请重新运行 /uo-init 创建新的 Run。
```

不要在本技能中实现新的增量更新算法。
