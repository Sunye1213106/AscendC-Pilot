---
name: tg-plan
description: >
  TG 测试计划：把用户目标解析成不可变的 TilingKey 目标集合 T，并批准给 tg-solve。
  未指定目标时默认 T=全部源码声明 TilingKey；用于 plan-intent / plan-build / plan-approve。
---

# TG Plan：只决定“要解哪些 case”

Plan 不构造 case、不跑 Host、不证明不可达。它只把求解边界冻结下来。

## 集合定义

- `D`：当前 Kernel template 源码声明的全部 legal packed TilingKey。
- `T`：本次批准计划要闭合的目标集合，必须满足 `T ⊆ D`。
- 默认：用户没有指定目标时，`T = D`。

显式目标支持两种形式：

1. `explicit_keys`：指定 packed TilingKey 列表；
2. `dimension_filter`：指定维度条件，例如 `IsTnd=1, InputDType∈{2,3}`，由确定性脚本在 D 上过滤得到 T。

## Plan 流程

```text
intent
  ↓ 读取用户目标；无目标 => all_declared
scope
  ↓ 固定 operator / arch / level
precheck
  ↓ .uo 与当前 Kernel schema 可用
build
  ↓ 枚举 D，解析 selector，写 target_set.yaml
approve
  ↓ 批准 target_hash + plan_hash
```

## 必须产出

`tg/plan/levels/<level>/target_set.yaml`：

- `target_mode`
- `selector`
- `keys`
- `count`
- `declared_count`
- `target_hash`
- `.uo` identity / snapshot hash
- `plan_hash`

`coverage_obligations.yaml` 只描述 T 的闭环义务：

```text
T = (R ∩ T) ∪ E
R ∩ E = ∅
```

其中 R/E 的含义由 `tg-solve` 保证。

## 批准规则

- T 非空且完全属于当前 D；
- selector 与实际 keys 一致；
- `target_hash`、`.uo` snapshot、`plan_hash` 可复验；
- approve 后 Solve 不得扩大 T；要改目标必须重新 Plan/Approve；
- Plan 里禁止写“SAT 已解”“Key 不可达”等 Solve 结论。

## 结果

- **APPROVE**：目标集身份完整，可交给 `tg-solve`；
- **REVISE**：目标/selector 需要修改；
- **BLOCKED**：`.uo`、Kernel schema 或目标合法性不足。
