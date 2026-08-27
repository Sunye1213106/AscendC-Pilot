---
name: bind-init
description: 把绑定拆成怎么跑和列怎么绑。repo 已扫完、要开始写 init 草稿时使用。
---

# 分路绑定

本 Action 负责写出 harness 与 columns 草稿。禁止混轴：harness 不读 bind.yaml，columns 不读 harness.yaml。代码访问遵守 `code-access`（算子语义先 `uo-query`，源码只核对卡片窗口）。本 Skill 不另定访问策略。

Host 按表头把列切成每路 ≤20：1 路 harness + N 路 bind。主控同一条回复里并行原生 Task 子代理（共享父对话，切片 FOCUS 隔离）；不要改路数、不要等一个完成再派下一个、不要开新对话。引擎合并 `harness.yaml` 与全部 `bindN.yaml` → `bind.yaml`。`inspect yaml` 过了只说明能合并。

- harness 轴：`references/harness.md`；边角：`references/harness-edge-cases.md`
- columns 轴：`references/columns.md`；边角：`references/column-binding-edge-cases.md`
- 两路共用：`references/test-script-repo.md`
- 裁判文：`references/review.md`（只由裁判 Action 装，不进切片窗）
