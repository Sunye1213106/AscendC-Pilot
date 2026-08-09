---
name: source-lemma-proof
description: >
  基于代码知识库、Codemap 与源码证明或反驳程序语义命题。
  当任务需要证明某条件必然导致某结果、某状态不可出现、某字段只能取特定值，
  或需要为静态分析结论建立可审计源码证据时使用。
---

# 源码引理证明

针对一个明确的程序语义命题，建立可审计的源码证明。

目标不是寻找「支持这个结论的代码」，而是回答：

> 在给定前提下，是否存在任何合法执行路径可以推翻这个结论？

最终只允许三种结果：

```text
PROVED        源码足以证明
REFUTED       找到合法反例
INSUFFICIENT  当前证据不足
```

## 核心原则

```text
命题
 ↓
分解证明义务
 ↓
定位相关程序状态
 ↓
验证控制流与数据流
 ↓
主动寻找反例
 ↓
PROVED / REFUTED / INSUFFICIENT
```

模型预测、搜索失败、历史未出现、测试覆盖不足，都不能证明程序状态不可达。

**未找到 ≠ 不存在。**

## 1. 明确命题

把任务整理成 `前提 P ⇒ 结论 Q`。命题必须可映射到变量、状态、分支或调用行为。优先证明最小命题。

若原始命题含糊，先明确：前提、结论、涉及哪些程序状态、要求局部成立还是所有路径成立。

## 2. 建立证明义务

默认检查：

```text
入口       前提可能从哪些入口形成
控制流     guard、dispatch、early return 是否完整
赋值       相关状态由哪些位置定义或修改
调用       关键跨函数路径是否被覆盖
覆盖       是否存在后续赋值推翻结论
替代路径   是否存在产生相反结果的合法分支
观测绑定   若命题来自运行观测，源码是否解释该观测
完整性     「全部/没有/不可能」等结论是否有完整分析支撑
```

每项标记为 `OPEN | CLOSED | BLOCKED`。存在必要的 `OPEN` 或 `BLOCKED` 时，不得返回 `PROVED`。

复杂义务关闭法：`references/proof-obligations.md`

## 3. 先查询结构，再阅读源码

优先使用 KB / Codemap：`definition` `writers` `readers` `guards` `callers` `callees` `roots` `path` `source` `completeness`。

```text
结构查询 → 最小相关路径 → 阅读对应源码 → 验证结构关系
```

若查询结果为 `partial`，不得根据缺失结果证明「不存在」。

## 4. 追踪决定性状态

对关键变量：定义与来源 → 赋值点 → 各赋值点 guard → 必要调用 → early return / dispatch → 后续覆盖 → 结论消费点。

找到一条支持路径后不要立即停止；证明需要排除能推翻结论的合法路径。

## 5. 选择证明方式

### 条件蕴含

`P → guard 固定 → 分支必然执行 → 状态确定 → Q`（仍须检查后续覆盖）

### 完备赋值分析

所有相关写入在 P 下固定为目标值或被 guard 排除，且无后续相反写入。仅当写入集合足够完整时可用。

### 路径不可满足

假设 `P ∧ ¬Q` 导出矛盾控制条件。若用求解器，结论须绑定正确源码变量与路径条件。

## 6. 主动寻找反例

证明完成前必须从反方向检查：其他入口、分流、early return、间接调用、重载/模板、宏、特殊模式、其他赋值点、保存—修改—恢复、后续覆盖、alias。

找到一条合法路径满足前提但得相反结论 → `REFUTED`。

## 7. 检查完整性

「全部 / 唯一 / 从不 / 没有其他 / 必然 / 不可能 / 不可达」依赖完整性。调用闭包、写入集合、宏上下文、模板实例、alias 不完整时：继续读源码关闭缺口，或返回 `INSUFFICIENT`。

## 8. 形成结论

- **PROVED**：必要义务全关、源码推理链完整、无有效反例、完整性足够
- **REFUTED**：合法源码路径或可靠运行反例；指出反例条件 → 路径 → 相反结果
- **INSUFFICIENT**：明确缺什么，不要猜

## 9. 输出证明摘要

```yaml
claim:
  premise: ...
  conclusion: ...
obligations:
  entry: CLOSED | OPEN | BLOCKED
  control: CLOSED | OPEN | BLOCKED
  writes: CLOSED | OPEN | BLOCKED
  calls: CLOSED | OPEN | BLOCKED
  overwrite: CLOSED | OPEN | BLOCKED
  alternatives: CLOSED | OPEN | BLOCKED
  completeness: CLOSED | OPEN | BLOCKED
result: PROVED | REFUTED | INSUFFICIENT
reasoning: [...]
evidence:
  - source: <file:line>
    role: ...
counterexample:
  checked: true
  result: none | <反例>
```

序列化 Schema 由调用方定义。

## 按需参考

- `references/proof-obligations.md`
- `references/cpp-semantics.md`
- `references/proof-certificate.md`
- `references/referee-replay.md`（裁判角色）
- `references/examples.md`
