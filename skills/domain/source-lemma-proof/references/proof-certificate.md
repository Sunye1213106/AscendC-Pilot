# 证明证书

Producer 产出可被裁判 replay 的证书。语义结论只有：

```text
PROVED | REFUTED | INSUFFICIENT
```

工作流层可将 `PROVED` 映射为可应用规则等级；Producer **不**自行决定是否写入排除集。

## 合格证书最低字段

```yaml
claim:
  premise: ...
  conclusion: ...
result: PROVED | REFUTED | INSUFFICIENT
obligations: { ... }   # 见 SKILL
reasoning:
  - step: ...
    cites: [EV_..., file:line]
evidence:
  - id: EV_...
    source: file:line
    role: ...
counterexample:
  checked: true
  result: none | { condition, path, opposite }
completeness:
  writers: full | partial
  calls: full | partial
  macros: full | partial | unknown
```

## 写作标准（对应三种形态）

1. **后续赋值被 guard 排除**：列全赋值点；说明每个对立写入被何 guard 挡住。
2. **析取取一支**：写明取哪支、另支为何不成立、取值如何存活到消费点。
3. **条件区间重叠固定对**：两边赋值与返回均引用；证明前提同时成立。

只贴 `file:line` 不够——必须有推理链 + 无后续覆盖。

## 与观测的关系

有证据包时，五检查引用的位点应以包内 `EV_…` 为可引用集合。无观测事实不得声称运行时不可达。
