# 预期外怎么分类

**何时加载**：本轮 Replay 已有跟 `evidence` 对不上的行，要归类、推引理、写下轮构造时。

先切 `TARGET_HIT` / `TARGET_MISS`。命中的进 R，不要进本表。下面只处理 MISS。同一 reject 族或同一 mismatch 维合成一类。一类一条引理。

## 分类桶

| 类 | 怎么认 | 下一步 |
| --- | --- | --- |
| REWRITE | Host 接受但实际 key ≠ 目标 | 写成「若这些控制列则改写到 Q」。下轮按引理改列。 |
| REFUSE | Host 拒绝（有 reject 字符串） | 写成「若 P 则拒绝，原因族 X」。不是 E。 |
| CRASH / NOT_RUN | `HOST_CRASHED` / `NOT_RUN` | 环境。open。 |
| 构造错 | 列填错、recipe 算错、shape 不合法 | 回构造。 |
| evidence 没打到 | 跑了但对不上字段 / 探针 | 仍 `TARGET_MISS`。改列或补探针，不拿 accuracy PASS 顶上。 |
| oracle 错位 | 想用 Host `HIT` 关精度/性能，或缺 harness | `harness_missing` 或去跑 harness。 |
| 未声明态 | Host 产出 `x ∉ D` | 当跨层契约单独报告。 |
| 无关维增长 | 系统性 rewrite 落在变量没点的维 | 停盲搜。用已有观测改控制列。 |

## 从类里推引理

每类最少写：P（控制列 / 入口条件）⇒ Q（`TARGET_HIT` / 改写到某 key / 拒绝）。  
结合 `skills/source-proof/SKILL.md` 查入口与改写点。未找到 ≠ 不存在。

- 能证或能驳 → 更新 worklog 引理段，指导下轮构造
- 窗口不够 → `INSUFFICIENT`，open 写还缺哪段源码或哪次观测
- 只有 Host reject → 不够当源码不可达，也不得抬 E

## 记账红线

R 来自 `TARGET_HIT`（加已点名的 oracle 通过）。target / prediction / 构造意图都不是 R。

E 只来自经审查的源码引理。搜索耗尽、样本缺失、模型分数、单次 `REFUSE` 只能保持 open。`Replay reject ≠ E`。

新 witness 击穿旧 exclusion 时，优先撤销规则，保留 R。

源码或声明变了，旧引理作废，重推。

## 指导下轮

写进 worklog 的下轮指令必须能执行：改哪几列、仍用哪条 evidence、停哪类盲搜。
