---
name: bind-init
description: 把绑定拆成怎么跑和列怎么绑两路草稿。repo 已扫完、要开始写 init 草稿时使用。
---

# 分两路绑定

本文件是路由：两路各交什么、什么算混轴、无仓怎么叙事。各轴 HOW 只在该轴窗口打开。本步不写正式 `tg/init.yaml`，不 PASS / REWORK。

无测试仓也两路都跑。`kind=default_input` 不是失败，是「列来自 Host API、没有脚本口径」。有仓却 mapping 空才是失败。

## 输入 / 输出 / 停

读：`repo_scan.yaml`（仓根、入口、表头、`tables[].profile`）。写：两路切片各自的草稿。

- harness → `parts/harness.yaml`
- columns → `parts/bind.yaml`

完成：两份草稿到齐，交给主控裁判。ACK 只认到齐数量。

## 两路各交什么

harness：现有 runner 怎么选 case、golden 怎么比、精度/性能分别怎么跑、现在造得出什么 / 造不出什么。

columns：脚本怎么调算子、API 入参对应哪一列、剩余列 role；shape 列是 range；TilingKey 维用查图覆盖列表。不要把列标成 PR 焦点。

冲突留给主控裁判，本步不合并。

## 常驻判断

两路隔离：harness 不读 bind.yaml，columns 不读 harness.yaml。列值域以 `tables[].profile` 为准，禁止通读 CSV。

无仓时：harness 写明缺口，columns 从 Host API 列变量，不要发明 CSV 列，不要假装 `script_repo`。

有仓则 API 入参 mapping 必须有。用户改过路径则以最新 scan 为准。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| `kind=script_repo` | 两路都按脚本仓写；bind 必须有 mapping |
| `kind=default_input` | 两路都跑；harness 写缺口，columns 用 Host API |
| 某一路想读另一路 YAML | 禁止；冲突留给裁判 |
| 想写正式 `init.yaml` | 禁止；promote 是引擎的事 |

## 指针

- harness 轴 HOW：`references/harness.md`；边角：`references/harness-edge-cases.md`
- columns 轴 HOW：`references/columns.md`；边角：`references/column-binding-edge-cases.md`
- 脚本仓（两路共用）：`references/test-script-repo.md`
- 主控裁判：`references/review.md`
