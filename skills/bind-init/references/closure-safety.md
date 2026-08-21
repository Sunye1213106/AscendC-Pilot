# Closure Safety

**何时加载**：增长 R/E、解释搜索失败、处理未声明运行态、签发或复用闭环证书时。

## 1. Observation authority

R 只能来自真实 oracle 的**成功观测状态**（命中目标声明态）。

target、prediction、constructed key、模型排序结果都不是 R。

## 2. Negative evidence

下列**不能**证明 unreachable：

- generator failure
- finite search exhaustion
- sample absence
- approximate model prediction
- unsupported predicate
- static-analysis unknown / partial

它们只能产生：`OPEN` / `UNKNOWN` / `LEAD`。

## 3. Exclusion

E 只能来自可审计 proof certificate（源码引理或求解器）。

应用前至少检查：

```text
matched(E) ∩ R = ∅
```

若冲突：优先认为 exclusion 被反例击穿，revoke E，不丢弃 R。

## 4. Undeclared runtime state

若运行成功产生状态 `x`，但 `x ∉ D`：

这是 declaration / extraction / **跨层契约**问题。

禁止：

- 丢弃 `x`
- 强行塞进 `R ∩ D`
- 当搜索噪声忽略

必须单独报告（并可触发审查：`skills/standalone-review/references/cross-layer-contracts.md`）。

## 5. Freshness

source / declaration / oracle / semantic graph 任一关键 fingerprint 改变后：

```text
旧 closure certificate → STALE
```
