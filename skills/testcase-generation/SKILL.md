---
name: testcase-generation
description: >
  AscendC 测试生成：初始化契约与绑定、规划不可变目标集 T、并对 T 做
  Host replay（R）与源码不可达证明（E）闭环，直到 T=(R∩T)∪E。
  Solve 按轮循环：构造→Replay→Round Analysis；预期增长则轮内对 reject
  证引理，非预期增长则基于已发现 key + 源码定向再构造。
  日常精度/性能 overlay：T 为 ScenarioSet，针对性构造少量 CSV，禁止笛卡尔全量 legal key。
---

# Testcase Generation

集合：

- `D`：Kernel 当前声明的全部 legal Key
- `T`：计划批准的目标，`T ⊆ D`（L3 元素为 `(key, site, outcome)`）
- `R`：真实 Host replay 见证
- `E`：源码证明不可达（含字段 pin → `key_determined`）

完成条件：

```text
T = (R ∩ T) ∪ E
R ∩ E = ∅
```

Solve 闭合的是计划目标 **T**。全覆盖证书还要求 `D = (R ∩ D) ∪ E`（当 `T=D` 时两者重合）。`scenario_targeted` 的 T 是 ScenarioSet，不会把 T 改写成 D。

## 三阶段方法（认知，非编排）

1. **Init**：契约清楚、绑定有证据；权威是 `.uo`。细节：`references/construction-contract.md`、`references/construction-binding.md`。
2. **Plan**：只冻结 T。默认 `T=D`。细节：`references/planning.md`。
3. **Solve / Closure**：oracle → rebuild R → **轮次循环**（构造/Replay → Round Analysis → 轮内引理或定向构造）→ certify。
   Overlay `scenario_targeted` 冻结的是 ScenarioSet（精度/性能场景），不是 `T=D`。全覆盖 overlay 仍是 `tilingkey_full_coverage`。

## 核心循环（每轮立刻分析）

```text
approved T → oracle → rebuild R
  → Round:
        construct/search candidates
          → Host Replay
          → Round Analysis（当场，不攒到最后）
                ├ expected growth
                │     → 本轮 reject / exclusive open → source lemma → E
                │     → 剩余 open 沿有效方向继续
                └ unexpected growth
                      → 已发现 key ∈ R + CodeMap/源码 → 定向再构造
  → certify T when Open=∅
```

纪律（正向完成条件在前）：

- 每轮 Round Analysis 当场证引理：`Replay reject` 只在完整源码证明通过后才能进 E。
- 预测 / 模型 / 近似排序只排序候选。
- 真实 witness 推翻 lemma 时立即撤销并重建 E。
- 改变 T 回到 Plan。
- 查代码：先 CodeMapQuery，再最小源码窗口。

Hard guardrail：`Replay reject ≠ 不可达`。红绿测试失败不能替代 E。

## L3 分支结局

Plan `level=L3` / `branch_outcome_coverage`：TD dump + `branch_eval` 增长 R；lemma 字段 pin 使对侧入 E。浅 writer 单独不能入 E。同样按轮分析。

## 按需参考

| 需要 | 读取 |
|---|---|
| Plan / 覆盖梯子 | `references/planning.md` |
| Closure 安全 | `references/closure-safety.md` |
| 搜索 / 轮次分析 | `references/search.md` |
| Oracle | `references/oracle.md` |
| 证书 | `references/certificate.md` |
| 失败模式 | `references/failure-patterns.md` |
| Init 契约 | `references/construction-contract.md` |
| Init 绑定 | `references/construction-binding.md` |
| 测试脚本仓（精度/性能 CSV） | `references/test-script-repo.md` |
| 踩坑 | `references/gotchas.md` |
| 场景 overlay（日常精度/性能） | `references/targeted-construct.md`、`references/harness-oracle.md` |
| 场景 id（权威在 CE；Action profile 物化，不在此 skill 内联） | Context Profile `references` → CE `scenario-catalog.md` |
| 精度 / 性能 knobs | `references/precision-scenarios.md`、`references/perf-scenarios.md` |
| 黑盒因子意图 | `references/blackbox-factors.md` |
| 白盒路径 | `references/whitebox-paths.md` |
| 针对性构造 | `references/targeted-construct.md` |
| Init 审计 METHOD | `capabilities/tg-init-audit/METHOD.md` |
| Closure 审计 METHOD | `capabilities/closure-audit/METHOD.md` |

源码引理细节见独立 Skill：`source-proof`。
