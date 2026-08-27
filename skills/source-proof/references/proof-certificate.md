# 证明证书

**何时加载**：准备写出 PROVED/REFUTED/INSUFFICIENT 证书时。这是唯一证书形状。

Producer 产出可被独立审证 replay 的证书。语义结论只有：

```text
PROVED | REFUTED | INSUFFICIENT
```

机器合同：`schemas/source-proof/certificate-v1.yaml`。本步不写 exclusion。`full` 跨层事实由引擎合成，证书 `claim.layer` 不得填 `full`。

## 证书字段

```yaml
schema: source-proof/v1
claim:
  layer: domain | template | host | kernel
  premise: ...
  conclusion: ...
coverage:
  declared: [...]
  product: [...]
  completeness: coverage_checked | first_hit | unknown
obligations:
  entry: CLOSED | OPEN | BLOCKED
  control: CLOSED | OPEN | BLOCKED
  writes: CLOSED | OPEN | BLOCKED
  calls: CLOSED | OPEN | BLOCKED
  overwrite: CLOSED | OPEN | BLOCKED
  alternatives: CLOSED | OPEN | BLOCKED
  completeness: CLOSED | OPEN | BLOCKED
result: PROVED | REFUTED | INSUFFICIENT
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
  writers:
    status: full | partial | unknown
    source: UO_WRITER_CLOSURE_RECEIPT | SOURCE_CLOSURE_RECEIPT | PRODUCT_COVERAGE_RECEIPT | ""
  calls:
    status: full | partial | unknown
    source: UO_WRITER_CLOSURE_RECEIPT | SOURCE_CLOSURE_RECEIPT | PRODUCT_COVERAGE_RECEIPT | ""
  macros:
    status: full | partial | unknown
    source: PRODUCT_COVERAGE_RECEIPT | ""
```

`completeness.*.status: full` 必须带非空 `source`，且该 source 是机器 receipt。没有 receipt 最多 `partial` / `unknown`。声称「全部 / 唯一 / 从不 / 不可达」却没有 full receipt → 不得 `PROVED`。

## 写作标准

1. **后续赋值被 guard 排除**：列全赋值点；说明每个对立写入被何 guard 挡住。
2. **析取取一支**：写明取哪支、另支为何不成立、取值如何存活到消费点。
3. **条件区间重叠固定对**：两边赋值与返回均引用；证明前提同时成立。

只贴 `file:line` 不够——必须有推理链 + 无后续覆盖。

## 与观测的关系

有证据包时，引用位点应以包内 `EV_…` 为可引用集合。

缺少 runtime 观测永远不能当成不可达证明。完整的静态证明（义务关闭且 completeness 有 receipt）可以在没有 runtime witness 的情况下证明运行时不可达。
