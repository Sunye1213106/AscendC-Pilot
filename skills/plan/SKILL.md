---
name: plan
description: 写出测试用途并融成义务表。init 已有、要规划覆盖时使用。
---

# 规划测试

本文件是路由。`/tg-plan` 两窗先后跑：先用途，再融合。各窗 HOW 只在该窗打开。本步不批准 `plan.md`。

## 两窗各交什么

- scope → `runs/.../plan_scope/parts/purpose.md`：这次测什么、会碰到哪些维/路径、哪些列是编码控制面。不是正式 `plan.md`，没有 YAML 义务表。
- fuse → 计划草稿：上半散文，下半 YAML 义务表。正式文件由 `plan_promote` 写入。没有 purpose → 停，回 scope。

## 常驻判断

缺 `tg/init.yaml` 先 `/tg-init`。scope 窗不要写义务表；fuse 窗不要重做用途调查。精度/性能口径不写进本文件，fuse 点名叠加原语再读。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 想写正式 plan.md YAML 围栏 | 那是 fuse |
| 没有 purpose.md | fuse 停，回 scope |
| 想在本路由里设计阈值 | 禁止 |

## 指针

- scope 窗：`references/scope.md`
- fuse 窗：`references/fuse.md`
- fuse 专表：`references/plan-heuristics.md`、`references/planning-gotchas.md`、`references/planning-context.md`
