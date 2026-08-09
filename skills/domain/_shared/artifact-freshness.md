# 产物新鲜度

**何时加载**：打算复用旧证明证书、旧 R/E、旧投影/索引、旧审查结论时。

## 规则

结论 C 依赖：

```text
source revision
semantic graph / fingerprint
build context
declaration schema
oracle / protocol semantics
```

任一**决定其语义**的 fingerprint 改变：

```text
C → STALE
```

不得静默继承 STALE 结论。

## 各域用法

| Domain | STALE 意味着 |
|---|---|
| source-lemma-proof | 旧 proof certificate 不可直接 accept |
| tg-closure | 旧 R/E / closure certificate 须重算或重审 |
| uo-kb-build | 旧 projection/index 须重建或标过期 |
| code-review | 旧 finding 须对照当前 revision 复核 |
