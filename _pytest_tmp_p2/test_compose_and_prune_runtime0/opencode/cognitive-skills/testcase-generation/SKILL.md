---
name: testcase-generation
description: 'AscendC 测试生成：初始化契约与绑定、规划不可变目标集 T、并对 T 做 Host replay（R）与源码不可达证明（E）闭环，直到
  T=(R∩T)∪E。

  '
---

# Testcase Generation

集合：

- `D`：Kernel 当前声明的全部 legal Key
- `T`：计划批准的目标，`T ⊆ D`（L3 元素为 `(key, site, outcome)`）
- `R`：真实 Host replay 见证
- `E`：源码证明不可达（含字段 pin → `key_determined`）

完成：

```text
T = (R ∩ T) ∪ E
R ∩ E = ∅
```

## 三阶段方法（认知，非编排）

1. **Init**：契约清楚、绑定有证据；权威是 `.uo`。细节：`references/construction-contract.md`、`references/construction-binding.md`。
2. **Plan**：只冻结 T，不构造 case / 不跑 Host / 不证明不可达。默认 `T=D`。细节：`references/planning.md`。
3. **Solve / Closure**：oracle → rebuild R → search/construct → residual → lemma → certify。

## 核心循环

```text
approved T → oracle → rebuild R → search/construct open(T)
  → Host verdict (HIT→R | REWRITE/REFUSE→residual | CRASH≠E)
  → stable residual → UO + source lemma → counterexample vs R → referee → E
  → certify T
```

## L3 分支结局

Plan `level=L3` / `branch_outcome_coverage`：TD dump + `branch_eval` 增长 R；lemma 字段 pin 使对侧入 E。浅 writer 不得单独入 E。

## 纪律

- 预测 / 模型 / Z3-approx 只能排序候选，不能入 E。
- Lemma 必须有源码引用，并检查入口、early return、all writers、顺序、异常路径。
- 真实 witness 推翻 lemma 时立即撤销并重建 E。
- 改变 T 回到 Plan，不在 Solve 内改计划。
- 查代码：先 CodeMapQuery，再最小源码窗口。

## 按需参考

| 需要 | 读取 |
|---|---|
| Plan / 覆盖梯子 | `references/planning.md` |
| Closure 安全 | `references/closure-safety.md` |
| 搜索饱和 | `references/search.md` |
| Oracle | `references/oracle.md` |
| 证书 | `references/certificate.md` |
| 失败模式 | `references/failure-patterns.md` |
| Init 契约 | `references/construction-contract.md` |
| Init 绑定 | `references/construction-binding.md` |
| 踩坑 | `references/gotchas.md` |

源码引理细节见独立 Skill：`source-proof`。
