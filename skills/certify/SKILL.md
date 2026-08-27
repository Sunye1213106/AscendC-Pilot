---
name: certify
description: 在覆盖义务已经 TARGET_HIT 之后，从 init 域与 harness 能力里选精度/性能邻域。不要用于构造未覆盖义务，也不要用 Host HIT 当 oracle PASS。
---

# 命中后邻域

本步发生在 Solve 已经让目标义务 `TARGET_HIT` 之后。不决定测哪些变量，只在合法域里扩 oracle 邻域。

邻域必须来自 `init.yaml` domains、harness 能力与 PR 点名的行为，不要用全局固定取值表。

- 精度：`references/precision-neighborhood.md`
- 性能：`references/performance-neighborhood.md`
