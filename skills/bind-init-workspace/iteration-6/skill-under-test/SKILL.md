---
name: bind-init
description: 把绑定拆成怎么跑和列怎么绑。repo 已扫完、要开始写 init 草稿时使用。
---

# 分路绑定

本目录是 family manifest，不是某一轴的 HOW。禁止混轴：harness 不读 bind.yaml，columns 不读 harness.yaml。代码访问遵守 `code-access`（优先 uo-query；已有明确 file_path 可 Read；空图须回退定向阅读）。本 Skill 不另定访问策略。

Host 按表头把列切成每路 ≤20：1 路 harness + N 路 bind。Primary 原样派 `dispatch_tasks`，不要自己改路数。引擎合并 `harness.yaml` 与全部 `bindN.yaml` → `bind.yaml`。`inspect yaml` 过了只说明能合并。

查图只用 `pilot_cli uo-query`。无参一次只认开关维。尺寸列用**列名**查，取 `TILING_FIELD` 的 `.name`；不要拿 `dim_names` 当查询词。标量 kwargs 的 source 列 `uo.id` 必须等于该 `call_args.name`；inspect 前按 call_args 回扫，空 id 不许停。

- harness 轴：`references/harness.md`；边角：`references/harness-edge-cases.md`
- columns 轴：`references/columns.md`；边角：`references/column-binding-edge-cases.md`
- 两路共用：`references/test-script-repo.md`
- 裁判文：`references/review.md`（只由裁判 Action 装，不进切片窗）
