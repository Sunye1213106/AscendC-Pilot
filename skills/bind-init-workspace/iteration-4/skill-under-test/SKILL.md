---
name: bind-init
description: 把绑定拆成怎么跑和列怎么绑两路草稿。repo 已扫完、要开始写 init 草稿时使用。
---

# 分两路绑定

本目录是 family manifest，不是某一轴的 HOW。禁止混轴：harness 不读 bind.yaml，columns 不读 harness.yaml。查图只用 `pilot_cli uo-query`，不能用索引文件、头文件或源码阅读代替。

- harness 轴：`references/harness.md`；边角：`references/harness-edge-cases.md`
- columns 轴：`references/columns.md`；边角：`references/column-binding-edge-cases.md`
- 两路共用：`references/test-script-repo.md`
- 裁判文：`references/review.md`（只由裁判 Action 装，不进切片窗）
