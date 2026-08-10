---
name: tg-init
description: >
  TilingKey / TG 初始化语义工作：构建契约、语义绑定、初始化审计、
  以及人工确认边界。不描述 Pilot 阶段机。
---

# TG 初始化

目标：在求解前得到**范围清楚、契约可检查、绑定有证据**的 TG 初始状态。

## 核心循环

```text
明确意图与模式
 ↓
检查 KB 前置
 ↓
构建 / 核对契约
 ↓
语义绑定
 ↓
审计缺口
 ↓
人工确认（仅当需要）
```

## 契约

- 权威是 CodeMap `.uo`；`declared_set` 来自 view_blob `tiling/exhaustive_key_space`（TPL ARGS_SEL 展开的 D）
- 契约应列出求解所需维度、约束、消费方期望
- 字段含义与单位必须有源码或 CodeMap 锚点（禁止无证据的「看起来像」）
- 不完整契约不得假装可求解

细节：`references/contract.md`

## 语义绑定

- 将契约符号绑定到 KB/源码实体
- 歧义 overload / 模板实例必须显式消解或标 unresolved
- 禁止无证据的「看起来像」绑定

细节：`references/binding.md`

## 审计

- 列出阻断求解的缺口（缺字段、缺绑定、缺 oracle 前提）
- 区分：可自动修 / 需人确认 / 需回 UO 补库

## 人工确认

- 只确认机器无法安全决定的边界（范围、模式、例外）
- 不把确认当成跳过证据的许可证
