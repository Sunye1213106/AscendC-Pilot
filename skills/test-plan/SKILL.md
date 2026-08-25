---
name: test-plan
description: 把测试要求编译为 Target、Dimension、Guard 与 L0–L3 覆盖义务。init 已有、要规划覆盖时使用。
---

# 白盒测试规划

本目录是 family manifest，不是某一窗的 HOW。Primary 原生 `Task(agent=tg-analyst)` 派 **一个 Plan Owner**：同一窗完成「测什么」+ Coverage IR，只交 YAML。Host 不发 model 阶 ticket。Engine 确定性 narrate 三节散文并写入 `tg/plan.md`。

## 快速诊断

路径合取项 → **取反后 Target.expected 还能被别的析取支打到？**

```
能 → Dimension（切臂/切值，两格都是可达 ON）
不能 → Guard（关断整个 Target；probe 杀整 Target 时用驱动列，勿用 constraints 代替 L3）
同一层 `||` 的两支 → **同一个** Dimension 的两格（互斥 ON）。不同层 `||` / 不同 helper 才各自成维
多值字段 → Target 用 `derived`+`in`；Dimension 每值 `eq` 一格（禁止 replay_field expected 列表 / 拆 Target / ne 第二格）
所有 partition 都成立的派生等式 → constraints（不得钉 Guard/Dimension 列）
核数/平台字面量 → environment（必须有 file:line）
可切 probe 做 Dimension（classifier=`probe.<name>`），不要丢进 constraints
unresolved+active 列 → untestable 点名
packet 文件里的新赋值优先于 UO 空结果（count:0 不是不存在）
packet.identifiers 非空 → Target 只点名其中的新赋值（默认 1 个 Target）
L1 先做 2×2：helper 只杀一支就不要和切臂维交叉
constraints 默认 []；早退合取不要把单因子枚举写成 Guard
H6：各 partition 谓词字段集合必须相等（多出来的列补 HIT 合法值，禁止换一组列）
controls 不算切到；token 列必须出现在两格谓词里
requirement.text 用 ASCII 写杀整事实（`g==1`/`g<=1`，不要 `≤`）
仍 HIT 的默认枚举必须有 partition `eq`；`in` values 禁止重叠
helper 初值/候选/合取布尔要在 requirement.text 点名
两臂 splitAxis / isDeterministic 互斥 → 耦合列写进该维两格，勿全局钉死一侧
```

详情与骨架：`references/coverage-planning.md`。

- 测什么（四项必答）：`references/target-planning.md`
- 覆盖模型 YAML：`references/coverage-planning.md`；观测种类：`references/evidence.md`
- 散文由 Engine `render_plan_prose` 生成；`references/plan-narrate.md` 仅作历史说明
