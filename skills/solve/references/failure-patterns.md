# 预期外怎么分类

**何时加载**：本轮 Replay 已有跟预期不一样的行，要归类、推引理、写下轮构造时。

先切「一样 / 不一样」。一样的进 R，不要进本表。下面只处理不一样的。同一 reject 族或同一 mismatch 维合成一类。一类一条引理，不要一行一条「感觉」。

## 分类桶

| 类 | 怎么认 | 下一步 |
| --- | --- | --- |
| REWRITE | Host 接受但实际 key ≠ 目标 | 写成「若这些控制列则改写到 Q」。推入口 / 改写条件。下轮按引理改列，不要重复同一 mutation。 |
| REFUSE | Host 拒绝（有 reject 字符串） | 写成「若 P 则拒绝，原因族 X」。解释入口。不是 E。 |
| CRASH / NOT_RUN | `HOST_CRASHED` / `NOT_RUN` | 环境。open。禁止当负样本、禁止写 E、不是 golden 失败。 |
| 构造错 | 列填错、recipe 算错、shape 不合法 | 回构造。不要推「源码不可达」。 |
| oracle 错位 | 想用 Host HIT 关 `P-*` / `F-*`，或缺 harness | `harness_missing` 或去跑 harness。HIT 只对 dispatch/key。 |
| 未声明态 | Host 产出 `x ∉ D` | 单独报告，当跨层契约，不要投影回 D 当普通 miss。 |
| 无关维增长 | 系统性 rewrite 落在义务没点的维 | 停盲搜。用已有观测 + 源码改控制列。 |

## 从类里推引理

每类最少写：P（控制列 / 入口条件）⇒ Q（HIT 到某 key / 改写到某 key / 拒绝）。  
结合 `skills/source-proof/SKILL.md` 查入口与改写点。未找到 ≠ 不存在。

- 能证或能驳 → 更新 worklog 引理段，指导下轮构造
- 窗口不够 → `INSUFFICIENT`，open 写还缺哪段源码或哪次观测
- 只有 Host reject → 不够当源码不可达，也不得抬 E

推完立刻写进 worklog，不要等「搜索耗尽」才想起引理。

## 记账红线

**不要把预测写进 R。** R 只能来自真实 oracle 的成功观测（dispatch/key 的 HIT，或 harness 通过）。target / prediction / 构造意图都不是 R。

**不要把负证据直接抬 E。** 搜索耗尽、样本缺失、模型分数、单次 Replay reject 只能保持 open。`Replay reject ≠ E`。E 只能来自经审查的源码引理。

**新 witness 击穿旧 exclusion 时，优先撤销规则，保留 R。** 不要删观测来保住旧引理。

**源码或声明变了，旧引理作废，重推。** 不要继承过期结论。

## 指导下轮

写进 worklog 的下轮指令必须能执行：改哪几列、用什么 recipe、停哪类盲搜。  
写不清「还缺什么 / 下一轮试什么」，分类等于没做。
