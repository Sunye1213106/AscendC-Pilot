# 静态证据怎么读

**何时加载**：手中有字段级静态分析 / derivation 探针输出（expression、domain、roots、def_sites、guards 等）时。

静态包是**探针摘要**，不是契约；真值以源码与正式 IR/检查为准。

## 证据包字段语义

```text
field
├─ expression     候选数据流摘要（不是证明本身）
├─ domain         可能值集合（≠ 可达值集合）
├─ roots          最终受哪些外部输入影响
├─ definition sites  证明入口（优先从这里读源码）
├─ guards         路径条件
├─ unresolved / free vars  证明义务仍未关闭
└─ completeness   该包对「全部」类结论是否足够
```

## 解读纪律

| 字段 | 正确用法 | 错误用法 |
|---|---|---|
| expression | 缩小阅读范围 | 当最终证明 |
| def_sites | 证明入口与写点枚举起点 | 忽略只读表达式 |
| guards | 构造路径条件 | 漏 early return / 第一行分流 |
| roots | 绑定输入/属性前提 | 当成已证明可达 |
| undecided / free vars | 保持 OPEN/BLOCKED | 假装已闭合 |
| domain | 候选值上界 | **当成可达域** |

## 硬规则

```text
value domain ≠ reachable domain
```

domain 说「可能取这些值」；可达性必须另有路径/oracle/完备排除证明。

有 undecided 或 free vars 时，不得对「不可能 / 不可达」返回 `PROVED`。
