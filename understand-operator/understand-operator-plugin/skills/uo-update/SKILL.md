---
name: uo-update
description: >-
  Recognize /uo-update and explain that incremental updates are currently disabled.
disable-model-invocation: true
argument-hint: "[path] [--op-name <name>]"
---

# uo-update

当前 Facts / Raw Graph / Derived Graph 结构尚未实现可靠的增量更新。
本技能不执行任何文件读取、写入、刷新、编译或迁移命令。

当用户运行 `/uo-update` 时，只返回：

```text
当前版本不支持增量更新，请重新运行 /uo-init 创建新的 Run。
```

不要在本技能中实现新的增量更新算法。
