---
name: solve
description: 按已批准计划构造用例并对照 Replay 写 worklog。plan 已批准、要求解时使用。
---

# 求解

本文件是路由。`/tg-solve` 两窗先后跑：先构造，再对照。各窗 HOW 只在该窗打开。本步不签发闭合。

## 两窗各交什么

- construct → 脚本能吃的草稿行。不写 `worklog.md` 文首 `open:`，不签发。
- analyze → worklog 草稿：进 R / 仍 open、分类、引理、下轮改哪几列。不改 cases 表。

## 常驻判断

没有批准计划 → 停。construct 窗不要「先切两堆」；analyze 窗不要改构造表。精度/性能/引理只在点名后读叠加原语。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| 想签发闭合 | 禁止；open 非空保持 open |
| 构造窗想写 open: | 那是 analyze |
| 分析窗想改 cases | 回 construct |

## 指针

- construct 窗：`references/construct.md`；定向表：`references/targeted-construct.md`
- analyze 窗：`references/analyze.md`；分类表：`references/failure-patterns.md`
