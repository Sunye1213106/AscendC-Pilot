# 证明义务如何关闭

**何时加载**：建立或关闭证明义务清单时。

对 `P ⇒ Q`，逐项关闭义务。每项状态：`OPEN | CLOSED | BLOCKED | NA`。一次只证一层：`domain` / `template` / `host` / `kernel`。

```text
OPEN  = 本 claim 适用，但还没证完
NA    = 本 atomic claim 不适用
CLOSED = 已用证据关闭
BLOCKED = 适用，但当前证据闭不上

PROVED ⇒ 所有 applicable 义务 == CLOSED
```

`OPEN` 永远不是「我觉得没必要」。没必要就写 `NA`。

## 入口

- 枚举前提 P 可能形成的所有入口（函数入口、分流第一行、外部 API）
- 每条入口说明：如何满足 P、是否到达结论消费点
- 漏入口 → 不得 `CLOSED`

## 控制流

- 列出相关 guard、dispatch、early return
- 证明在 P 下哪些分支必然/不可能执行
- 函数第一行分流必须检查

## 赋值

- 对结论涉及的每个状态，列出全部 write sites（含间接写）
- 对每个可能推翻 Q 的写入：在 P 下不可达，或写入值仍满足 Q
- 声称写点全集但没有 writer-closure receipt → 该项最多 `BLOCKED`，禁止 `PROVED`
- 局部「此处写入发生」可以把 writes 标 `CLOSED`，completeness 义务用 `NA`

## 调用

- 覆盖跨函数路径：callers / callees / 间接调用目标
- 调用目标未解析 → `BLOCKED` 或继续读源码
- 本 claim 不依赖 call graph → `NA`，不要用 writer-closure receipt 冒充 call 完整性
- call 穷尽依赖 `UO_CALL_CLOSURE_RECEIPT`

## 覆盖

- 结论成立点之后，是否存在相反赋值
- 含「保存—修改—恢复」与别名写

## 替代路径

- 主动寻找 `P ∧ ¬Q` 的合法路径
- 模板/宏/重载/特殊模式若可能改变路径，必须覆盖或声明不足

## 观测绑定

- 若命题来自运行观测（REWRITE/REFUSE），证明须解释该观测：走了哪条入口、为何改写或拒绝
- 禁止把构造器先验拒采写成源码不可达

## 维值 / 组合命题

先用 cover 决定层，再关义务：

- domain：DECL / `declared_coverage` 是否包含被禁值
- template：`product_coverage` / `matching_block_count`。须 `coverage_checked`
- host：赋值函数（不是 packing 那一行）+ early return / `GRAPH_FAILED` + 无后续覆盖 + 替代路径。packing 只证明「Key 槽位读哪个字段」
- kernel：模板实参 / `if constexpr`

组合 cover>0 时，template 义务不得写成「不存在」。漏空 tensor、PREFIX、layout 回写 → 替代路径未关。

## 完整性

下列用语依赖机器 receipt：全部、唯一、从不、没有其他、必然、不可能、不可达。

维值列表看 `dim_coverage` 且 `completeness=coverage_checked`。写点全集看 writer-closure receipt。调用全集看 call-closure receipt。没有 receipt 时：该项 `NA`（若不适用）、继续关闭缺口，或整体 `INSUFFICIENT`。
